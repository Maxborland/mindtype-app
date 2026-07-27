"""Provider-neutral operation lifecycle shared by dictation and file work."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional


class OperationKind(str, Enum):
    DICTATION = "dictation"
    FILE = "file"


class OperationStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    RETRYABLE = "retryable"
    CANCEL_REQUESTED = "cancel_requested"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OperationStage(str, Enum):
    CAPTURE = "capture"
    PERSIST = "persist"
    UPLOAD = "upload"
    TRANSCRIBE = "transcribe"
    DIARIZE = "diarize"
    SUMMARIZE = "summarize"
    EXPORT = "export"
    INSERT = "insert"


class InvalidOperationTransition(ValueError):
    """Raised when an operation violates lifecycle invariants."""


_TERMINAL_STATUSES = {
    OperationStatus.COMPLETED,
    OperationStatus.FAILED,
    OperationStatus.CANCELLED,
}

_ALLOWED_STATUS_TRANSITIONS = {
    OperationStatus.CREATED: {
        OperationStatus.CREATED,
        OperationStatus.RUNNING,
        OperationStatus.RETRYABLE,
        OperationStatus.CANCEL_REQUESTED,
        OperationStatus.FAILED,
    },
    OperationStatus.RUNNING: {
        OperationStatus.RUNNING,
        OperationStatus.RETRYABLE,
        OperationStatus.CANCEL_REQUESTED,
        OperationStatus.COMPLETED,
        OperationStatus.FAILED,
    },
    OperationStatus.RETRYABLE: {
        OperationStatus.RETRYABLE,
        OperationStatus.RUNNING,
        OperationStatus.CANCEL_REQUESTED,
        OperationStatus.FAILED,
    },
    OperationStatus.CANCEL_REQUESTED: {
        OperationStatus.CANCEL_REQUESTED,
        OperationStatus.CANCELLED,
        OperationStatus.FAILED,
    },
    OperationStatus.COMPLETED: set(),
    OperationStatus.FAILED: set(),
    OperationStatus.CANCELLED: set(),
}

_STAGE_ORDER = {stage: index for index, stage in enumerate(OperationStage)}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class OperationRecord:
    operation_id: str
    kind: OperationKind
    status: OperationStatus
    stage: OperationStage
    source_asset_path: Path
    source_sha256: Optional[str]
    route: dict[str, Any]
    server_job_ids: dict[str, str]
    canonical_result_path: Optional[Path]
    attempt_count: int
    progress: int
    last_error_code: Optional[str]
    retry_after: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]
    retention_deadline: Optional[datetime]

    @classmethod
    def new(
        cls,
        *,
        operation_id: str,
        kind: OperationKind,
        source_asset_path: Path,
        route: Mapping[str, Any],
        stage: OperationStage = OperationStage.PERSIST,
    ) -> "OperationRecord":
        now = utc_now()
        return cls(
            operation_id=operation_id,
            kind=kind,
            status=OperationStatus.CREATED,
            stage=stage,
            source_asset_path=Path(source_asset_path),
            source_sha256=None,
            route=dict(route),
            server_job_ids={},
            canonical_result_path=None,
            attempt_count=0,
            progress=0,
            last_error_code=None,
            retry_after=None,
            created_at=now,
            updated_at=now,
            completed_at=None,
            retention_deadline=None,
        )


def transition_operation(
    operation: OperationRecord,
    *,
    status: OperationStatus,
    stage: Optional[OperationStage] = None,
    new_attempt: bool = False,
    now: Optional[datetime] = None,
) -> OperationRecord:
    """Return a transitioned record after enforcing domain invariants."""
    if status not in _ALLOWED_STATUS_TRANSITIONS[operation.status]:
        raise InvalidOperationTransition(
            f"cannot transition operation from {operation.status.value} "
            f"to {status.value}"
        )

    target_stage = operation.stage if stage is None else stage
    if not new_attempt and _STAGE_ORDER[target_stage] < _STAGE_ORDER[operation.stage]:
        raise InvalidOperationTransition(
            f"cannot move stage backwards from {operation.stage.value} "
            f"to {target_stage.value}"
        )
    if new_attempt and status is not OperationStatus.RUNNING:
        raise InvalidOperationTransition("a new attempt must enter running state")

    timestamp = now or utc_now()
    terminal_at = timestamp if status in _TERMINAL_STATUSES else operation.completed_at
    return replace(
        operation,
        status=status,
        stage=target_stage,
        attempt_count=operation.attempt_count + (1 if new_attempt else 0),
        updated_at=timestamp,
        completed_at=terminal_at,
    )
