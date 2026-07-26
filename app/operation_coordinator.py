"""Orchestrate durable desktop operation boundaries."""

from __future__ import annotations

import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any, Mapping, Optional

from .operation_models import (
    OperationKind,
    OperationRecord,
    OperationStage,
    OperationStatus,
    utc_now,
)
from .operation_store import OperationStore
from .result_schema import write_canonical_result
from .spool import SpoolAsset, SpoolManager


class StaleOperationCallback(RuntimeError):
    """Raised when a terminal or cancelling operation receives late success."""


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
        )

    def _register_asset(
        self,
        operation_id: str,
        *,
        kind: OperationKind,
        asset: SpoolAsset,
        route: Mapping[str, Any],
    ) -> OperationRecord:
        deadline = utc_now() + timedelta(days=7)
        self.spool.write_operation_metadata(
            operation_id,
            retention_deadline=deadline,
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
        )
        source.unlink(missing_ok=True)
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
                "channels": [],
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
