from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Protocol, Sequence
from urllib.parse import quote, urlparse

from ..operation_coordinator import (
    OperationCoordinator,
    StaleOperationCallback,
)
from ..operation_models import (
    OperationRecord,
    OperationStage,
    OperationStatus,
    utc_now,
)
from ..result_schema import CanonicalResultError, validate_canonical_result


DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024
DEFAULT_RETRY_DELAYS = (1, 2, 5, 15, 30)
DEFAULT_MAX_RESPONSE_BYTES = 64 * 1024 * 1024


class CloudErrorCode(str, Enum):
    AUTH_REQUIRED = "AUTH_REQUIRED"
    ENTITLEMENT_EXPIRED = "ENTITLEMENT_EXPIRED"
    INSUFFICIENT_CREDITS = "INSUFFICIENT_CREDITS"
    RATE_LIMITED = "RATE_LIMITED"
    UPLOAD_EXPIRED = "UPLOAD_EXPIRED"
    INVALID_MEDIA = "INVALID_MEDIA"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    JOB_CANCELLED = "JOB_CANCELLED"
    RESULT_EXPIRED = "RESULT_EXPIRED"
    SCHEMA_UNSUPPORTED = "SCHEMA_UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


class CloudAPIError(RuntimeError):
    def __init__(
        self,
        code: CloudErrorCode,
        message: str,
        *,
        retryable: bool,
        retry_after_seconds: Optional[float] = None,
        job_id: Optional[str] = None,
        http_status: Optional[int] = None,
    ):
        super().__init__(message or code.value)
        self.code = code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        self.job_id = job_id
        self.http_status = http_status


class TransportError(OSError):
    """The request did not receive an HTTP response."""


class ResponseTooLargeError(OSError):
    """The peer exceeded the bounded desktop response contract."""


@dataclass(frozen=True)
class HTTPResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class HTTPTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: Optional[bytes],
        timeout: float,
    ) -> HTTPResponse: ...


