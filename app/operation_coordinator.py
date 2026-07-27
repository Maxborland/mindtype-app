"""Orchestrate durable desktop operation boundaries."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Optional

from .audio_mix import mix_tracks_to_wav
from .audio_sources import MultiTrackCapture, RecordedTrack
from .operation_models import (
    OperationKind,
    OperationRecord,
    OperationStage,
    OperationStatus,
    utc_now,
)
from .operation_store import OperationStore
from .result_schema import CanonicalResultError, write_canonical_result
from .spool import SpoolAsset, SpoolManager


class StaleOperationCallback(RuntimeError):
    """Raised when a terminal or cancelling operation receives late success."""


@dataclass(frozen=True)
class StartupRecovery:
    retryable_files: tuple[Any, ...]
    retryable_dictations: tuple[OperationRecord, ...]
    completed_pending_ack: tuple[OperationRecord, ...]


class OperationCoordinator:
    """Small composition layer for persistence-critical operation steps."""

    def __init__(self, *, store: OperationStore, spool: SpoolManager) -> None:
        self.store = store
        self.spool = spool

    def create_file_operation(
        self,
        source_path: Path,
        *,
        route: Mapping[str, Any],
        operation_id: Optional[str] = None,
    ) -> OperationRecord:
        identifier = operation_id or str(uuid.uuid4())
        asset = self.spool.import_source(identifier, source_path)
        return self._register_asset(
            identifier,
            kind=OperationKind.FILE,
            asset=asset,
            route=route,
            display_name=Path(source_path).name,
        )

    def _register_asset(
        self,
        operation_id: str,
        *,
        kind: OperationKind,
        asset: SpoolAsset,
        route: Mapping[str, Any],
        display_name: str,
        channels: Optional[list[dict[str, Any]]] = None,
    ) -> OperationRecord:
        deadline = utc_now() + timedelta(days=7)
        self.spool.write_operation_metadata(
            operation_id,
            retention_deadline=deadline,
            display_name=display_name,
            channels=channels,
        )
        created = self.store.create(
            operation_id=operation_id,
            kind=kind,
            source_asset_path=asset.path,
            source_sha256=asset.sha256,
            route=route,
            stage=OperationStage.PERSIST,
        )
        return self.store.transition(
            created.operation_id,
            OperationStatus.CREATED,
            retention_deadline=deadline,
        )

    def prepare_dictation(
        self,
        *,
        operation_id: Optional[str] = None,
    ) -> tuple[str, Path]:
        identifier = operation_id or str(uuid.uuid4())
        return identifier, self.spool.prepare_recording(identifier)

    def finalize_dictation(
        self,
        operation_id: str,
        *,
        route: Mapping[str, Any],
    ) -> OperationRecord:
        asset = self.spool.finalize_recording(operation_id)
        return self._register_asset(
            operation_id,
            kind=OperationKind.DICTATION,
            asset=asset,
            route=route,
            display_name="dictation.wav",
        )

    def adopt_recorded_dictation(
        self,
        recorder_path: Path,
        *,
        route: Mapping[str, Any],
        operation_id: Optional[str] = None,
    ) -> OperationRecord:
        """Copy/link a closed recorder WAV into the spool, then retire the temp."""
        identifier = operation_id or str(uuid.uuid4())
        source = Path(recorder_path)
        asset = self.spool.import_source(identifier, source)
        operation = self._register_asset(
            identifier,
            kind=OperationKind.DICTATION,
            asset=asset,
            route=route,
            display_name=source.name,
        )
        source.unlink(missing_ok=True)
        return operation

    def adopt_multitrack_dictation(
        self,
        capture: MultiTrackCapture,
        *,
        route: Mapping[str, Any],
        operation_id: Optional[str] = None,
    ) -> OperationRecord:
        """Durably adopt original tracks and a provider-compatible PCM projection."""
        identifier = operation_id or str(uuid.uuid4())
        source_tracks = [result.track for result in capture.results if result.track]
        if not source_tracks:
            raise ValueError("capture has no preserved audio track")
        kinds = [track.source for track in source_tracks]
        if len(set(kinds)) != len(kinds):
            raise ValueError("capture contains duplicate audio source tracks")
        if self.store.get(identifier) is not None:
            raise ValueError("operation_id already exists")

        durable_tracks: list[RecordedTrack] = []
        channels: list[dict[str, Any]] = []
        try:
            for track in source_tracks:
                asset = self.spool.import_track(
                    identifier,
                    track.path,
                    source=track.source,
                )
                durable = RecordedTrack(
                    source=track.source,
                    path=asset.path,
                    sample_rate=track.sample_rate,
                    channels=track.channels,
                    started_at_monotonic_ns=track.started_at_monotonic_ns,
                    ended_at_monotonic_ns=track.ended_at_monotonic_ns,
                )
                durable_tracks.append(durable)
                channels.append(
                    durable.canonical_channel(sha256=asset.sha256)
                )

            if len(durable_tracks) == 1:
                source_asset = self.spool.import_source(
                    identifier,
                    durable_tracks[0].path,
                )
            else:
                projection_path = self.spool.prepare_recording(identifier)
                mix_tracks_to_wav(durable_tracks, projection_path)
                source_asset = self.spool.finalize_recording(identifier)

            operation = self._register_asset(
                identifier,
                kind=OperationKind.DICTATION,
                asset=source_asset,
                route=route,
                display_name="dictation.wav",
                channels=channels,
            )
        except Exception:
            self.spool.delete_source(identifier)
            self.spool.delete_partial_outputs(identifier)
            raise
        for track in source_tracks:
            track.path.unlink(missing_ok=True)

        if capture.interrupted:
            errors = "; ".join(
                result.error
                for result in capture.results
                if result.error is not None
            )
            operation = self.store.transition(
                operation.operation_id,
                OperationStatus.RETRYABLE,
                stage=OperationStage.PERSIST,
                last_error_code=errors or "AUDIO_CAPTURE_INTERRUPTED",
            )
        return operation

    def begin_attempt(
        self,
        operation_id: str,
        *,
        stage: OperationStage,
    ) -> OperationRecord:
        return self.store.transition(
            operation_id,
            OperationStatus.RUNNING,
            stage=stage,
            new_attempt=True,
        )

    def prepare_file_task(
        self,
        task: Any,
        *,
        route: Mapping[str, Any],
    ) -> OperationRecord:
        """Spool or upgrade a file task, record its route, then start an attempt."""
        operation = self.store.get(task.operation_id)
        if operation is None:
            operation = self.create_file_operation(
                task.file_path,
                route=route,
                operation_id=task.operation_id,
            )
        elif operation.retention_deadline is None:
            operation = self.store.transition(
                operation.operation_id,
                operation.status,
                retention_deadline=utc_now() + timedelta(days=7),
            )
        if operation.source_sha256 is None:
            source = task.processing_path
            asset = self.spool.import_source(operation.operation_id, source)
            self.spool.write_operation_metadata(
                operation.operation_id,
                retention_deadline=operation.retention_deadline,
                display_name=task.file_name,
            )
            operation = self.store.update_source_asset(
                operation.operation_id,
                source_asset_path=asset.path,
                source_sha256=asset.sha256,
            )
        if operation.route != route:
            operation = self.store.update_route(operation.operation_id, route)

        task.source_asset_path = operation.source_asset_path
        self.spool.write_operation_metadata(
            operation.operation_id,
            retention_deadline=operation.retention_deadline,
            display_name=task.file_name,
        )
        metadata = self.spool.read_operation_metadata(operation.operation_id)
        if not task.display_name:
            task.display_name = str(
                metadata.get("display_name") or task.file_path.name
            )
        return self.begin_attempt(
            operation.operation_id,
            stage=OperationStage.TRANSCRIBE,
        )

    def save_canonical_result(
        self,
        operation_id: str,
        payload: Mapping[str, Any],
    ) -> OperationRecord:
        operation = self.store.get(operation_id)
        if operation is None:
            raise KeyError(operation_id)
        if operation.status in {
            OperationStatus.CANCEL_REQUESTED,
            OperationStatus.CANCELLED,
            OperationStatus.FAILED,
        }:
            raise StaleOperationCallback(
                "late result ignored for cancelling or terminal operation"
            )
        if operation.status is OperationStatus.COMPLETED:
            return operation
        result_source = payload.get("source")
        result_sha256 = (
            result_source.get("sha256")
            if isinstance(result_source, Mapping)
            else None
        )
        if (
            operation.source_sha256 is not None
            and result_sha256 != operation.source_sha256
        ):
            raise CanonicalResultError(
                "canonical result belongs to a different source asset"
            )
        result_path = self.spool.operation_dir(operation_id) / "result.json"
        write_canonical_result(
            result_path,
            payload,
            expected_operation_id=operation_id,
        )
        completed = self.store.transition(
            operation_id,
            OperationStatus.COMPLETED,
            stage=OperationStage.EXPORT,
            canonical_result_path=result_path,
            progress=100,
            retention_deadline=None,
        )
        self.spool.write_operation_metadata(
            operation_id,
            retention_deadline=None,
        )
        return completed

    def save_canonical_checkpoint(
        self,
        operation_id: str,
        payload: Mapping[str, Any],
        *,
        stage: OperationStage,
        name: str = "transcript",
    ) -> Path:
        """Atomically preserve a validated intermediate result without completing."""
        operation = self.store.get(operation_id)
        if operation is None:
            raise KeyError(operation_id)
        if operation.status is not OperationStatus.RUNNING:
            raise StaleOperationCallback(
                "checkpoint ignored for non-running operation"
            )
        result_source = payload.get("source")
        result_sha256 = (
            result_source.get("sha256")
            if isinstance(result_source, Mapping)
            else None
        )
        if (
            operation.source_sha256 is not None
            and result_sha256 != operation.source_sha256
        ):
            raise CanonicalResultError(
                "canonical checkpoint belongs to a different source asset"
            )
        checkpoint_dir = (
            self.spool.operation_dir(operation_id) / "checkpoints"
        )
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        checkpoint_path = checkpoint_dir / f"{name}.json"
        write_canonical_result(
            checkpoint_path,
            payload,
            expected_operation_id=operation_id,
        )
        self.store.transition(
            operation_id,
            OperationStatus.RUNNING,
            stage=stage,
        )
        return checkpoint_path

    def complete_dictation(
        self,
        operation_id: str,
        *,
        text: str,
        language: str,
        confidence: float,
        duration_ms: int,
    ) -> OperationRecord:
        operation = self.store.get(operation_id)
        if operation is None:
            raise KeyError(operation_id)
        payload = {
            "schema_version": "1.0",
            "operation_id": operation_id,
            "source": {
                "display_name": "dictation.wav",
                "duration_ms": duration_ms,
                "sha256": operation.source_sha256,
                "channels": self.spool.read_operation_metadata(
                    operation_id
                ).get("channels", []),
            },
            "route": operation.route,
            "transcript": {
                "language": language or "und",
                "confidence": confidence,
                "segments": [
                    {
                        "segment_id": "segment-0001",
                        "start_ms": 0,
                        "end_ms": duration_ms,
                        "text": text,
                        "speaker_id": None,
                        "words": [],
                        "confidence": confidence,
                        "postprocessed": False,
                    }
                ],
            },
            "speakers": [],
            "summary": None,
            "warnings": [],
            "provenance": {
                "server_job_ids": list(operation.server_job_ids.values()),
                "created_at": utc_now().isoformat(),
            },
        }
        return self.save_canonical_result(operation_id, payload)

    @staticmethod
    def _canonical_words(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
        canonical: list[dict[str, Any]] = []
        for word in words:
            start_ms = word.get("start_ms")
            if start_ms is None:
                start_ms = round(float(word.get("start", 0.0)) * 1000)
            end_ms = word.get("end_ms")
            if end_ms is None:
                end = word.get("end")
                end_ms = (
                    round(float(end) * 1000)
                    if end is not None
                    else start_ms
                )
            item: dict[str, Any] = {
                "start_ms": int(start_ms),
                "end_ms": int(end_ms),
                "text": str(word.get("text", word.get("word", ""))),
            }
            if word.get("confidence") is not None:
                item["confidence"] = word["confidence"]
            canonical.append(item)
        return canonical

    def canonical_payload_for_file_task(
        self,
        task: Any,
    ) -> dict[str, Any]:
        """Project a local worker result into the canonical cloud-safe schema."""
        operation = self.store.get(task.operation_id)
        if operation is None:
            raise KeyError(task.operation_id)
        if operation.kind is not OperationKind.FILE:
            raise ValueError("operation is not a file operation")
        if task.result is None:
            raise ValueError("file task has no transcription result")

        result = task.result
        segments = []
        for index, segment in enumerate(result.segments, start=1):
            segments.append(
                {
                    "segment_id": f"segment-{index:04d}",
                    "start_ms": round(float(segment.start) * 1000),
                    "end_ms": round(float(segment.end) * 1000),
                    "text": segment.text,
                    "speaker_id": segment.speaker,
                    "words": self._canonical_words(segment.words),
                    "confidence": None,
                    "postprocessed": False,
                }
            )
        segment_ids = [segment["segment_id"] for segment in segments]
        speakers = []
        for stats in result.speaker_stats or []:
            speakers.append(
                {
                    "speaker_id": stats.speaker_id,
                    "display_name": stats.speaker_name,
                    "total_duration_ms": round(stats.total_duration * 1000),
                    "segment_count": stats.segment_count,
                    "word_count": stats.word_count,
                }
            )

        summary = None
        if result.summary is not None:
            summary = {
                "text": result.summary,
                "preset": result.summary_preset_name or "generic",
                "generated": True,
                "source_segment_ids": segment_ids,
            }
        warnings = [task.warning] if task.warning else []
        payload = {
            "schema_version": "1.0",
            "operation_id": operation.operation_id,
            "source": {
                "display_name": task.file_name,
                "duration_ms": round(float(result.duration) * 1000),
                "sha256": operation.source_sha256,
                "channels": [],
            },
            "route": operation.route,
            "transcript": {
                "language": result.detected_language or "und",
                "confidence": max(
                    0.0,
                    min(1.0, float(result.language_probability)),
                ),
                "segments": segments,
                "processed_text": result.processed_text,
            },
            "speakers": speakers,
            "summary": summary,
            "warnings": warnings,
            "provenance": {
                "server_job_ids": list(operation.server_job_ids.values()),
                "created_at": utc_now().isoformat(),
            },
        }
        return payload

    def complete_file_task(self, task: Any) -> OperationRecord:
        """Persist the worker result as canonical JSON before publishing success."""
        payload = self.canonical_payload_for_file_task(task)
        return self.save_canonical_result(task.operation_id, payload)

    def restore_startup(self) -> StartupRecovery:
        """Recover durable work without starting processing or spending money."""
        from .transcription_models import FileStatus, FileTask

        running_before_recovery = self.store.list_running()
        self.store.recover_incomplete()
        for previous in running_before_recovery:
            recovered = self.store.get(previous.operation_id)
            if (
                recovered is not None
                and recovered.status is OperationStatus.COMPLETED
            ):
                self.spool.write_operation_metadata(
                    recovered.operation_id,
                    retention_deadline=None,
                )
        self.cleanup_expired(now=utc_now())
        retryable_files = []
        retryable_dictations = []
        for operation in self.store.list_retryable():
            if operation.kind is OperationKind.DICTATION:
                retryable_dictations.append(operation)
                continue
            metadata = self.spool.read_operation_metadata(operation.operation_id)
            display_name = metadata.get("display_name")
            retryable_files.append(
                FileTask(
                    file_path=operation.source_asset_path,
                    source_asset_path=operation.source_asset_path,
                    display_name=(
                        str(display_name)
                        if display_name
                        else operation.source_asset_path.name
                    ),
                    status=FileStatus.PENDING,
                    operation_id=operation.operation_id,
                )
            )
        completed_pending_ack = tuple(
            operation
            for operation in self.store.list_completed()
            if operation.source_asset_path.is_file()
            and operation.canonical_result_path is not None
            and operation.canonical_result_path.is_file()
        )
        return StartupRecovery(
            retryable_files=tuple(retryable_files),
            retryable_dictations=tuple(retryable_dictations),
            completed_pending_ack=completed_pending_ack,
        )

    def restore_retryable_file_tasks(self) -> list[Any]:
        """Compatibility wrapper for callers not yet consuming recovery details."""
        return list(self.restore_startup().retryable_files)

    def cleanup_expired(self, *, now: datetime) -> list[str]:
        removed = self.spool.cleanup_expired(now=now)
        for operation_id in removed:
            operation = self.store.get(operation_id)
            if operation is None or operation.status in {
                OperationStatus.COMPLETED,
                OperationStatus.FAILED,
                OperationStatus.CANCELLED,
            }:
                continue
            self.store.transition(
                operation_id,
                OperationStatus.FAILED,
                last_error_code="RETENTION_EXPIRED",
            )
        return removed

    def sync_file_task(
        self,
        task: Any,
        *,
        preserve_inflight: bool = False,
    ) -> OperationRecord:
        """Mirror one observable worker state into the durable lifecycle."""
        from .transcription_models import FileStatus

        operation = self.store.get(task.operation_id)
        if operation is None:
            raise KeyError(task.operation_id)

        stage_by_status = {
            FileStatus.EXTRACTING: OperationStage.TRANSCRIBE,
            FileStatus.TRANSCRIBING: OperationStage.TRANSCRIBE,
            FileStatus.PROCESSING: OperationStage.DIARIZE,
            FileStatus.SUMMARIZING: OperationStage.SUMMARIZE,
            FileStatus.GENERATING: OperationStage.EXPORT,
        }
        if task.status in stage_by_status:
            return self.store.transition(
                operation.operation_id,
                OperationStatus.RUNNING,
                stage=stage_by_status[task.status],
                progress=task.progress,
            )
        if task.status is FileStatus.COMPLETED:
            return self.complete_file_task(task)
        if task.status is FileStatus.ERROR:
            return self.mark_retryable(
                operation.operation_id,
                error_code="PROCESSING_FAILED",
            )
        if task.status is FileStatus.CANCELLED and not preserve_inflight:
            if operation.status in {
                OperationStatus.CREATED,
                OperationStatus.RUNNING,
                OperationStatus.RETRYABLE,
            }:
                operation = self.request_cancel(operation.operation_id)
            if operation.status is OperationStatus.CANCEL_REQUESTED:
                return self.finish_cancel(operation.operation_id)
        return operation

    def acknowledge_result(
        self,
        operation_id: str,
        *,
        preserve_source: bool = False,
    ) -> None:
        operation = self.store.get(operation_id)
        if operation is None:
            raise KeyError(operation_id)
        if operation.status is not OperationStatus.COMPLETED:
            raise ValueError("only a completed operation can be acknowledged")
        self.spool.write_operation_metadata(
            operation_id,
            retention_deadline=None,
        )
        if not preserve_source:
            self.spool.delete_source(operation_id)

    def request_cancel(self, operation_id: str) -> OperationRecord:
        return self.store.transition(
            operation_id,
            OperationStatus.CANCEL_REQUESTED,
        )

    def mark_retryable(
        self,
        operation_id: str,
        *,
        error_code: str,
    ) -> OperationRecord:
        return self.store.transition(
            operation_id,
            OperationStatus.RETRYABLE,
            last_error_code=error_code,
        )

    def finish_cancel(self, operation_id: str) -> OperationRecord:
        cancelled = self.store.transition(
            operation_id,
            OperationStatus.CANCELLED,
        )
        self.spool.delete_partial_outputs(operation_id)
        return cancelled
