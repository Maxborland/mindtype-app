"""SQLite repository for provider-neutral desktop operations."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from .operation_models import (
    InvalidOperationTransition,
    OperationKind,
    OperationRecord,
    OperationStage,
    OperationStatus,
    transition_operation,
    utc_now,
)


_SCHEMA_VERSION = 2
_UNSET = object()


class _ClosingConnection(sqlite3.Connection):
    """Make ``with connection`` close the Windows file handle as well."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class IncompleteOperationError(ValueError):
    """Raised when completion is attempted before durable result persistence."""


class OperationStore:
    """Persist operations with short transactions and per-call connections."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            timeout=5,
            factory=_ClosingConnection,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            legacy_migration = self._has_table(
                connection, "cloud_jobs"
            ) and not self._has_table(connection, "schema_meta")

        if legacy_migration:
            self._backup_legacy_database()

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS operations (
                    operation_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    source_asset_path TEXT NOT NULL,
                    source_sha256 TEXT,
                    route_json TEXT NOT NULL,
                    server_job_ids_json TEXT NOT NULL,
                    canonical_result_path TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    progress INTEGER NOT NULL DEFAULT 0,
                    last_error_code TEXT,
                    retry_after TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    retention_deadline TEXT
                )
                """
            )
            if legacy_migration:
                self._migrate_legacy_cloud_jobs(connection)
            connection.execute(
                """
                INSERT INTO schema_meta (key, value)
                VALUES ('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(_SCHEMA_VERSION),),
            )

    @staticmethod
    def _has_table(connection: sqlite3.Connection, table_name: str) -> bool:
        row = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = ?
            """,
            (table_name,),
        ).fetchone()
        return row is not None

    def _backup_legacy_database(self) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = self.database_path.with_name(
            f"{self.database_path.stem}.v1-backup-{timestamp}.sqlite3"
        )
        source = self._connect()
        destination = sqlite3.connect(backup_path)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        return backup_path

    @staticmethod
    def _legacy_stage(state: str) -> OperationStage:
        if state == "uploading":
            return OperationStage.UPLOAD
        if state == "completed":
            return OperationStage.EXPORT
        if state in {"processing", "failed", "cancelled"}:
            return OperationStage.TRANSCRIBE
        return OperationStage.PERSIST

    @staticmethod
    def _legacy_status(state: str) -> OperationStatus:
        if state in {"created", "uploading", "processing", "retryable"}:
            return OperationStatus.RETRYABLE
        return OperationStatus(state)

    def _migrate_legacy_cloud_jobs(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute("SELECT * FROM cloud_jobs").fetchall()
        for row in rows:
            remote_job_id = row["remote_job_id"]
            server_job_ids = {"legacy": remote_job_id} if remote_job_id else {}
            connection.execute(
                """
                INSERT OR IGNORE INTO operations (
                    operation_id, kind, status, stage, source_asset_path,
                    source_sha256, route_json, server_job_ids_json,
                    canonical_result_path, attempt_count, progress,
                    last_error_code, retry_after, created_at, updated_at,
                    completed_at, retention_deadline
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["idempotency_key"],
                    OperationKind.FILE.value,
                    self._legacy_status(row["state"]).value,
                    self._legacy_stage(row["state"]).value,
                    row["source_path"],
                    None,
                    row["route_json"],
                    json.dumps(server_job_ids, sort_keys=True),
                    None,
                    row["attempt_count"],
                    row["progress"],
                    row["last_error"],
                    None,
                    row["created_at"],
                    row["updated_at"],
                    row["completed_at"],
                    None,
                ),
            )

    @property
    def schema_version(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
        return int(row["value"])

    @staticmethod
    def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
        return datetime.fromisoformat(value) if value else None

    @classmethod
    def _from_row(cls, row: sqlite3.Row) -> OperationRecord:
        return OperationRecord(
            operation_id=row["operation_id"],
            kind=OperationKind(row["kind"]),
            status=OperationStatus(row["status"]),
            stage=OperationStage(row["stage"]),
            source_asset_path=Path(row["source_asset_path"]),
            source_sha256=row["source_sha256"],
            route=json.loads(row["route_json"]),
            server_job_ids=json.loads(row["server_job_ids_json"]),
            canonical_result_path=(
                Path(row["canonical_result_path"])
                if row["canonical_result_path"]
                else None
            ),
            attempt_count=row["attempt_count"],
            progress=row["progress"],
            last_error_code=row["last_error_code"],
            retry_after=cls._parse_datetime(row["retry_after"]),
            created_at=cls._parse_datetime(row["created_at"]),
            updated_at=cls._parse_datetime(row["updated_at"]),
            completed_at=cls._parse_datetime(row["completed_at"]),
            retention_deadline=cls._parse_datetime(row["retention_deadline"]),
        )

    def create(
        self,
        *,
        operation_id: str,
        kind: OperationKind,
        source_asset_path: Path,
        route: Mapping[str, Any],
        stage: OperationStage,
        source_sha256: Optional[str] = None,
    ) -> OperationRecord:
        now = utc_now().isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO operations (
                    operation_id, kind, status, stage, source_asset_path,
                    source_sha256, route_json, server_job_ids_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    operation_id,
                    kind.value,
                    OperationStatus.CREATED.value,
                    stage.value,
                    str(Path(source_asset_path).resolve()),
                    source_sha256,
                    json.dumps(dict(route), ensure_ascii=False, sort_keys=True),
                    "{}",
                    now,
                    now,
                ),
            )
        operation = self.get(operation_id)
        if operation is None:
            raise RuntimeError("operation was not persisted")
        return operation

    def get(self, operation_id: str) -> Optional[OperationRecord]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
        return self._from_row(row) if row else None

    def count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM operations"
            ).fetchone()
        return int(row["count"])

    def update_route(
        self,
        operation_id: str,
        route: Mapping[str, Any],
    ) -> OperationRecord:
        """Replace provenance only while work is idle and user-startable."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if row is None:
                raise KeyError(operation_id)
            current = self._from_row(row)
            if current.status not in {
                OperationStatus.CREATED,
                OperationStatus.RETRYABLE,
            }:
                raise InvalidOperationTransition(
                    "route can change only before a new attempt"
                )
            connection.execute(
                """
                UPDATE operations
                SET route_json = ?, updated_at = ?
                WHERE operation_id = ?
                """,
                (
                    json.dumps(
                        dict(route),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    utc_now().isoformat(),
                    operation_id,
                ),
            )
        updated = self.get(operation_id)
        if updated is None:
            raise RuntimeError("operation disappeared after route update")
        return updated

    def update_source_asset(
        self,
        operation_id: str,
        *,
        source_asset_path: Path,
        source_sha256: str,
    ) -> OperationRecord:
        """Attach a durable spool asset while an operation is idle."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if row is None:
                raise KeyError(operation_id)
            current = self._from_row(row)
            if current.status not in {
                OperationStatus.CREATED,
                OperationStatus.RETRYABLE,
            }:
                raise InvalidOperationTransition(
                    "source can change only before a new attempt"
                )
            connection.execute(
                """
                UPDATE operations
                SET source_asset_path = ?,
                    source_sha256 = ?,
                    updated_at = ?
                WHERE operation_id = ?
                """,
                (
                    str(Path(source_asset_path).resolve()),
                    source_sha256,
                    utc_now().isoformat(),
                    operation_id,
                ),
            )
        updated = self.get(operation_id)
        if updated is None:
            raise RuntimeError("operation disappeared after source update")
        return updated

    def recover_incomplete(self) -> list[OperationRecord]:
        """Make interrupted work explicit without starting network work."""
        now = utc_now()
        retention_deadline = now + timedelta(days=7)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT * FROM operations
                WHERE status IN (?, ?, ?)
                ORDER BY created_at
                """,
                (
                    OperationStatus.CREATED.value,
                    OperationStatus.RUNNING.value,
                    OperationStatus.CANCEL_REQUESTED.value,
                ),
            ).fetchall()
            for row in rows:
                current = self._from_row(row)
                result_path = current.source_asset_path.parent / "result.json"
                recovered_result = replace(
                    current,
                    canonical_result_path=result_path,
                )
                if current.status is OperationStatus.CANCEL_REQUESTED:
                    target_status = OperationStatus.CANCEL_REQUESTED
                    error_code = current.last_error_code
                    deadline = current.retention_deadline
                elif (
                    current.status is OperationStatus.RUNNING
                    and self._is_valid_completion_result(recovered_result)
                ):
                    target_status = OperationStatus.COMPLETED
                    error_code = None
                    deadline = None
                elif current.source_asset_path.is_file():
                    target_status = OperationStatus.RETRYABLE
                    error_code = current.last_error_code or "INTERRUPTED"
                    deadline = current.retention_deadline or retention_deadline
                else:
                    target_status = OperationStatus.FAILED
                    error_code = "SOURCE_MISSING"
                    deadline = current.retention_deadline

                terminal_at = (
                    now.isoformat()
                    if target_status
                    in {OperationStatus.FAILED, OperationStatus.CANCELLED}
                    else None
                )
                connection.execute(
                    """
                    UPDATE operations
                    SET status = ?,
                        last_error_code = ?,
                        updated_at = ?,
                        completed_at = ?,
                        retention_deadline = ?,
                        canonical_result_path = ?,
                        progress = ?
                    WHERE operation_id = ?
                    """,
                    (
                        target_status.value,
                        error_code,
                        now.isoformat(),
                        terminal_at,
                        deadline.isoformat() if deadline else None,
                        (
                            str(result_path.resolve())
                            if target_status is OperationStatus.COMPLETED
                            else (
                                str(current.canonical_result_path)
                                if current.canonical_result_path
                                else None
                            )
                        ),
                        (
                            100
                            if target_status is OperationStatus.COMPLETED
                            else current.progress
                        ),
                        current.operation_id,
                    ),
                )
        return self.list_retryable()

    def list_retryable(self) -> list[OperationRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM operations
                WHERE status = ?
                ORDER BY created_at
                """,
                (OperationStatus.RETRYABLE.value,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def list_cancel_requested(self) -> list[OperationRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM operations
                WHERE status = ?
                ORDER BY created_at
                """,
                (OperationStatus.CANCEL_REQUESTED.value,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def list_running(self) -> list[OperationRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM operations
                WHERE status = ?
                ORDER BY created_at
                """,
                (OperationStatus.RUNNING.value,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def list_completed(self) -> list[OperationRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM operations
                WHERE status = ?
                ORDER BY created_at
                """,
                (OperationStatus.COMPLETED.value,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def transition(
        self,
        operation_id: str,
        status: OperationStatus,
        *,
        stage: Optional[OperationStage] = None,
        new_attempt: bool = False,
        progress: Optional[int] = None,
        source_sha256: object = _UNSET,
        server_job_ids: Optional[Mapping[str, str]] = None,
        canonical_result_path: object = _UNSET,
        last_error_code: object = _UNSET,
        retry_after: object = _UNSET,
        retention_deadline: object = _UNSET,
    ) -> OperationRecord:
        if progress is not None and not 0 <= progress <= 100:
            raise ValueError("progress must be between 0 and 100")

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if row is None:
                raise KeyError(operation_id)

            current = self._from_row(row)
            updated_fields: dict[str, Any] = {}
            if progress is not None:
                updated_fields["progress"] = progress
            if source_sha256 is not _UNSET:
                updated_fields["source_sha256"] = source_sha256
            if server_job_ids is not None:
                updated_fields["server_job_ids"] = dict(server_job_ids)
            if canonical_result_path is not _UNSET:
                updated_fields["canonical_result_path"] = (
                    Path(canonical_result_path).resolve()
                    if canonical_result_path is not None
                    else None
                )
            if last_error_code is not _UNSET:
                updated_fields["last_error_code"] = last_error_code
            if retry_after is not _UNSET:
                updated_fields["retry_after"] = retry_after
            if retention_deadline is not _UNSET:
                updated_fields["retention_deadline"] = retention_deadline

            candidate = replace(current, **updated_fields)
            if status is OperationStatus.COMPLETED:
                self._validate_completion_result(candidate)
            transitioned = transition_operation(
                candidate,
                status=status,
                stage=stage,
                new_attempt=new_attempt,
            )
            connection.execute(
                """
                UPDATE operations
                SET status = ?,
                    stage = ?,
                    source_sha256 = ?,
                    server_job_ids_json = ?,
                    canonical_result_path = ?,
                    attempt_count = ?,
                    progress = ?,
                    last_error_code = ?,
                    retry_after = ?,
                    updated_at = ?,
                    completed_at = ?,
                    retention_deadline = ?
                WHERE operation_id = ?
                """,
                (
                    transitioned.status.value,
                    transitioned.stage.value,
                    transitioned.source_sha256,
                    json.dumps(
                        transitioned.server_job_ids,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    (
                        str(transitioned.canonical_result_path)
                        if transitioned.canonical_result_path
                        else None
                    ),
                    transitioned.attempt_count,
                    transitioned.progress,
                    transitioned.last_error_code,
                    (
                        transitioned.retry_after.isoformat()
                        if transitioned.retry_after
                        else None
                    ),
                    transitioned.updated_at.isoformat(),
                    (
                        transitioned.completed_at.isoformat()
                        if transitioned.completed_at
                        else None
                    ),
                    (
                        transitioned.retention_deadline.isoformat()
                        if transitioned.retention_deadline
                        else None
                    ),
                    operation_id,
                ),
            )
        persisted = self.get(operation_id)
        if persisted is None:
            raise RuntimeError("operation disappeared after transition")
        return persisted

    @staticmethod
    def _validate_completion_result(operation: OperationRecord) -> None:
        from .result_schema import CanonicalResultError, validate_canonical_result

        result_path = operation.canonical_result_path
        if result_path is None or not result_path.is_file():
            raise IncompleteOperationError(
                "completed operation requires a persisted canonical result"
            )
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            validate_canonical_result(
                payload,
                expected_operation_id=operation.operation_id,
            )
            source = payload.get("source")
            result_sha256 = (
                source.get("sha256")
                if isinstance(source, Mapping)
                else None
            )
            if (
                operation.source_sha256 is not None
                and result_sha256 != operation.source_sha256
            ):
                raise CanonicalResultError(
                    "canonical result belongs to a different source asset"
                )
        except (OSError, json.JSONDecodeError, CanonicalResultError) as exc:
            raise IncompleteOperationError(
                "canonical result is invalid or belongs to another operation"
            ) from exc

    @classmethod
    def _is_valid_completion_result(cls, operation: OperationRecord) -> bool:
        try:
            cls._validate_completion_result(operation)
        except IncompleteOperationError:
            return False
        return True

    def guarded_transition(
        self,
        *,
        callback_operation_id: str,
        active_operation_id: str,
        status: OperationStatus,
        stage: Optional[OperationStage] = None,
        **changes: Any,
    ) -> Optional[OperationRecord]:
        """Apply a callback only when it belongs to the active operation."""
        if callback_operation_id != active_operation_id:
            return None
        return self.transition(
            callback_operation_id,
            status,
            stage=stage,
            **changes,
        )
