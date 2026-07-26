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
from .spool import SpoolManager


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
        deadline = utc_now() + timedelta(days=7)
        self.spool.write_operation_metadata(
            identifier,
            retention_deadline=deadline,
        )
        created = self.store.create(
            operation_id=identifier,
            kind=OperationKind.FILE,
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
        deadline = utc_now() + timedelta(days=7)
        self.spool.write_operation_metadata(
            operation_id,
            retention_deadline=deadline,
        )
        created = self.store.create(
            operation_id=operation_id,
            kind=OperationKind.DICTATION,
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

    def finish_cancel(self, operation_id: str) -> OperationRecord:
        cancelled = self.store.transition(
            operation_id,
            OperationStatus.CANCELLED,
        )
        self.spool.delete_partial_outputs(operation_id)
        return cancelled
