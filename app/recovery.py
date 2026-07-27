"""Project durable canonical results back into user-visible desktop state."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from .exporters import CanonicalExporter, ExportFormat
from .operation_models import OperationKind, OperationRecord, OperationStatus
from .result_schema import validate_canonical_result
from .transcription_models import FileStatus, FileTask


@dataclass(frozen=True)
class RecoveredProjection:
    file_task: Optional[FileTask]
    dictation_text: Optional[str]
    file_duration_seconds: Optional[float] = None


def project_completed_operation(
    operation: OperationRecord,
    *,
    output_dir: Path,
    formats: Iterable[ExportFormat] = CanonicalExporter.formats,
) -> RecoveredProjection:
    if operation.status is not OperationStatus.COMPLETED:
        raise ValueError("only completed operations can be projected")
    if operation.canonical_result_path is None:
        raise ValueError("completed operation has no canonical result")
    payload = validate_canonical_result(
        json.loads(
            operation.canonical_result_path.read_text(encoding="utf-8")
        ),
        expected_operation_id=operation.operation_id,
    )

    if operation.kind is OperationKind.DICTATION:
        text = " ".join(
            str(segment["text"]).strip()
            for segment in payload["transcript"]["segments"]
            if str(segment["text"]).strip()
        )
        return RecoveredProjection(file_task=None, dictation_text=text)

    exported = CanonicalExporter().export_bundle(
        payload,
        output_dir,
        formats=formats,
        idempotency_key=operation.operation_id,
    )
    task = FileTask(
        file_path=operation.source_asset_path,
        source_asset_path=operation.source_asset_path,
        display_name=str(payload["source"]["display_name"]),
        status=FileStatus.COMPLETED,
        progress=100,
        operation_id=operation.operation_id,
        output_files={
            format_.value: path
            for format_, path in exported.items()
        },
    )
    return RecoveredProjection(
        file_task=task,
        dictation_text=None,
        file_duration_seconds=float(payload["source"]["duration_ms"]) / 1000,
    )
