"""Durable provider-neutral lifecycle for cloud-backed desktop operations."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional


class CloudJobState(str, Enum):
    CREATED = "created"
    UPLOADING = "uploading"
    PROCESSING = "processing"
    RETRYABLE = "retryable"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InvalidCloudJobTransition(ValueError):
    """Raised when a job attempts to leave its declared lifecycle."""


class CloudJobPayloadTooLarge(ValueError):
    """Raised when result metadata looks like content rather than metadata."""


class IdempotencyConflictError(ValueError):
    """Raised when one idempotency key describes two different operations."""


_MAX_RESULT_JSON_BYTES = 256 * 1024


_TERMINAL_STATES = {
    CloudJobState.COMPLETED,
    CloudJobState.FAILED,
    CloudJobState.CANCELLED,
}

_ALLOWED_TRANSITIONS = {
    CloudJobState.CREATED: {
        CloudJobState.CREATED,
        CloudJobState.UPLOADING,
        CloudJobState.PROCESSING,
        CloudJobState.RETRYABLE,
        CloudJobState.FAILED,
        CloudJobState.CANCELLED,
    },
    CloudJobState.UPLOADING: {
        CloudJobState.UPLOADING,
        CloudJobState.PROCESSING,
        CloudJobState.RETRYABLE,
        CloudJobState.FAILED,
        CloudJobState.CANCELLED,
    },
    CloudJobState.PROCESSING: {
        CloudJobState.PROCESSING,
        CloudJobState.RETRYABLE,
        CloudJobState.COMPLETED,
        CloudJobState.FAILED,
        CloudJobState.CANCELLED,
    },
    CloudJobState.RETRYABLE: {
        CloudJobState.RETRYABLE,
        CloudJobState.UPLOADING,
        CloudJobState.PROCESSING,
        CloudJobState.FAILED,
        CloudJobState.CANCELLED,
    },
    CloudJobState.COMPLETED: set(),
    CloudJobState.FAILED: set(),
    CloudJobState.CANCELLED: set(),
}


@dataclass(frozen=True)
class CloudJob:
    job_id: str
    idempotency_key: str
    source_path: Path
    operation: str
    route: dict[str, str]
    state: CloudJobState
    progress: int
    attempt_count: int
    remote_job_id: Optional[str]
    last_error: Optional[str]
    result: Optional[dict[str, Any]]
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]


class CloudJobStore:
    """SQLite job ledger using one short-lived connection per operation."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cloud_jobs (
                    job_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    source_path TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    route_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    remote_job_id TEXT,
                    last_error TEXT,
                    result_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                )
                """
            )

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
        return datetime.fromisoformat(value) if value else None

    @classmethod
    def _from_row(cls, row: sqlite3.Row) -> CloudJob:
        return CloudJob(
            job_id=row["job_id"],
            idempotency_key=row["idempotency_key"],
            source_path=Path(row["source_path"]),
            operation=row["operation"],
            route=json.loads(row["route_json"]),
            state=CloudJobState(row["state"]),
            progress=row["progress"],
            attempt_count=row["attempt_count"],
            remote_job_id=row["remote_job_id"],
            last_error=row["last_error"],
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            created_at=cls._parse_datetime(row["created_at"]),
            updated_at=cls._parse_datetime(row["updated_at"]),
            completed_at=cls._parse_datetime(row["completed_at"]),
        )

    def create_or_get(
        self,
        *,
        idempotency_key: str,
        source_path: Path,
        operation: str,
        route: Mapping[str, str],
    ) -> CloudJob:
        now = self._now().isoformat()
        source = str(Path(source_path).resolve())
        route_json = json.dumps(dict(route), ensure_ascii=False, sort_keys=True)
        job_id = str(uuid.uuid4())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO cloud_jobs (
                    job_id, idempotency_key, source_path, operation, route_json,
                    state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    idempotency_key,
                    source,
                    operation,
                    route_json,
                    CloudJobState.CREATED.value,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM cloud_jobs WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if (
                row["source_path"] != source
                or row["operation"] != operation
                or row["route_json"] != route_json
            ):
                raise IdempotencyConflictError(
                    "idempotency key is already bound to a different cloud job"
                )
        return self._from_row(row)

    def get(self, job_id: str) -> Optional[CloudJob]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM cloud_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return self._from_row(row) if row else None

    def begin_attempt(
        self,
        job_id: str,
        *,
        state: CloudJobState,
        remote_job_id: Optional[str] = None,
    ) -> CloudJob:
        if state not in {CloudJobState.UPLOADING, CloudJobState.PROCESSING}:
            raise ValueError("an attempt must begin in uploading or processing state")

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM cloud_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise KeyError(job_id)

            current = CloudJobState(row["state"])
            if state not in _ALLOWED_TRANSITIONS[current]:
                raise InvalidCloudJobTransition(
                    f"cannot transition cloud job from {current.value} to {state.value}"
                )

            connection.execute(
                """
                UPDATE cloud_jobs
                SET state = ?,
                    progress = 0,
                    attempt_count = attempt_count + 1,
                    remote_job_id = ?,
                    last_error = NULL,
                    updated_at = ?,
                    completed_at = NULL
                WHERE job_id = ?
                """,
                (
                    state.value,
                    row["remote_job_id"] if remote_job_id is None else remote_job_id,
                    self._now().isoformat(),
                    job_id,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM cloud_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return self._from_row(updated)

    def transition(
        self,
        job_id: str,
        state: CloudJobState,
        *,
        progress: Optional[int] = None,
        remote_job_id: Optional[str] = None,
        last_error: Optional[str] = None,
        result: Optional[Mapping[str, Any]] = None,
    ) -> CloudJob:
        if progress is not None and not 0 <= progress <= 100:
            raise ValueError("progress must be between 0 and 100")
        result_json = None
        if result is not None:
            result_json = json.dumps(
                dict(result),
                ensure_ascii=False,
                sort_keys=True,
            )
            if len(result_json.encode("utf-8")) > _MAX_RESULT_JSON_BYTES:
                raise CloudJobPayloadTooLarge(
                    "cloud job result metadata exceeds 256 KiB"
                )

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM cloud_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise KeyError(job_id)

            current = CloudJobState(row["state"])
            if state not in _ALLOWED_TRANSITIONS[current]:
                raise InvalidCloudJobTransition(
                    f"cannot transition cloud job from {current.value} to {state.value}"
                )

            now = self._now().isoformat()
            completed_at = now if state in _TERMINAL_STATES else row["completed_at"]
            connection.execute(
                """
                UPDATE cloud_jobs
                SET state = ?,
                    progress = ?,
                    remote_job_id = ?,
                    last_error = ?,
                    result_json = ?,
                    updated_at = ?,
                    completed_at = ?
                WHERE job_id = ?
                """,
                (
                    state.value,
                    row["progress"] if progress is None else progress,
                    row["remote_job_id"] if remote_job_id is None else remote_job_id,
                    row["last_error"] if last_error is None else last_error,
                    (
                        row["result_json"]
                        if result is None
                        else result_json
                    ),
                    now,
                    completed_at,
                    job_id,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM cloud_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return self._from_row(updated)

    def recover_incomplete(self) -> list[CloudJob]:
        """Convert interrupted local work into explicit user-retryable jobs."""
        inflight = (
            CloudJobState.CREATED.value,
            CloudJobState.UPLOADING.value,
            CloudJobState.PROCESSING.value,
        )
        now = self._now().isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT * FROM cloud_jobs
                WHERE state IN (?, ?, ?)
                ORDER BY created_at
                """,
                inflight,
            ).fetchall()
            retryable_ids: list[str] = []
            for row in rows:
                source_exists = Path(row["source_path"]).is_file()
                target_state = (
                    CloudJobState.RETRYABLE
                    if source_exists
                    else CloudJobState.FAILED
                )
                if source_exists:
                    retryable_ids.append(row["job_id"])
                connection.execute(
                    """
                    UPDATE cloud_jobs
                    SET state = ?,
                        last_error = ?,
                        updated_at = ?,
                        completed_at = ?
                    WHERE job_id = ?
                    """,
                    (
                        target_state.value,
                        (
                            row["last_error"]
                            if source_exists
                            else "Source file is missing; retry is impossible."
                        ),
                        now,
                        None if source_exists else now,
                        row["job_id"],
                    ),
                )
            if retryable_ids:
                placeholders = ",".join("?" for _ in retryable_ids)
                rows = connection.execute(
                    f"""
                    SELECT * FROM cloud_jobs
                    WHERE job_id IN ({placeholders})
                    ORDER BY created_at
                    """,
                    retryable_ids,
                ).fetchall()
            else:
                rows = []
        return [self._from_row(row) for row in rows]

    def list_retryable(self) -> list[CloudJob]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM cloud_jobs
                WHERE state = ?
                ORDER BY created_at
                """,
                (CloudJobState.RETRYABLE.value,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def count(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM cloud_jobs").fetchone()
        return int(row["count"])


class FileCloudJobTracker:
    """Bridge durable cloud jobs to the existing file-processing task model."""

    def __init__(self, store: CloudJobStore) -> None:
        self.store = store

    def register(
        self,
        task: Any,
        *,
        route: Mapping[str, str],
    ) -> CloudJob:
        job = self.store.create_or_get(
            idempotency_key=task.operation_id,
            source_path=getattr(task, "processing_path", task.file_path),
            operation="file_processing",
            route=route,
        )
        task.cloud_job_id = job.job_id
        return job

    def begin(self, task: Any) -> CloudJob:
        if not task.cloud_job_id:
            raise ValueError("file task is not registered as a cloud job")
        return self.store.begin_attempt(
            task.cloud_job_id,
            state=CloudJobState.PROCESSING,
        )

    def sync(self, task: Any) -> Optional[CloudJob]:
        from .transcription_models import FileStatus

        if not task.cloud_job_id:
            return None

        processing_states = {
            FileStatus.EXTRACTING,
            FileStatus.TRANSCRIBING,
            FileStatus.PROCESSING,
            FileStatus.SUMMARIZING,
            FileStatus.GENERATING,
        }
        if task.status in processing_states:
            return self.store.transition(
                task.cloud_job_id,
                CloudJobState.PROCESSING,
                progress=task.progress,
            )
        if task.status is FileStatus.COMPLETED:
            result_metadata: dict[str, Any] = {
                "outputs": {
                    name: str(path)
                    for name, path in task.output_files.items()
                },
                "warning": task.warning or None,
            }
            if task.result is not None:
                result_metadata["duration_seconds"] = task.result.duration
            return self.store.transition(
                task.cloud_job_id,
                CloudJobState.COMPLETED,
                progress=100,
                result=result_metadata,
            )
        if task.status is FileStatus.ERROR:
            return self.store.transition(
                task.cloud_job_id,
                CloudJobState.RETRYABLE,
                progress=task.progress,
                last_error=task.error_message or "Cloud processing failed.",
            )
        if task.status is FileStatus.CANCELLED:
            return self.store.transition(
                task.cloud_job_id,
                CloudJobState.CANCELLED,
                progress=task.progress,
            )
        return self.store.get(task.cloud_job_id)

    def restore_retryable_tasks(self) -> list[Any]:
        from .transcription_models import FileStatus, FileTask

        self.store.recover_incomplete()
        return [
            FileTask(
                file_path=job.source_path,
                status=FileStatus.PENDING,
                operation_id=job.idempotency_key,
                cloud_job_id=job.job_id,
            )
            for job in self.store.list_retryable()
        ]
