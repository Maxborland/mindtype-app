"""Durable, operation-scoped storage for audio and imported media."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


MAX_SOURCE_SIZE = 4 * 1024 * 1024 * 1024
_SAFE_OPERATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class InvalidSpoolPath(ValueError):
    """Raised when a requested spool path can escape the configured root."""


class SourceTooLarge(ValueError):
    """Raised when a source exceeds the Windows GA input limit."""


class InsufficientSpoolSpace(OSError):
    """Raised when an atomic spool copy cannot fit on the target volume."""


@dataclass(frozen=True)
class SpoolAsset:
    path: Path
    sha256: str
    size: int
    hardlinked: bool = False


class SpoolManager:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def operation_dir(self, operation_id: str) -> Path:
        if (
            not _SAFE_OPERATION_ID.fullmatch(operation_id)
            or operation_id in {".", ".."}
        ):
            raise InvalidSpoolPath("operation_id is not safe for a spool path")
        path = (self.root / operation_id).resolve()
        if not path.is_relative_to(self.root):
            raise InvalidSpoolPath("operation path escapes the spool root")
        return path

    def prepare_recording(self, operation_id: str) -> Path:
        operation_dir = self.operation_dir(operation_id)
        operation_dir.mkdir(parents=True, exist_ok=True)
        return operation_dir / "source.part"

    def finalize_recording(
        self,
        operation_id: str,
        *,
        suffix: str = ".wav",
    ) -> SpoolAsset:
        operation_dir = self.operation_dir(operation_id)
        part_path = operation_dir / "source.part"
        if not part_path.is_file():
            raise FileNotFoundError(part_path)
        size = part_path.stat().st_size
        if size > MAX_SOURCE_SIZE:
            raise SourceTooLarge("source exceeds the 4 GiB Windows GA limit")

        with part_path.open("r+b") as source:
            os.fsync(source.fileno())
        final_path = operation_dir / f"source{suffix}"
        os.replace(part_path, final_path)
        return self._describe(final_path)

    def import_source(self, operation_id: str, source_path: Path) -> SpoolAsset:
        source = Path(source_path).resolve(strict=True)
        if not source.is_file():
            raise FileNotFoundError(source)
        size = source.stat().st_size
        if size > MAX_SOURCE_SIZE:
            raise SourceTooLarge("source exceeds the 4 GiB Windows GA limit")

        operation_dir = self.operation_dir(operation_id)
        operation_dir.mkdir(parents=True, exist_ok=True)
        part_path = operation_dir / "source.part"
        suffix = source.suffix if re.fullmatch(r"\.[A-Za-z0-9]{1,15}", source.suffix) else ".bin"
        final_path = operation_dir / f"source{suffix.lower()}"

        hardlinked = False
        try:
            os.link(source, part_path)
            hardlinked = True
        except OSError:
            free_bytes = shutil.disk_usage(operation_dir).free
            if free_bytes < size:
                raise InsufficientSpoolSpace(
                    f"spool requires {size} bytes but only {free_bytes} are free"
                )
            try:
                with source.open("rb") as input_file, part_path.open("xb") as output:
                    shutil.copyfileobj(input_file, output, length=1024 * 1024)
                    output.flush()
                    os.fsync(output.fileno())
            except Exception:
                part_path.unlink(missing_ok=True)
                raise

        os.replace(part_path, final_path)
        return self._describe(final_path, hardlinked=hardlinked)

    def write_operation_metadata(
        self,
        operation_id: str,
        *,
        retention_deadline: Optional[datetime],
    ) -> Path:
        if retention_deadline is not None and retention_deadline.tzinfo is None:
            raise ValueError("retention_deadline must be timezone-aware")
        operation_dir = self.operation_dir(operation_id)
        operation_dir.mkdir(parents=True, exist_ok=True)
        final_path = operation_dir / "operation.json"
        part_path = operation_dir / "operation.json.part"
        payload = {
            "operation_id": operation_id,
            "retention_deadline": (
                retention_deadline.isoformat() if retention_deadline else None
            ),
        }
        try:
            part_path.unlink(missing_ok=True)
            with part_path.open("x", encoding="utf-8", newline="\n") as output:
                json.dump(payload, output, ensure_ascii=False, sort_keys=True)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(part_path, final_path)
        except Exception:
            part_path.unlink(missing_ok=True)
            raise
        return final_path

    def cleanup_expired(self, *, now: datetime) -> list[str]:
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        removed: list[str] = []
        for candidate in sorted(self.root.iterdir(), key=lambda path: path.name):
            if not candidate.is_dir():
                continue
            resolved = candidate.resolve()
            if resolved.parent != self.root:
                continue
            metadata_path = resolved / "operation.json"
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                if metadata.get("operation_id") != candidate.name:
                    continue
                deadline = datetime.fromisoformat(metadata["retention_deadline"])
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                continue
            if deadline.tzinfo is None or deadline > now:
                continue

            # The resolved parent check above is the destructive-operation guard.
            shutil.rmtree(resolved)
            removed.append(candidate.name)
        return removed

    def delete_source(self, operation_id: str) -> list[Path]:
        """Delete only MindType-owned source assets for an acknowledged result."""
        operation_dir = self.operation_dir(operation_id)
        if not operation_dir.exists():
            return []
        resolved_dir = operation_dir.resolve()
        if resolved_dir.parent != self.root:
            raise InvalidSpoolPath("operation path escapes the spool root")

        removed: list[Path] = []
        for candidate in resolved_dir.glob("source.*"):
            resolved = candidate.resolve()
            if resolved.parent != resolved_dir or not candidate.is_file():
                continue
            candidate.unlink()
            removed.append(candidate)
        return removed

    def delete_partial_outputs(self, operation_id: str) -> list[Path]:
        operation_dir = self.operation_dir(operation_id)
        if not operation_dir.exists():
            return []
        resolved_dir = operation_dir.resolve()
        if resolved_dir.parent != self.root:
            raise InvalidSpoolPath("operation path escapes the spool root")

        removed: list[Path] = []
        for name in ("source.part", "result.json.part"):
            candidate = resolved_dir / name
            if candidate.is_file():
                candidate.unlink()
                removed.append(candidate)
        checkpoints = resolved_dir / "checkpoints"
        if checkpoints.is_dir() and checkpoints.resolve().parent == resolved_dir:
            shutil.rmtree(checkpoints)
            removed.append(checkpoints)
        return removed

    @staticmethod
    def _describe(path: Path, *, hardlinked: bool = False) -> SpoolAsset:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
        return SpoolAsset(
            path=path,
            sha256=digest.hexdigest(),
            size=size,
            hardlinked=hardlinked,
        )