class UrlLibTransport:
    def __init__(
        self,
        *,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        if max_response_bytes < 1:
            raise ValueError("max_response_bytes must be positive")
        self.max_response_bytes = int(max_response_bytes)

    def _read_body(self, response: Any) -> bytes:
        declared = response.headers.get("Content-Length")
        try:
            declared_size = int(declared) if declared is not None else None
        except (TypeError, ValueError):
            declared_size = None
        if (
            declared_size is not None
            and declared_size > self.max_response_bytes
        ):
            raise ResponseTooLargeError(
                "cloud response exceeds the desktop size limit"
            )
        try:
            body = response.read(self.max_response_bytes + 1)
        except OSError as exc:
            raise TransportError(str(exc)) from exc
        if len(body) > self.max_response_bytes:
            raise ResponseTooLargeError(
                "cloud response exceeds the desktop size limit"
            )
        return body

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: Optional[bytes],
        timeout: float,
    ) -> HTTPResponse:
        request = urllib.request.Request(
            url,
            data=body,
            headers=dict(headers),
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return HTTPResponse(
                    status=response.status,
                    headers=dict(response.headers.items()),
                    body=self._read_body(response),
                )
        except urllib.error.HTTPError as exc:
            return HTTPResponse(
                status=exc.code,
                headers=dict(exc.headers.items()) if exc.headers else {},
                body=self._read_body(exc),
            )
        except (TransportError, ResponseTooLargeError):
            raise
        except urllib.error.URLError as exc:
            raise TransportError(str(exc.reason)) from exc
        except OSError as exc:
            raise TransportError(str(exc)) from exc


TokenSource = str | Callable[[], str]


class MindTypeCloudClient:
    """Synchronous HTTP client intended to run inside a desktop worker."""

    def __init__(
        self,
        base_url: str,
        *,
        access_token: TokenSource,
        refresh_access_token: Optional[Callable[[], None]] = None,
        transport: Optional[HTTPTransport] = None,
        timeout: float = 60,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        retry_delays: Sequence[float] = DEFAULT_RETRY_DELAYS,
        sleep: Callable[[float], None] = time.sleep,
        minimum_chunk_size: int = 64 * 1024,
    ):
        parsed = urlparse(base_url)
        loopback = parsed.hostname in {"127.0.0.1", "::1", "localhost"}
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and loopback
        ):
            raise ValueError("MindType Cloud base URL must use HTTPS")
        if parsed.query or parsed.fragment or not parsed.netloc:
            raise ValueError("MindType Cloud base URL is invalid")
        if not minimum_chunk_size <= chunk_size <= 64 * 1024 * 1024:
            raise ValueError("upload chunk size is outside supported bounds")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if any(delay < 0 for delay in retry_delays):
            raise ValueError("retry delays must not be negative")
        self.base_url = base_url.rstrip("/")
        self._access_token = access_token
        self._refresh_access_token = refresh_access_token
        self._transport = transport or UrlLibTransport()
        self._timeout = float(timeout)
        self.chunk_size = int(chunk_size)
        self._retry_delays = tuple(float(delay) for delay in retry_delays)
        self._sleep = sleep

    def _token(self) -> str:
        token = (
            self._access_token()
            if callable(self._access_token)
            else self._access_token
        )
        if not token and self._refresh_access_token is not None:
            self._refresh_access_token()
            token = (
                self._access_token()
                if callable(self._access_token)
                else self._access_token
            )
        if not token:
            raise CloudAPIError(
                CloudErrorCode.AUTH_REQUIRED,
                "cloud access token is missing",
                retryable=False,
            )
        return token

    @staticmethod
    def _json_body(payload: Optional[Mapping[str, Any]]) -> Optional[bytes]:
        if payload is None:
            return None
        return json.dumps(
            dict(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @staticmethod
    def _decode_response(response: HTTPResponse) -> dict[str, Any]:
        if not response.body:
            return {}
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CloudAPIError(
                CloudErrorCode.SCHEMA_UNSUPPORTED,
                "cloud response is not valid JSON",
                retryable=False,
                http_status=response.status,
            ) from exc
        if not isinstance(payload, dict):
            raise CloudAPIError(
                CloudErrorCode.SCHEMA_UNSUPPORTED,
                "cloud response must be a JSON object",
                retryable=False,
                http_status=response.status,
            )
        return payload

    @staticmethod
    def _header(
        headers: Mapping[str, str],
        name: str,
    ) -> Optional[str]:
        wanted = name.casefold()
        return next(
            (
                str(value)
                for key, value in headers.items()
                if str(key).casefold() == wanted
            ),
            None,
        )

    def _error_from_response(
        self,
        response: HTTPResponse,
    ) -> CloudAPIError:
        try:
            payload = self._decode_response(response)
        except CloudAPIError:
            payload = {}
        raw_error = payload.get("error", {})
        error = raw_error if isinstance(raw_error, Mapping) else {}
        raw_code = str(error.get("code", ""))
        try:
            code = CloudErrorCode(raw_code)
        except ValueError:
            if response.status == 401:
                code = CloudErrorCode.AUTH_REQUIRED
            elif response.status == 402:
                code = CloudErrorCode.INSUFFICIENT_CREDITS
            elif response.status == 429:
                code = CloudErrorCode.RATE_LIMITED
            elif response.status >= 500:
                code = CloudErrorCode.PROVIDER_UNAVAILABLE
            else:
                code = CloudErrorCode.UNKNOWN
        retryable = bool(
            error.get(
                "retryable",
                response.status == 429 or response.status >= 500,
            )
        )
        retry_after = error.get("retry_after_seconds")
        if retry_after is None:
            retry_after = self._header(response.headers, "Retry-After")
        try:
            retry_after_seconds = (
                float(retry_after) if retry_after is not None else None
            )
        except (TypeError, ValueError):
            retry_after_seconds = None
        return CloudAPIError(
            code,
            str(error.get("message") or f"HTTP {response.status}"),
            retryable=retryable,
            retry_after_seconds=retry_after_seconds,
            job_id=(
                str(error["job_id"]) if error.get("job_id") is not None else None
            ),
            http_status=response.status,
        )

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        payload: Optional[Mapping[str, Any]] = None,
        raw_body: Optional[bytes] = None,
        headers: Optional[Mapping[str, str]] = None,
        bearer_token: Optional[str] = None,
        retry_safe: bool = False,
    ) -> dict[str, Any]:
        if payload is not None and raw_body is not None:
            raise ValueError("request cannot contain JSON and raw body")
        body = raw_body if raw_body is not None else self._json_body(payload)
        refreshed = False
        retry_index = 0
        while True:
            request_headers = {
                "Accept": "application/json",
                "Authorization": f"Bearer {bearer_token or self._token()}",
                **dict(headers or {}),
            }
            if payload is not None:
                request_headers["Content-Type"] = "application/json"
            elif raw_body is not None:
                request_headers["Content-Type"] = "application/octet-stream"
            try:
                response = self._transport.request(
                    method,
                    f"{self.base_url}{endpoint}",
                    headers=request_headers,
                    body=body,
                    timeout=self._timeout,
                )
            except ResponseTooLargeError as exc:
                raise CloudAPIError(
                    CloudErrorCode.SCHEMA_UNSUPPORTED,
                    str(exc),
                    retryable=False,
                ) from exc
            except TransportError as exc:
                error = CloudAPIError(
                    CloudErrorCode.PROVIDER_UNAVAILABLE,
                    str(exc),
                    retryable=True,
                )
                if retry_safe and retry_index < len(self._retry_delays):
                    self._sleep(self._retry_delays[retry_index])
                    retry_index += 1
                    continue
                raise error from exc

            if 200 <= response.status < 300:
                return self._decode_response(response)
            if (
                response.status == 401
                and not refreshed
                and bearer_token is None
                and self._refresh_access_token is not None
            ):
                self._refresh_access_token()
                refreshed = True
                continue

            error = self._error_from_response(response)
            if (
                retry_safe
                and error.retryable
                and retry_index < len(self._retry_delays)
            ):
                delay = (
                    error.retry_after_seconds
                    if error.retry_after_seconds is not None
                    else self._retry_delays[retry_index]
                )
                self._sleep(delay)
                retry_index += 1
                continue
            raise error

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _path_segment(value: str) -> str:
        if not value:
            raise ValueError("remote identifier must not be empty")
        return quote(str(value), safe="")

    @staticmethod
    def _validate_upload(
        upload: Mapping[str, Any],
        *,
        expected_size: int,
        expected_sha256: str,
        requested_part_size: int,
    ) -> tuple[str, str, set[int], int]:
        upload_id = str(upload.get("id") or "")
        upload_token = str(upload.get("upload_token") or "")
        if not upload_id or not upload_token:
            raise CloudAPIError(
                CloudErrorCode.SCHEMA_UNSUPPORTED,
                "upload response is missing id or upload token",
                retryable=False,
            )
        if upload.get("size") is not None and upload["size"] != expected_size:
            raise CloudAPIError(
                CloudErrorCode.INVALID_MEDIA,
                "existing upload belongs to a different source size",
                retryable=False,
            )
        if (
            upload.get("sha256") is not None
            and str(upload["sha256"]).casefold() != expected_sha256.casefold()
        ):
            raise CloudAPIError(
                CloudErrorCode.INVALID_MEDIA,
                "existing upload belongs to a different source hash",
                retryable=False,
            )
        try:
            uploaded_parts = {
                int(item) for item in upload.get("uploaded_parts", [])
            }
            part_size = int(upload.get("part_size", requested_part_size))
        except (TypeError, ValueError) as exc:
            raise CloudAPIError(
                CloudErrorCode.SCHEMA_UNSUPPORTED,
                "upload response contains invalid part metadata",
                retryable=False,
            ) from exc
        if any(part < 1 for part in uploaded_parts) or not (
            1 <= part_size <= 64 * 1024 * 1024
        ):
            raise CloudAPIError(
                CloudErrorCode.SCHEMA_UNSUPPORTED,
                "upload response contains invalid part metadata",
                retryable=False,
            )
        return upload_id, upload_token, uploaded_parts, part_size

    def create_upload(
        self,
        source_path: Path,
        *,
        operation_id: str,
        source_sha256: Optional[str] = None,
    ) -> dict[str, Any]:
        source = Path(source_path)
        return self._request(
            "POST",
            "/v1/uploads",
            payload={
                "size": source.stat().st_size,
                "sha256": source_sha256 or self._sha256(source),
                "part_size": self.chunk_size,
            },
            headers={"Idempotency-Key": f"{operation_id}:upload"},
            retry_safe=True,
        )

    def get_upload(self, upload_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/v1/uploads/{self._path_segment(upload_id)}",
            retry_safe=True,
        )

    def upload_file(
        self,
        source_path: Path,
        *,
        operation_id: str,
        remote_upload_id: Optional[str] = None,
    ) -> dict[str, Any]:
        source = Path(source_path)
        whole_hash = self._sha256(source)
        upload = (
            self.get_upload(remote_upload_id)
            if remote_upload_id
            else self.create_upload(
                source,
                operation_id=operation_id,
                source_sha256=whole_hash,
            )
        )
        upload_id, upload_token, uploaded_parts, part_size = (
            self._validate_upload(
                upload,
                expected_size=source.stat().st_size,
                expected_sha256=whole_hash,
                requested_part_size=self.chunk_size,
            )
        )
        with source.open("rb") as stream:
            part_number = 0
            while chunk := stream.read(part_size):
                part_number += 1
                if part_number in uploaded_parts:
                    continue
                part_hash = hashlib.sha256(chunk).hexdigest()
                self._request(
                    "PUT",
                    f"/v1/uploads/{self._path_segment(upload_id)}"
                    f"/parts/{part_number}",
                    raw_body=chunk,
                    headers={"X-Part-SHA256": part_hash},
                    bearer_token=upload_token,
                    retry_safe=True,
                )
        return self._request(
            "POST",
            f"/v1/uploads/{self._path_segment(upload_id)}/complete",
            payload={"sha256": whole_hash, "parts": part_number},
            bearer_token=upload_token,
            retry_safe=True,
        )

    def create_transcription(
        self,
        *,
        upload_id: str,
        operation_id: str,
        options: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/transcriptions",
            payload={
                "operation_id": operation_id,
                "upload_id": upload_id,
                "options": dict(options),
            },
            headers={
                "Idempotency-Key": f"{operation_id}:transcription",
            },
            retry_safe=True,
        )

    def get_transcription(self, job_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/v1/transcriptions/{self._path_segment(job_id)}",
            retry_safe=True,
        )

    def recover_or_create_transcription(
        self,
        *,
        remote_job_id: Optional[str],
        upload_id: str,
        operation_id: str,
        options: Mapping[str, Any],
    ) -> dict[str, Any]:
        if remote_job_id:
            return self.get_transcription(remote_job_id)
        return self.create_transcription(
            upload_id=upload_id,
            operation_id=operation_id,
            options=options,
        )

    def get_transcription_result(
        self,
        job_id: str,
        *,
        expected_operation_id: Optional[str] = None,
    ) -> dict[str, Any]:
        payload = self._request(
            "GET",
            f"/v1/transcriptions/{self._path_segment(job_id)}/result",
            retry_safe=True,
        )
        result = payload.get("result", payload)
        return validate_canonical_result(
            result,
            expected_operation_id=expected_operation_id,
        )

    def resume_transcription(self, job_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/transcriptions/{self._path_segment(job_id)}/resume",
            retry_safe=True,
        )

    def acknowledge_transcription(self, job_id: str) -> None:
        self._request(
            "POST",
            f"/v1/transcriptions/{self._path_segment(job_id)}/ack",
            retry_safe=True,
        )

    def cancel_transcription(self, job_id: str) -> dict[str, Any]:
        return self._request(
            "DELETE",
            f"/v1/transcriptions/{self._path_segment(job_id)}",
            retry_safe=True,
        )

    def create_summary(
        self,
        *,
        operation_id: str,
        transcript_artifact_id: Optional[str] = None,
        canonical_transcript: Optional[Mapping[str, Any]] = None,
        options: Mapping[str, Any],
    ) -> dict[str, Any]:
        if (transcript_artifact_id is None) == (
            canonical_transcript is None
        ):
            raise ValueError(
                "provide exactly one cloud summary transcript source"
            )
        preset = str(options.get("preset") or "general")
        input_token_estimate = int(
            options.get("input_token_estimate", 0)
        )
        max_output_tokens = int(options.get("max_output_tokens", 2_000))
        payload: dict[str, Any] = {
            "operation_id": operation_id,
            "preset": preset,
            "input_token_estimate": input_token_estimate,
            "max_output_tokens": max_output_tokens,
        }
        if transcript_artifact_id is not None:
            payload["source_artifact_id"] = transcript_artifact_id
        else:
            payload["transcript"] = dict(canonical_transcript or {})
        return self._request(
            "POST",
            "/v1/summaries",
            payload=payload,
            headers={"Idempotency-Key": f"{operation_id}:summary"},
            retry_safe=True,
        )

    def get_summary(self, job_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/v1/summaries/{self._path_segment(job_id)}",
            retry_safe=True,
        )

    def get_summary_result(
        self,
        job_id: str,
        *,
        expected_operation_id: Optional[str] = None,
    ) -> dict[str, Any]:
        payload = self._request(
            "GET",
            f"/v1/summaries/{self._path_segment(job_id)}/result",
            retry_safe=True,
        )
        result = payload.get("result", payload)
        return validate_canonical_result(
            result,
            expected_operation_id=expected_operation_id,
        )

    def resume_summary(self, job_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/summaries/{self._path_segment(job_id)}/resume",
            retry_safe=True,
        )

    def acknowledge_summary(self, job_id: str) -> None:
        self._request(
            "POST",
            f"/v1/summaries/{self._path_segment(job_id)}/ack",
            retry_safe=True,
        )

    def cancel_summary(self, job_id: str) -> dict[str, Any]:
        return self._request(
            "DELETE",
            f"/v1/summaries/{self._path_segment(job_id)}",
            retry_safe=True,
        )

    def estimate_usage(
        self,
        request: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/usage/estimate",
            payload=request,
            retry_safe=True,
        )

    def get_usage(self) -> dict[str, Any]:
        return self._request("GET", "/v1/usage", retry_safe=True)

    def get_models(self) -> dict[str, Any]:
        return self._request("GET", "/v1/models", retry_safe=True)


class MindTypeCloudExecutor:
    """Advance one durable cloud transcription without hiding remote state."""

    _ACTIVE_STATES = {
        "awaiting_upload",
        "queued",
        "running",
    }

    def __init__(
        self,
        *,
        client: MindTypeCloudClient,
        coordinator: OperationCoordinator,
    ) -> None:
        self.client = client
        self.coordinator = coordinator

    @staticmethod
    def _required_remote_id(
        payload: Mapping[str, Any],
        *,
        resource: str,
    ) -> str:
        identifier = str(payload.get("id") or "")
        if not identifier:
            raise CloudAPIError(
                CloudErrorCode.SCHEMA_UNSUPPORTED,
                f"{resource} response is missing id",
                retryable=False,
            )
        return identifier

    def _remember_remote_id(
        self,
        operation_id: str,
        *,
        key: str,
        remote_id: str,
        stage: OperationStage,
    ) -> OperationRecord:
        operation = self.coordinator.store.get(operation_id)
        if operation is None:
            raise KeyError(operation_id)
        if operation.status in {
            OperationStatus.CANCEL_REQUESTED,
            OperationStatus.COMPLETED,
            OperationStatus.FAILED,
            OperationStatus.CANCELLED,
        }:
            raise StaleOperationCallback(
                "remote identifier ignored for terminal operation"
            )
        identifiers = dict(operation.server_job_ids)
        identifiers[key] = remote_id
        return self.coordinator.store.transition(
            operation_id,
            operation.status,
            stage=stage,
            server_job_ids=identifiers,
        )

    def _retryable(
        self,
        operation_id: str,
        *,
        code: str,
        retry_after_seconds: Optional[float] = None,
    ) -> OperationRecord:
        retry_after = (
            utc_now() + timedelta(seconds=max(0.0, retry_after_seconds))
            if retry_after_seconds is not None
            else None
        )
        return self.coordinator.store.transition(
            operation_id,
            OperationStatus.RETRYABLE,
            last_error_code=code,
            retry_after=retry_after,
        )

    def _with_local_source_metadata(
        self,
        operation_id: str,
        result: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Restore filename-free metadata that never leaves the desktop."""
        normalized = dict(result)
        source = normalized.get("source")
        if not isinstance(source, Mapping):
            return normalized

        local_metadata = self.coordinator.spool.read_operation_metadata(
            operation_id
        )
        normalized_source = dict(source)
        display_name = local_metadata.get("display_name")
        if isinstance(display_name, str) and display_name.strip():
            normalized_source["display_name"] = display_name
        channels = local_metadata.get("channels")
        if (
            isinstance(channels, list)
            and channels
            and not normalized_source.get("channels")
        ):
            normalized_source["channels"] = channels
        normalized["source"] = normalized_source
        return normalized

    def _handle_summary_job(
        self,
        operation_id: str,
        job: Mapping[str, Any],
    ) -> OperationRecord:
        state = str(job.get("state") or "")
        if state in self._ACTIVE_STATES:
            return self.coordinator.store.transition(
                operation_id,
                OperationStatus.RUNNING,
                stage=OperationStage.SUMMARIZE,
            )
        if state == "awaiting_funds":
            return self._retryable(
                operation_id,
                code=CloudErrorCode.INSUFFICIENT_CREDITS.value,
            )
        if state == "expired":
            return self.coordinator.store.transition(
                operation_id,
                OperationStatus.FAILED,
                last_error_code=CloudErrorCode.RESULT_EXPIRED.value,
            )
        if state == "cancelling":
            operation = self.coordinator.store.get(operation_id)
            if operation is None:
                raise KeyError(operation_id)
            if operation.status is not OperationStatus.CANCEL_REQUESTED:
                return self.coordinator.request_cancel(operation_id)
            return operation
        if state == "cancelled":
            operation = self.coordinator.store.get(operation_id)
            if operation is None:
                raise KeyError(operation_id)
            if operation.status is not OperationStatus.CANCEL_REQUESTED:
                self.coordinator.request_cancel(operation_id)
            return self.coordinator.finish_cancel(operation_id)
        if state == "failed":
            raw_error = job.get("error")
            error = raw_error if isinstance(raw_error, Mapping) else {}
            code = str(error.get("code") or "CLOUD_SUMMARY_FAILED")
            if bool(error.get("retryable", False)):
                retry_after = error.get("retry_after_seconds")
                try:
                    seconds = (
                        float(retry_after)
                        if retry_after is not None
                        else None
                    )
                except (TypeError, ValueError):
                    seconds = None
                return self._retryable(
                    operation_id,
                    code=code,
                    retry_after_seconds=seconds,
                )
            return self.coordinator.store.transition(
                operation_id,
                OperationStatus.FAILED,
                last_error_code=code,
            )
        if state != "succeeded":
            raise CloudAPIError(
                CloudErrorCode.SCHEMA_UNSUPPORTED,
                f"unsupported cloud summary state: {state or '<missing>'}",
                retryable=False,
            )

        operation = self.coordinator.store.get(operation_id)
        if operation is None:
            raise KeyError(operation_id)
        summary_id = operation.server_job_ids.get("summary")
        if not summary_id:
            raise CloudAPIError(
                CloudErrorCode.SCHEMA_UNSUPPORTED,
                "succeeded summary has no persisted job identity",
                retryable=False,
            )
        result = self.client.get_summary_result(
            summary_id,
            expected_operation_id=operation_id,
        )
        result = self._with_local_source_metadata(operation_id, result)
        completed = self.coordinator.save_canonical_result(
            operation_id,
            result,
        )
        return completed

    def _handle_job(
        self,
        operation_id: str,
        job: Mapping[str, Any],
        *,
        summary_options: Optional[Mapping[str, Any]] = None,
    ) -> OperationRecord:
        state = str(job.get("state") or "")
        if state in self._ACTIVE_STATES:
            operation = self.coordinator.store.get(operation_id)
            if operation is None:
                raise KeyError(operation_id)
            return self.coordinator.store.transition(
                operation_id,
                OperationStatus.RUNNING,
                stage=OperationStage.TRANSCRIBE,
            )
        if state == "awaiting_funds":
            return self._retryable(
                operation_id,
                code=CloudErrorCode.INSUFFICIENT_CREDITS.value,
            )
        if state == "expired":
            return self.coordinator.store.transition(
                operation_id,
                OperationStatus.FAILED,
                last_error_code=CloudErrorCode.RESULT_EXPIRED.value,
            )
        if state == "cancelling":
            operation = self.coordinator.store.get(operation_id)
            if operation is None:
                raise KeyError(operation_id)
            if operation.status is not OperationStatus.CANCEL_REQUESTED:
                return self.coordinator.request_cancel(operation_id)
            return operation
        if state == "cancelled":
            operation = self.coordinator.store.get(operation_id)
            if operation is None:
                raise KeyError(operation_id)
            if operation.status is not OperationStatus.CANCEL_REQUESTED:
                self.coordinator.request_cancel(operation_id)
            return self.coordinator.finish_cancel(operation_id)
        if state == "failed":
            raw_error = job.get("error")
            error = raw_error if isinstance(raw_error, Mapping) else {}
            code = str(error.get("code") or "CLOUD_JOB_FAILED")
            if bool(error.get("retryable", False)):
                retry_after = error.get("retry_after_seconds")
                try:
                    seconds = (
                        float(retry_after)
                        if retry_after is not None
                        else None
                    )
                except (TypeError, ValueError):
                    seconds = None
                return self._retryable(
                    operation_id,
                    code=code,
                    retry_after_seconds=seconds,
                )
            return self.coordinator.store.transition(
                operation_id,
                OperationStatus.FAILED,
                last_error_code=code,
            )
        if state != "succeeded":
            raise CloudAPIError(
                CloudErrorCode.SCHEMA_UNSUPPORTED,
                f"unsupported cloud job state: {state or '<missing>'}",
                retryable=False,
            )

        operation = self.coordinator.store.get(operation_id)
        if operation is None:
            raise KeyError(operation_id)
        job_id = operation.server_job_ids.get("transcription")
        if not job_id:
            raise CloudAPIError(
                CloudErrorCode.SCHEMA_UNSUPPORTED,
                "succeeded job has no persisted transcription id",
                retryable=False,
            )
        result = self.client.get_transcription_result(
            job_id,
            expected_operation_id=operation_id,
        )
        result = self._with_local_source_metadata(operation_id, result)
        if summary_options is not None:
            result_artifact_id = str(
                job.get("result_artifact_id") or ""
            )
            if not result_artifact_id:
                raise CloudAPIError(
                    CloudErrorCode.SCHEMA_UNSUPPORTED,
                    "succeeded transcription has no result artifact id",
                    retryable=False,
                )
            self.coordinator.save_canonical_checkpoint(
                operation_id,
                result,
                stage=OperationStage.SUMMARIZE,
            )
            summary_job = self.client.create_summary(
                operation_id=operation_id,
                transcript_artifact_id=result_artifact_id,
                options=summary_options,
            )
            summary_id = self._required_remote_id(
                summary_job,
                resource="summary",
            )
            self._remember_remote_id(
                operation_id,
                key="summary",
                remote_id=summary_id,
                stage=OperationStage.SUMMARIZE,
            )
            return self._handle_summary_job(operation_id, summary_job)
        completed = self.coordinator.save_canonical_result(
            operation_id,
            result,
        )
        return completed

    def advance_transcription(
        self,
        operation_id: str,
        *,
        options: Mapping[str, Any],
        summary_options: Optional[Mapping[str, Any]] = None,
    ) -> OperationRecord:
        operation = self.coordinator.store.get(operation_id)
        if operation is None:
            raise KeyError(operation_id)
        if operation.status is OperationStatus.COMPLETED:
            return self.acknowledge_completed(operation_id)
        if operation.status in {
            OperationStatus.FAILED,
            OperationStatus.CANCELLED,
        }:
            return operation
        if operation.status is OperationStatus.CANCEL_REQUESTED:
            return self.cancel(operation_id)
        if operation.status in {
            OperationStatus.CREATED,
            OperationStatus.RETRYABLE,
        }:
            stage = (
                OperationStage.SUMMARIZE
                if operation.server_job_ids.get("summary")
                else (
                    OperationStage.TRANSCRIBE
                    if operation.server_job_ids.get("transcription")
                    else OperationStage.UPLOAD
                )
            )
            operation = self.coordinator.begin_attempt(
                operation_id,
                stage=stage,
            )

        try:
            summary_id = operation.server_job_ids.get("summary")
            if summary_id:
                summary_job = self.client.get_summary(summary_id)
                return self._handle_summary_job(
                    operation_id,
                    summary_job,
                )
            transcription_id = operation.server_job_ids.get(
                "transcription"
            )
            if transcription_id:
                job = self.client.get_transcription(transcription_id)
                return self._handle_job(
                    operation_id,
                    job,
                    summary_options=summary_options,
                )

            upload_id = operation.server_job_ids.get("upload")
            if not upload_id:
                upload = self.client.create_upload(
                    operation.source_asset_path,
                    operation_id=operation_id,
                )
                upload_id = self._required_remote_id(
                    upload,
                    resource="upload",
                )
                operation = self._remember_remote_id(
                    operation_id,
                    key="upload",
                    remote_id=upload_id,
                    stage=OperationStage.UPLOAD,
                )

            self.client.upload_file(
                operation.source_asset_path,
                operation_id=operation_id,
                remote_upload_id=upload_id,
            )
            job = self.client.create_transcription(
                upload_id=upload_id,
                operation_id=operation_id,
                options=options,
            )
            transcription_id = self._required_remote_id(
                job,
                resource="transcription",
            )
            self._remember_remote_id(
                operation_id,
                key="transcription",
                remote_id=transcription_id,
                stage=OperationStage.TRANSCRIBE,
            )
            return self._handle_job(
                operation_id,
                job,
                summary_options=summary_options,
            )
        except CloudAPIError as exc:
            current = self.coordinator.store.get(operation_id)
            if current is None:
                raise KeyError(operation_id) from exc
            if current.status is OperationStatus.COMPLETED:
                raise
            if exc.job_id:
                remote_key = (
                    "summary"
                    if current.stage is OperationStage.SUMMARIZE
                    else "transcription"
                )
                if remote_key not in current.server_job_ids:
                    current = self._remember_remote_id(
                        operation_id,
                        key=remote_key,
                        remote_id=exc.job_id,
                        stage=current.stage,
                    )
            if (
                exc.retryable
                or exc.code is CloudErrorCode.INSUFFICIENT_CREDITS
            ):
                return self._retryable(
                    operation_id,
                    code=exc.code.value,
                    retry_after_seconds=exc.retry_after_seconds,
                )
            return self.coordinator.store.transition(
                operation_id,
                OperationStatus.FAILED,
                last_error_code=exc.code.value,
            )
        except CanonicalResultError:
            return self.coordinator.store.transition(
                operation_id,
                OperationStatus.FAILED,
                last_error_code=CloudErrorCode.SCHEMA_UNSUPPORTED.value,
            )

    def advance_summary(
        self,
        operation_id: str,
        *,
        canonical_transcript: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> OperationRecord:
        """Advance a durable cloud summary for a locally produced transcript."""
        operation = self.coordinator.store.get(operation_id)
        if operation is None:
            raise KeyError(operation_id)
        if operation.status is OperationStatus.COMPLETED:
            return self.acknowledge_completed(operation_id)
        if operation.status in {
            OperationStatus.FAILED,
            OperationStatus.CANCELLED,
        }:
            return operation
        if operation.status is OperationStatus.CANCEL_REQUESTED:
            return self.cancel(operation_id)
        if operation.status in {
            OperationStatus.CREATED,
            OperationStatus.RETRYABLE,
        }:
            operation = self.coordinator.begin_attempt(
                operation_id,
                stage=OperationStage.SUMMARIZE,
            )
        elif operation.stage in {
            OperationStage.CAPTURE,
            OperationStage.PERSIST,
            OperationStage.UPLOAD,
            OperationStage.TRANSCRIBE,
            OperationStage.DIARIZE,
        }:
            operation = self.coordinator.store.transition(
                operation_id,
                OperationStatus.RUNNING,
                stage=OperationStage.SUMMARIZE,
            )

        try:
            summary_id = operation.server_job_ids.get("summary")
            if summary_id:
                return self._handle_summary_job(
                    operation_id,
                    self.client.get_summary(summary_id),
                )
            self.coordinator.save_canonical_checkpoint(
                operation_id,
                canonical_transcript,
                stage=OperationStage.SUMMARIZE,
            )
            summary_job = self.client.create_summary(
                operation_id=operation_id,
                canonical_transcript=canonical_transcript,
                options=options,
            )
            summary_id = self._required_remote_id(
                summary_job,
                resource="summary",
            )
            self._remember_remote_id(
                operation_id,
                key="summary",
                remote_id=summary_id,
                stage=OperationStage.SUMMARIZE,
            )
            return self._handle_summary_job(operation_id, summary_job)
        except CloudAPIError as exc:
            current = self.coordinator.store.get(operation_id)
            if current is None:
                raise KeyError(operation_id) from exc
            if current.status is OperationStatus.COMPLETED:
                raise
            if (
                exc.job_id
                and "summary" not in current.server_job_ids
            ):
                self._remember_remote_id(
                    operation_id,
                    key="summary",
                    remote_id=exc.job_id,
                    stage=OperationStage.SUMMARIZE,
                )
            if (
                exc.retryable
                or exc.code is CloudErrorCode.INSUFFICIENT_CREDITS
            ):
                return self._retryable(
                    operation_id,
                    code=exc.code.value,
                    retry_after_seconds=exc.retry_after_seconds,
                )
            return self.coordinator.store.transition(
                operation_id,
                OperationStatus.FAILED,
                last_error_code=exc.code.value,
            )
        except CanonicalResultError:
            return self.coordinator.store.transition(
                operation_id,
                OperationStatus.FAILED,
                last_error_code=CloudErrorCode.SCHEMA_UNSUPPORTED.value,
            )

    def acknowledge_completed(
        self,
        operation_id: str,
    ) -> OperationRecord:
        operation = self.coordinator.store.get(operation_id)
        if operation is None:
            raise KeyError(operation_id)
        if operation.status is not OperationStatus.COMPLETED:
            raise ValueError("only a completed operation can be acknowledged")
        job_id = operation.server_job_ids.get("transcription")
        summary_id = operation.server_job_ids.get("summary")
        if not job_id and not summary_id:
            raise ValueError("completed cloud operation has no server job id")
        if summary_id:
            self.client.acknowledge_summary(summary_id)
        if job_id:
            self.client.acknowledge_transcription(job_id)
        self.coordinator.acknowledge_result(operation_id)
        return self.coordinator.store.get(operation_id) or operation

    def cancel(self, operation_id: str) -> OperationRecord:
        operation = self.coordinator.store.get(operation_id)
        if operation is None:
            raise KeyError(operation_id)
        if operation.status in {
            OperationStatus.CANCELLED,
            OperationStatus.FAILED,
            OperationStatus.COMPLETED,
        }:
            return operation
        if operation.status is not OperationStatus.CANCEL_REQUESTED:
            operation = self.coordinator.request_cancel(operation_id)
        summary_id = operation.server_job_ids.get("summary")
        transcription_id = operation.server_job_ids.get("transcription")
        response: Mapping[str, Any]
        if summary_id:
            response = self.client.cancel_summary(summary_id)
        elif transcription_id:
            response = self.client.cancel_transcription(transcription_id)
        else:
            return self.coordinator.finish_cancel(operation_id)
        state = str(response.get("state") or "")
        if state == "cancelled":
            return self.coordinator.finish_cancel(operation_id)
        if state in {
            "awaiting_upload",
            "awaiting_funds",
            "queued",
            "running",
            "cancelling",
        }:
            return self.coordinator.store.get(operation_id) or operation
        if state in {"succeeded", "failed", "expired"}:
            return self.coordinator.store.transition(
                operation_id,
                OperationStatus.FAILED,
                last_error_code=f"REMOTE_{state.upper()}",
            )
        raise CloudAPIError(
            CloudErrorCode.SCHEMA_UNSUPPORTED,
            "cancellation response has no supported state",
            retryable=False,
        )


__all__ = [
    "CloudAPIError",
    "CloudErrorCode",
    "HTTPResponse",
    "MindTypeCloudClient",
    "MindTypeCloudExecutor",
    "ResponseTooLargeError",
    "TransportError",
    "UrlLibTransport",
]
