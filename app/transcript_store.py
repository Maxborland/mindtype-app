"""Durable transcript documents backed by SQLite."""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional, Tuple
from uuid import uuid4

from .transcription_models import (
    FileTask,
    TranscriptionResult,
    TranscriptionSegment,
)

logger = logging.getLogger("mindtype.transcript_store")


class TranscriptStoreError(RuntimeError):
    pass


class UnsupportedSchemaVersion(TranscriptStoreError):
    pass


class CorruptTranscriptData(TranscriptStoreError):
    pass


@dataclass(frozen=True)
class TranscriptRevision:
    id: str
    document_id: str
    number: int
    created_at: datetime
    segments: Tuple[TranscriptionSegment, ...]
    processed_text: Optional[str]
    speaker_names: dict[str, str]


@dataclass(frozen=True)
class SummaryVariant:
    id: str
    document_id: str
    revision_id: str
    template_id: str
    template_name: str
    template_version: int
    template_prompts: dict[str, str]
    content: str
    provider: str
    model: str
    metrics: Optional[dict]
    created_at: datetime


@dataclass(frozen=True)
class TranscriptDocument:
    id: str
    source_path: Path
    detected_language: Optional[str]
    language_probability: float
    duration: float
    model_used: str
    created_at: datetime
    updated_at: datetime
    revisions: Tuple[TranscriptRevision, ...]
    summary_variants: Tuple[SummaryVariant, ...]
    cloud_job_id: Optional[str] = None
    cloud_summary_job_id: Optional[str] = None
    cloud_cleanup_acknowledged: bool = False
    cloud_summary_cleanup_acknowledged: bool = False

    @property
    def current_revision(self) -> TranscriptRevision:
        return self.revisions[-1]


@dataclass(frozen=True)
class PendingCloudCleanup:
    document_id: str
    job_id: str
    kind: str


