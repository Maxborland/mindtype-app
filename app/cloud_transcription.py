"""MindType Cloud transcription client and desktop transcriber adapter.

The client deliberately keeps the server lifecycle explicit:

1. create a short-lived license session;
2. upload media in bounded parts;
3. create and poll a transcription job;
4. fetch and validate the canonical result;
5. acknowledge the job only after the caller has saved the result locally.

The last step is intentionally not part of :meth:`transcribe_file`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import uuid4


DEFAULT_PART_SIZE = 8 * 1024 * 1024
MAX_UPLOAD_BYTES = 4 * 1024 * 1024 * 1024
MAX_DURATION_SECONDS = 8 * 60 * 60
SPOOL_RESERVE_BYTES = 64 * 1024 * 1024
DEFAULT_POLL_TIMEOUT_SECONDS = 8 * 60 * 60

ProgressCallback = Callable[[str, int, int], None]
CancelCheck = Callable[[], bool]


class CloudTranscriptionError(RuntimeError):
    """Provider-neutral Cloud failure exposed to the desktop."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: Optional[int] = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.retryable = retryable


class CloudTranscriptionCancelled(CloudTranscriptionError):
    def __init__(self) -> None:
        super().__init__("CANCELLED", "Cloud transcription was cancelled")


@dataclass
class CloudSession:
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    entitlement_lease: str
    claim_version: int


@dataclass(frozen=True)
class CloudTranscriptionOutcome:
    operation_id: str
    job_id: str
    segments: List[Dict[str, Any]]
    language: Optional[str]
    confidence: float
    duration_seconds: float
    speaker_names: Dict[str, str]
    provider: str
    model: str
    warnings: List[Any]
    # Complete canonical payload for a follow-up Cloud summary. The summary
    # client redacts local-only source metadata before sending it back.
    canonical_result: Optional[Dict[str, Any]] = None
    transcript_artifact_id: Optional[str] = None