class TranscriptStore:
    """Small public interface around MindType's durable transcript library."""

    _SCHEMA_VERSION = 2

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def save_result(self, result: TranscriptionResult) -> TranscriptDocument:
        if not result.segments:
            raise ValueError("Нельзя сохранить расшифровку без сегментов")

        document_id = str(uuid4())
        revision_id = str(uuid4())
        created_at = result.transcription_date
        source_path = result.file_path.resolve()

        segments_json = json.dumps(
            [asdict(segment) for segment in result.segments],
            ensure_ascii=False,
        )
        speaker_names_json = json.dumps(result.speaker_names, ensure_ascii=False)

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO transcript_documents (
                    id, source_path, detected_language, language_probability,
                    duration, model_used, created_at, updated_at,
                    cloud_job_id, cloud_summary_job_id,
                    cloud_cleanup_acknowledged,
                    cloud_summary_cleanup_acknowledged
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    str(source_path),
                    result.detected_language,
                    result.language_probability,
                    result.duration,
                    result.model_used,
                    created_at.isoformat(),
                    created_at.isoformat(),
                    result.cloud_job_id,
                    result.cloud_summary_job_id,
                    int(result.cloud_cleanup_acknowledged),
                    int(result.cloud_summary_cleanup_acknowledged),
                ),
            )
            connection.execute(
                """
                INSERT INTO transcript_revisions (
                    id, document_id, revision_number, created_at, segments_json,
                    processed_text, speaker_names_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revision_id,
                    document_id,
                    1,
                    created_at.isoformat(),
                    segments_json,
                    result.processed_text,
                    speaker_names_json,
                ),
            )
            if result.has_summary:
                connection.execute(
                    """
                    INSERT INTO summary_variants (
                        id, document_id, revision_id, template_id, template_name,
                        template_version, template_prompts_json, content,
                        provider, model, metrics_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        document_id,
                        revision_id,
                        "legacy",
                        result.summary_preset_name or "Imported summary",
                        1,
                        "{}",
                        result.summary,
                        "legacy",
                        "",
                        (
                            json.dumps(result.summary_metrics, ensure_ascii=False)
                            if result.summary_metrics is not None
                            else None
                        ),
                        created_at.isoformat(),
                    ),
                )

        document = self.get_document(document_id)
        if document is None:  # pragma: no cover - guarded by the transaction above
            raise RuntimeError("Сохранённая расшифровка не найдена")
        return document

    def rename_speakers(
        self,
        document_id: str,
        names: dict[str, str],
    ) -> TranscriptDocument:
        normalized_names = {
            speaker_id: name.strip()
            for speaker_id, name in names.items()
        }
        if any(not name for name in normalized_names.values()):
            raise ValueError("Имя собеседника не может быть пустым")

        revision_id = str(uuid4())
        updated_at = datetime.now()

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                """
                SELECT revision_number, segments_json, processed_text,
                       speaker_names_json
                FROM transcript_revisions
                WHERE document_id = ?
                ORDER BY revision_number DESC
                LIMIT 1
                """,
                (document_id,),
            ).fetchone()
            if current is None:
                raise KeyError(f"Расшифровка {document_id} не найдена")

            speaker_names = json.loads(current["speaker_names_json"])
            speaker_names.update(normalized_names)
            connection.execute(
                """
                INSERT INTO transcript_revisions (
                    id, document_id, revision_number, created_at, segments_json,
                    processed_text, speaker_names_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revision_id,
                    document_id,
                    current["revision_number"] + 1,
                    updated_at.isoformat(),
                    current["segments_json"],
                    current["processed_text"],
                    json.dumps(speaker_names, ensure_ascii=False),
                ),
            )
            connection.execute(
                """
                UPDATE transcript_documents
                SET updated_at = ?
                WHERE id = ?
                """,
                (updated_at.isoformat(), document_id),
            )

        document = self.get_document(document_id)
        if document is None:  # pragma: no cover - guarded by the transaction above
            raise RuntimeError("Обновлённая расшифровка не найдена")
        return document

    def add_summary_variant(
        self,
        *,
        document_id: str,
        revision_id: str,
        template_id: str,
        template_name: str,
        template_version: int,
        template_prompts: dict[str, str],
        content: str,
        provider: str,
        model: str,
        metrics: Optional[dict] = None,
    ) -> SummaryVariant:
        if not content.strip():
            raise ValueError("Саммари не может быть пустым")

        variant_id = str(uuid4())
        created_at = datetime.now()
        with self._connect() as connection:
            revision = connection.execute(
                """
                SELECT 1
                FROM transcript_revisions
                WHERE id = ? AND document_id = ?
                """,
                (revision_id, document_id),
            ).fetchone()
            if revision is None:
                raise KeyError("Версия расшифровки не найдена")

            connection.execute(
                """
                INSERT INTO summary_variants (
                    id, document_id, revision_id, template_id, template_name,
                    template_version, template_prompts_json, content, provider,
                    model, metrics_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    variant_id,
                    document_id,
                    revision_id,
                    template_id,
                    template_name,
                    template_version,
                    json.dumps(template_prompts, ensure_ascii=False),
                    content,
                    provider,
                    model,
                    json.dumps(metrics, ensure_ascii=False) if metrics is not None else None,
                    created_at.isoformat(),
                ),
            )
            connection.execute(
                """
                UPDATE transcript_documents
                SET updated_at = ?
                WHERE id = ?
                """,
                (created_at.isoformat(), document_id),
            )

        document = self.get_document(document_id)
        if document is None:  # pragma: no cover - guarded by the transaction above
            raise RuntimeError("Расшифровка для саммари не найдена")
        return next(
            variant
            for variant in document.summary_variants
            if variant.id == variant_id
        )


    def list_documents(self) -> Tuple[TranscriptDocument, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id
                FROM transcript_documents
                ORDER BY created_at DESC, id DESC
                """
            ).fetchall()

        documents = (
            self.get_document(row["id"])
            for row in rows
        )
        return tuple(document for document in documents if document is not None)
    def register_cloud_summary_job(self, document_id: str, job_id: str) -> None:
        """Persist a summary job before attempting remote cleanup."""
        normalized_job_id = str(job_id).strip()
        if not normalized_job_id:
            raise ValueError("Cloud summary job id cannot be empty")
        with self._connect() as connection:
            updated = connection.execute(
                """
                UPDATE transcript_documents
                SET cloud_summary_job_id = ?,
                    cloud_summary_cleanup_acknowledged = 0,
                    updated_at = ?
                WHERE id = ?
                """,
                (normalized_job_id, datetime.now().isoformat(), document_id),
            )
            if updated.rowcount != 1:
                raise KeyError(f"Расшифровка {document_id} не найдена")

    def mark_cloud_cleanup_acknowledged(
        self,
        document_id: str,
        job_id: str,
        kind: str,
    ) -> bool:
        """Mark one remote artifact as acknowledged after a successful ACK."""
        columns = {
            "transcription": ("cloud_job_id", "cloud_cleanup_acknowledged"),
            "summary": ("cloud_summary_job_id", "cloud_summary_cleanup_acknowledged"),
        }
        job_column, acknowledged_column = columns.get(kind, (None, None))
        if job_column is None or acknowledged_column is None:
            raise ValueError(f"Unknown Cloud cleanup kind: {kind}")
        with self._connect() as connection:
            updated = connection.execute(
                f"""
                UPDATE transcript_documents
                SET {acknowledged_column} = 1,
                    updated_at = ?
                WHERE id = ? AND {job_column} = ?
                """,
                (datetime.now().isoformat(), document_id, str(job_id)),
            )
        return updated.rowcount == 1

    def list_pending_cloud_cleanups(self) -> Tuple[PendingCloudCleanup, ...]:
        """Return Cloud jobs whose local cleanup ACK is still pending."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, cloud_job_id, cloud_summary_job_id,
                       cloud_cleanup_acknowledged,
                       cloud_summary_cleanup_acknowledged
                FROM transcript_documents
                WHERE (cloud_job_id IS NOT NULL AND cloud_cleanup_acknowledged = 0)
                   OR (cloud_summary_job_id IS NOT NULL
                       AND cloud_summary_cleanup_acknowledged = 0)
                ORDER BY updated_at, id
                """
            ).fetchall()
        pending = []
        for row in rows:
            if row["cloud_job_id"] and not row["cloud_cleanup_acknowledged"]:
                pending.append(
                    PendingCloudCleanup(
                        document_id=row["id"],
                        job_id=row["cloud_job_id"],
                        kind="transcription",
                    )
                )
            if row["cloud_summary_job_id"] and not row["cloud_summary_cleanup_acknowledged"]:
                pending.append(
                    PendingCloudCleanup(
                        document_id=row["id"],
                        job_id=row["cloud_summary_job_id"],
                        kind="summary",
                    )
                )
        return tuple(pending)

    def get_document(self, document_id: str) -> Optional[TranscriptDocument]:
        with self._connect() as connection:
            document_row = connection.execute(
                """
                SELECT id, source_path, detected_language, language_probability,
                       duration, model_used, created_at, updated_at,
                       cloud_job_id, cloud_summary_job_id,
                       cloud_cleanup_acknowledged,
                       cloud_summary_cleanup_acknowledged
                FROM transcript_documents
                WHERE id = ?
                """,
                (document_id,),
            ).fetchone()
            if document_row is None:
                return None

            revision_rows = connection.execute(
                """
                SELECT id, document_id, revision_number, created_at,
                       segments_json, processed_text, speaker_names_json
                FROM transcript_revisions
                WHERE document_id = ?
                ORDER BY revision_number
                """,
                (document_id,),
            ).fetchall()

            variant_rows = connection.execute(
                """
                SELECT id, document_id, revision_id, template_id, template_name,
                       template_version, template_prompts_json, content,
                       provider, model, metrics_json, created_at
                FROM summary_variants
                WHERE document_id = ?
                ORDER BY created_at, rowid
                """,
                (document_id,),
            ).fetchall()

        revisions = tuple(self._revision_from_row(row) for row in revision_rows)
        variants = tuple(
            self._summary_variant_from_row(row)
            for row in variant_rows
        )
        return TranscriptDocument(
            id=document_row["id"],
            source_path=Path(document_row["source_path"]),
            detected_language=document_row["detected_language"],
            language_probability=document_row["language_probability"],
            duration=document_row["duration"],
            model_used=document_row["model_used"],
            created_at=datetime.fromisoformat(document_row["created_at"]),
            updated_at=datetime.fromisoformat(document_row["updated_at"]),
            revisions=revisions,
            summary_variants=variants,
            cloud_job_id=document_row["cloud_job_id"],
            cloud_summary_job_id=document_row["cloud_summary_job_id"],
            cloud_cleanup_acknowledged=bool(document_row["cloud_cleanup_acknowledged"]),
            cloud_summary_cleanup_acknowledged=bool(
                document_row["cloud_summary_cleanup_acknowledged"]
            ),
        )

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_info (
                    version INTEGER NOT NULL
                )
                """
            )
            version = connection.execute(
                "SELECT version FROM schema_info LIMIT 1"
            ).fetchone()
            if version is None:
                connection.execute(
                    "INSERT INTO schema_info (version) VALUES (?)",
                    (self._SCHEMA_VERSION,),
                )
            elif version["version"] == 1:
                connection.execute(
                    "ALTER TABLE transcript_documents ADD COLUMN cloud_job_id TEXT"
                )
                connection.execute(
                    "ALTER TABLE transcript_documents ADD COLUMN cloud_summary_job_id TEXT"
                )
                connection.execute(
                    "ALTER TABLE transcript_documents ADD COLUMN cloud_cleanup_acknowledged INTEGER NOT NULL DEFAULT 0"
                )
                connection.execute(
                    "ALTER TABLE transcript_documents ADD COLUMN cloud_summary_cleanup_acknowledged INTEGER NOT NULL DEFAULT 0"
                )
                connection.execute(
                    "UPDATE schema_info SET version = ?",
                    (self._SCHEMA_VERSION,),
                )
            elif version["version"] != self._SCHEMA_VERSION:
                raise UnsupportedSchemaVersion(
                    f"Неподдерживаемая версия схемы: {version['version']}"
                )

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS transcript_documents (
                    id TEXT PRIMARY KEY,
                    source_path TEXT NOT NULL,
                    detected_language TEXT,
                    language_probability REAL NOT NULL,
                    duration REAL NOT NULL,
                    model_used TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    cloud_job_id TEXT,
                    cloud_summary_job_id TEXT,
                    cloud_cleanup_acknowledged INTEGER NOT NULL DEFAULT 0,
                    cloud_summary_cleanup_acknowledged INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS transcript_revisions (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL
                        REFERENCES transcript_documents(id) ON DELETE CASCADE,
                    revision_number INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    segments_json TEXT NOT NULL,
                    processed_text TEXT,
                    speaker_names_json TEXT NOT NULL,
                    UNIQUE(document_id, revision_number)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS summary_variants (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL
                        REFERENCES transcript_documents(id) ON DELETE CASCADE,
                    revision_id TEXT NOT NULL
                        REFERENCES transcript_revisions(id) ON DELETE CASCADE,
                    template_id TEXT NOT NULL,
                    template_name TEXT NOT NULL,
                    template_version INTEGER NOT NULL,
                    template_prompts_json TEXT NOT NULL,
                    content TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    metrics_json TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _revision_from_row(row: sqlite3.Row) -> TranscriptRevision:
        try:
            segments_data = json.loads(row["segments_json"])
            speaker_names = json.loads(row["speaker_names_json"])
        except (json.JSONDecodeError, TypeError) as error:
            raise CorruptTranscriptData(
                f"Повреждены данные расшифровки {row['document_id']}"
            ) from error

        segments = tuple(
            TranscriptionSegment(
                start=segment["start"],
                end=segment["end"],
                text=segment["text"],
                speaker=segment.get("speaker"),
                words=segment.get("words", []),
            )
            for segment in segments_data
        )
        return TranscriptRevision(
            id=row["id"],
            document_id=row["document_id"],
            number=row["revision_number"],
            created_at=datetime.fromisoformat(row["created_at"]),
            segments=segments,
            processed_text=row["processed_text"],
            speaker_names=speaker_names,
        )

    @staticmethod
    def _summary_variant_from_row(row: sqlite3.Row) -> SummaryVariant:
        metrics_json = row["metrics_json"]
        return SummaryVariant(
            id=row["id"],
            document_id=row["document_id"],
            revision_id=row["revision_id"],
            template_id=row["template_id"],
            template_name=row["template_name"],
            template_version=row["template_version"],
            template_prompts=json.loads(row["template_prompts_json"]),
            content=row["content"],
            provider=row["provider"],
            model=row["model"],
            metrics=json.loads(metrics_json) if metrics_json is not None else None,
            created_at=datetime.fromisoformat(row["created_at"]),
        )


def persist_completed_task(
    store: TranscriptStore,
    task: FileTask,
) -> Optional[TranscriptDocument]:
    # A transcript result remains valid when a downstream summary or report
    # stage failed. Persist any task that reached a durable result object.
    if task.result is None:
        return None
    try:
        document = store.save_result(task.result)
    except Exception as error:
        logger.exception("Не удалось сохранить расшифровку в библиотеку")
        warning = f"Не удалось сохранить расшифровку в библиотеку: {error}"
        task.warning = "\n".join(part for part in (task.warning, warning) if part)
        return None

    task.library_document_id = document.id
    return document