class CloudTranscriptionClient:
    """Small stdlib HTTP client for the existing MindType Cloud API."""

    def __init__(
        self,
        *,
        base_url: str,
        license_key: str,
        device_id: str,
        desktop_version: str,
        platform: str,
        request_timeout: int = 30,
        poll_interval_seconds: float = 2.0,
        poll_timeout_seconds: float = DEFAULT_POLL_TIMEOUT_SECONDS,
        part_size: int = DEFAULT_PART_SIZE,
        spool_dir: Optional[Path] = None,
        progress_callback: Optional[ProgressCallback] = None,
        cancel_check: Optional[CancelCheck] = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:

        if part_size <= 0:
            raise ValueError("part_size must be positive")

        self.base_url = base_url.rstrip("/")
        self.license_key = license_key.strip()
        self.device_id_hash = self._normalize_device_hash(device_id)
        self.desktop_version = desktop_version
        self.platform = self._normalize_platform(platform)
        self.request_timeout = request_timeout
        self.poll_interval_seconds = poll_interval_seconds
        self.poll_timeout_seconds = poll_timeout_seconds
        self.part_size = part_size
        self.spool_dir = Path(spool_dir or Path(tempfile.gettempdir()) / 'MindType' / 'spool')
        self.progress_callback = progress_callback
        self.cancel_check = cancel_check
        self._sleep = sleep
        self._clock = clock
        self._session: Optional[CloudSession] = None

    @staticmethod
    def _normalize_device_hash(device_id: str) -> str:
        value = device_id.strip().lower()
        if len(value) == 64 and all(char in "0123456789abcdef" for char in value):
            return value
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize_platform(platform: str) -> str:
        return {
            "win32": "windows",
            "darwin": "macos",
        }.get(platform, platform)

    def set_cancel_check(self, cancel_check: CancelCheck) -> None:
        self.cancel_check = cancel_check

    def _check_cancelled(self) -> None:
        if self.cancel_check is not None and self.cancel_check():
            raise CloudTranscriptionCancelled()

    def _progress(self, stage: str, current: int, total: int) -> None:
        if self.progress_callback is not None:
            self.progress_callback(stage, current, total)

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        token: Optional[str] = None,
        body: Optional[Dict[str, Any]] = None,
        raw_body: Optional[bytes] = None,
        headers: Optional[Dict[str, str]] = None,
        check_cancelled: bool = True,
    ) -> Dict[str, Any]:
        if check_cancelled:
            self._check_cancelled()
        request_headers = {
            "Accept": "application/json",
            "User-Agent": f"MindType/{self.desktop_version}",
        }
        if token:
            request_headers["Authorization"] = f"Bearer {token}"
        if headers:
            request_headers.update(headers)

        data: Optional[bytes]
        if body is not None:
            data = json.dumps(body, separators=(",", ":")).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        else:
            data = raw_body
            if raw_body is not None:
                request_headers["Content-Type"] = "application/octet-stream"
        if data is not None:
            request_headers["Content-Length"] = str(len(data))

        request = Request(
            f"{self.base_url}/{path.lstrip('/')}",
            data=data,
            headers=request_headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self.request_timeout) as response:
                payload = response.read()
        except HTTPError as error:
            raw_error = error.read()
            try:
                parsed = json.loads(raw_error.decode("utf-8"))
                envelope = parsed.get("error", parsed)
                code = str(envelope.get("code", f"HTTP_{error.code}"))
                message = str(envelope.get("message", error.reason))
                retryable = bool(envelope.get("retryable", False))
            except Exception:
                code = f"HTTP_{error.code}"
                message = str(error.reason)
                retryable = error.code >= 500
            raise CloudTranscriptionError(
                code,
                message,
                status=error.code,
                retryable=retryable,
            ) from error
        except URLError as error:
            raise CloudTranscriptionError(
                "NETWORK_ERROR",
                f"MindType Cloud is unavailable: {error.reason}",
                retryable=True,
            ) from error

        if not payload:
            return {}
        try:
            parsed = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CloudTranscriptionError(
                "INVALID_RESPONSE",
                "MindType Cloud returned invalid JSON",
            ) from error
        if not isinstance(parsed, dict):
            raise CloudTranscriptionError(
                "INVALID_RESPONSE",
                "MindType Cloud returned an invalid response",
            )
        return parsed

    @staticmethod
    def _parse_session(payload: Dict[str, Any]) -> CloudSession:
        try:
            expires_at = datetime.fromisoformat(
                str(payload["access_expires_at"]).replace("Z", "+00:00")
            )
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            return CloudSession(
                access_token=str(payload["access_token"]),
                access_expires_at=expires_at,
                refresh_token=str(payload["refresh_token"]),
                entitlement_lease=str(payload["entitlement_lease"]),
                claim_version=int(payload["claim_version"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise CloudTranscriptionError(
                "INVALID_RESPONSE",
                "MindType Cloud returned an invalid session",
            ) from error

    def create_session(self) -> CloudSession:
        session_path = (
            "/api/license/session"
            if self.license_key
            else "/api/license/trial-session"
        )
        session_body = {
            "device_id_hash": self.device_id_hash,
            "desktop_version": self.desktop_version,
            "platform": self.platform,
        }
        if self.license_key:
            session_body["license_key"] = self.license_key
        payload = self._request_json(
            "POST",
            session_path,
            body=session_body,
        )
        self._session = self._parse_session(payload)
        return self._session

    def _refresh_session(self) -> CloudSession:
        if self._session is None:
            return self.create_session()
        payload = self._request_json(
            "POST",
            "/api/license/session/refresh",
            body={"refresh_token": self._session.refresh_token},
        )
        self._session = self._parse_session(payload)
        return self._session

    def _access_token(self) -> str:
        if self._session is None:
            return self.create_session().access_token
        remaining = (self._session.access_expires_at - self._clock()).total_seconds()
        if remaining <= 30:
            return self._refresh_session().access_token
        return self._session.access_token

    def access_token(self) -> str:
        """Return a valid short-lived Cloud access token."""
        return self._access_token()

    def validate_media(
        self,
        path: Path,
        duration_seconds: Optional[float] = None,
    ) -> None:
        media_path = Path(path)
        if not media_path.is_file():
            raise CloudTranscriptionError(
                "INVALID_MEDIA",
                f"Media file does not exist: {media_path}",
            )
        size = media_path.stat().st_size
        if size <= 0:
            raise CloudTranscriptionError("INVALID_MEDIA", "Media file is empty")
        if size > MAX_UPLOAD_BYTES:
            raise CloudTranscriptionError(
                "INVALID_MEDIA",
                "Media file exceeds the 4 GiB MindType Cloud limit",
            )
        if duration_seconds is not None and duration_seconds > MAX_DURATION_SECONDS:
            raise CloudTranscriptionError(
                "INVALID_MEDIA",
                "Recording exceeds the 8 hour MindType Cloud limit",
            )

        self.spool_dir.mkdir(parents=True, exist_ok=True)
        free_bytes = shutil.disk_usage(self.spool_dir).free
        if free_bytes < size + SPOOL_RESERVE_BYTES:
            raise CloudTranscriptionError(
                "INSUFFICIENT_STORAGE",
                "Not enough free disk space for the secure upload spool",
            )

    def _prepare_spool(self, path: Path) -> Tuple[Path, int, str]:
        media_path = Path(path)
        self.validate_media(media_path)
        size = media_path.stat().st_size
        spool_path = self.spool_dir / f"{uuid4().hex}{media_path.suffix}.spool"
        digest = hashlib.sha256()
        copied = 0
        self._progress("hashing", 0, size)
        try:
            with media_path.open("rb") as source, spool_path.open("xb") as target:
                while chunk := source.read(self.part_size):
                    self._check_cancelled()
                    target.write(chunk)
                    digest.update(chunk)
                    copied += len(chunk)
                    self._progress("hashing", copied, size)
        except Exception:
            spool_path.unlink(missing_ok=True)
            raise
        return spool_path, copied, digest.hexdigest()

    def _cancel_upload(self, upload_id: str) -> None:
        try:
            self._request_json(
                "DELETE",
                f"/v1/uploads/{quote(upload_id, safe='')}",
                token=self._access_token(),
                check_cancelled=False,
            )
        except CloudTranscriptionError:
            pass

    def _cancel_job(self, job_id: str) -> None:
        try:
            self._request_json(
                "DELETE",
                f"/v1/transcriptions/{quote(job_id, safe='')}",
                token=self._access_token(),
                check_cancelled=False,
            )
        except CloudTranscriptionError:
            pass

    def transcribe_file(
        self,
        path: Path,
        *,
        language: str = "auto",
        diarization: bool = True,
        word_timestamps: bool = True,
        quality_profile: str = "balanced",
    ) -> CloudTranscriptionOutcome:
        media_path = Path(path)
        if not media_path.is_file():
            raise CloudTranscriptionError(
                "INVALID_MEDIA",
                f"Media file does not exist: {media_path}",
            )

        self.validate_media(media_path)
        spool_path, size, sha256 = self._prepare_spool(media_path)

        operation_id = str(uuid4())
        upload_id: Optional[str] = None
        job_id: Optional[str] = None
        transcript_artifact_id: Optional[str] = None
        try:
            upload = self._request_json(
                "POST",
                "/v1/uploads",
                token=self._access_token(),
                headers={"Idempotency-Key": f"{operation_id}:upload"},
                body={
                    "size": size,
                    "sha256": sha256,
                    "part_size": self.part_size,
                },
            )
            upload_id = str(upload["id"])
            upload_token = str(upload["upload_token"])

            uploaded = 0
            part_number = 0
            with spool_path.open("rb") as source:
                while chunk := source.read(self.part_size):
                    self._check_cancelled()
                    part_number += 1
                    self._request_json(
                        "PUT",
                        (
                            f"/v1/uploads/{quote(upload_id, safe='')}/parts/"
                            f"{part_number}"
                        ),
                        token=upload_token,
                        raw_body=chunk,
                        headers={
                            "x-part-sha256": hashlib.sha256(chunk).hexdigest(),
                        },
                    )
                    uploaded += len(chunk)
                    self._progress("uploading", uploaded, size)

            self._request_json(
                "POST",
                f"/v1/uploads/{quote(upload_id, safe='')}/complete",
                token=upload_token,
                body={"sha256": sha256, "parts": part_number},
            )

            created = self._request_json(
                "POST",
                "/v1/transcriptions",
                token=self._access_token(),
                headers={"Idempotency-Key": f"{operation_id}:transcribe"},
                body={
                    "operation_id": operation_id,
                    "upload_id": upload_id,
                    "options": {
                        "language": language,
                        "word_timestamps": word_timestamps,
                        "diarization": diarization,
                        "quality_profile": quality_profile,
                    },
                },
            )
            job_id = str(created["id"])

            deadline = time.monotonic() + self.poll_timeout_seconds
            while True:
                self._check_cancelled()
                state = self._request_json(
                    "GET",
                    f"/v1/transcriptions/{quote(job_id, safe='')}",
                    token=self._access_token(),
                )
                state_name = str(state.get("state", ""))
                self._progress("transcribing", 1 if state_name == "succeeded" else 0, 1)
                if state_name == "succeeded":
                    if state.get("result_artifact_id"):
                        transcript_artifact_id = str(state["result_artifact_id"])
                    break
                if state_name in {"failed", "cancelled", "awaiting_funds"}:
                    error = state.get("error") or {}
                    raise CloudTranscriptionError(
                        str(error.get("code", state_name.upper())),
                        str(error.get("message", f"Cloud job {state_name}")),
                        retryable=bool(error.get("retryable", False)),
                    )
                if state_name not in {"queued", "running", "cancelling"}:
                    raise CloudTranscriptionError(
                        "INVALID_RESPONSE",
                        f"MindType Cloud returned unknown job state: {state_name}",
                    )
                if time.monotonic() >= deadline:
                    raise CloudTranscriptionError(
                        "TIMEOUT",
                        "MindType Cloud transcription timed out",
                        retryable=True,
                    )
                self._sleep(self.poll_interval_seconds)

            result_payload = self._request_json(
                "GET",
                f"/v1/transcriptions/{quote(job_id, safe='')}/result",
                token=self._access_token(),
            )
            canonical = self._validate_canonical(
                result_payload.get("result"),
                operation_id,
            )
            return self._outcome(
                canonical,
                operation_id,
                job_id,
                transcript_artifact_id=transcript_artifact_id,
            )
        except CloudTranscriptionCancelled:
            if job_id:
                self._cancel_job(job_id)
            elif upload_id:
                self._cancel_upload(upload_id)
            raise
        except CloudTranscriptionError:
            if upload_id and not job_id:
                self._cancel_upload(upload_id)
            raise
        except (KeyError, TypeError, ValueError) as error:
            if upload_id and not job_id:
                self._cancel_upload(upload_id)
            raise CloudTranscriptionError(
                "INVALID_RESPONSE",
                "MindType Cloud returned an incomplete response",
            ) from error
        finally:
            spool_path.unlink(missing_ok=True)

    @staticmethod
    def _validate_canonical(
        payload: Any,
        expected_operation_id: str,
    ) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise CloudTranscriptionError(
                "SCHEMA_UNSUPPORTED",
                "Canonical transcription result is missing",
            )
        version = str(payload.get("schema_version", ""))
        if not version.startswith("1."):
            raise CloudTranscriptionError(
                "SCHEMA_UNSUPPORTED",
                "Canonical transcription schema is unsupported",
            )
        if payload.get("operation_id") != expected_operation_id:
            raise CloudTranscriptionError(
                "SCHEMA_UNSUPPORTED",
                "Canonical transcription belongs to another operation",
            )
        transcript = payload.get("transcript")
        if not isinstance(transcript, dict) or not isinstance(
            transcript.get("segments"), list
        ):
            raise CloudTranscriptionError(
                "SCHEMA_UNSUPPORTED",
                "Canonical transcription segments are invalid",
            )
        seen_ids = set()
        for item in transcript["segments"]:
            if not isinstance(item, dict):
                raise CloudTranscriptionError(
                    "SCHEMA_UNSUPPORTED",
                    "Canonical transcription segment is invalid",
                )
            segment_id = item.get("segment_id")
            if not segment_id or segment_id in seen_ids:
                raise CloudTranscriptionError(
                    "SCHEMA_UNSUPPORTED",
                    "Canonical transcription has duplicate segment IDs",
                )
            seen_ids.add(segment_id)
            if int(item.get("start_ms", -1)) > int(item.get("end_ms", -1)):
                raise CloudTranscriptionError(
                    "SCHEMA_UNSUPPORTED",
                    "Canonical transcription has inverted timestamps",
                )
        return payload

    @staticmethod
    def _outcome(
        canonical: Dict[str, Any],
        operation_id: str,
        job_id: str,
        *,
        transcript_artifact_id: Optional[str] = None,
    ) -> CloudTranscriptionOutcome:
        transcript = canonical["transcript"]
        route = canonical.get("route", {}).get("transcription", {})
        source = canonical.get("source", {})
        segments: List[Dict[str, Any]] = []
        for item in transcript["segments"]:
            words = [
                {
                    **word,
                    "start": float(word.get("start_ms", 0)) / 1000,
                    "end": float(word.get("end_ms", 0)) / 1000,
                }
                for word in item.get("words", [])
            ]
            segments.append(
                {
                    "start": float(item["start_ms"]) / 1000,
                    "end": float(item["end_ms"]) / 1000,
                    "text": str(item.get("text", "")),
                    "speaker": item.get("speaker_id"),
                    "words": words,
                }
            )

        speaker_names: Dict[str, str] = {}
        for index, speaker in enumerate(canonical.get("speakers", []), start=1):
            if not isinstance(speaker, dict) or not speaker.get("speaker_id"):
                continue
            speaker_id = str(speaker["speaker_id"])
            speaker_names[speaker_id] = str(
                speaker.get("display_name")
                or speaker.get("name")
                or f"Speaker {index}"
            )

        confidence = transcript.get("confidence")
        return CloudTranscriptionOutcome(
            operation_id=operation_id,
            job_id=job_id,
            segments=segments,
            language=transcript.get("language"),
            confidence=float(confidence) if confidence is not None else 0.0,
            duration_seconds=float(source.get("duration_ms", 0)) / 1000,
            speaker_names=speaker_names,
            provider=str(route.get("provider", "mindtype_cloud")),
            model=str(route.get("model", "auto")),
            warnings=list(canonical.get("warnings", [])),
            canonical_result=dict(canonical),
            transcript_artifact_id=transcript_artifact_id,
        )

    def acknowledge(self, job_id: str) -> None:
        self._request_json(
            "POST",
            f"/v1/transcriptions/{quote(job_id, safe='')}/ack",
            token=self._access_token(),
            body={},
        )


class MindTypeCloudTranscriber:
    """Adapter that satisfies the existing desktop Transcriber protocol."""

    def __init__(
        self,
        *,
        base_url: str,
        license_key: str,
        device_id: str,
        desktop_version: str,
        platform: str,
        client: Optional[CloudTranscriptionClient] = None,
    ) -> None:
        self.client = client or CloudTranscriptionClient(
            base_url=base_url,
            license_key=license_key,
            device_id=device_id,
            desktop_version=desktop_version,
            platform=platform,
        )
        self._last_outcome: Optional[CloudTranscriptionOutcome] = None

    def set_cancel_check(self, cancel_check: CancelCheck) -> None:
        self.client.set_cancel_check(cancel_check)

    def validate_media(
        self,
        path: Path,
        duration_seconds: Optional[float] = None,
    ) -> None:
        self.client.validate_media(path, duration_seconds)

    def load_model(self, *args: Any, **kwargs: Any) -> None:
        """Cloud chooses the current production model; there is nothing to load."""

    def transcribe_with_timestamps(
        self,
        audio_path: Path,
        language: str,
        beam_size: int,
        vad_filter: bool,
        word_timestamps: bool = True,
    ) -> Tuple[List[Dict[str, Any]], Optional[str], float]:
        del beam_size, vad_filter
        outcome = self.client.transcribe_file(
            Path(audio_path),
            language=language,
            diarization=True,
            word_timestamps=word_timestamps,
        )
        self._last_outcome = outcome
        return outcome.segments, outcome.language, outcome.confidence

    def transcribe(
        self,
        audio_path: Path,
        language: str,
        beam_size: int,
        vad_filter: bool,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> Tuple[str, Optional[str], float]:
        del progress_callback
        segments, detected_language, confidence = self.transcribe_with_timestamps(
            audio_path,
            language,
            beam_size,
            vad_filter,
        )
        return (
            " ".join(str(item.get("text", "")) for item in segments).strip(),
            detected_language,
            confidence,
        )

    def transcribe_stream(
        self,
        audio_path: Path,
        language: str,
        beam_size: int,
        vad_filter: bool,
    ) -> Iterable[Tuple[str, Optional[str], float]]:
        yield self.transcribe(audio_path, language, beam_size, vad_filter)

    def consume_last_outcome(self) -> Optional[CloudTranscriptionOutcome]:
        outcome = self._last_outcome
        self._last_outcome = None
        return outcome

    def acknowledge_result(self, job_id: str) -> None:
        self.client.acknowledge(job_id)

    def acknowledge_summary(self, job_id: str) -> None:
        from .cloud_summary import CloudSummaryClient

        CloudSummaryClient(self.client).acknowledge(job_id)
