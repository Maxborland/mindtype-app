"""Fail-closed validation for native runtime and model provenance manifests."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_REVISION = re.compile(r"^[0-9a-f]{40}$")
_UNKNOWN_VALUES = {"", "unknown", "unverified", "tbd", "n/a"}


class ManifestError(ValueError):
    """The artifact manifest cannot establish the required trust metadata."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"Cannot read artifact manifest {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ManifestError("Artifact manifest root must be an object")
    return value


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{field} must be a non-empty string")
    return value.strip()


def _validate_sha256(value: Any, field: str) -> str:
    digest = _required_string(value, field).lower()
    if not _SHA256.fullmatch(digest):
        raise ManifestError(f"{field} must be a lowercase SHA-256 digest")
    return digest


def _validate_local_file(
    record: dict[str, Any],
    *,
    root: Path,
    field_prefix: str,
) -> None:
    relative = Path(_required_string(record.get("path"), f"{field_prefix}.path"))
    if relative.is_absolute() or ".." in relative.parts:
        raise ManifestError(f"{field_prefix}.path must stay inside the repository")

    expected_size = record.get("size")
    if not isinstance(expected_size, int) or isinstance(expected_size, bool):
        raise ManifestError(f"{field_prefix}.size must be an integer")
    if expected_size <= 0:
        raise ManifestError(f"{field_prefix}.size must be positive")
    expected_hash = _validate_sha256(
        record.get("sha256"), f"{field_prefix}.sha256"
    )

    target = (root / relative).resolve()
    resolved_root = root.resolve()
    if not target.is_relative_to(resolved_root):
        raise ManifestError(f"{field_prefix}.path must stay inside the repository")
    if not target.is_file():
        raise ManifestError(f"Bundled artifact is missing: {relative}")
    if target.stat().st_size != expected_size:
        raise ManifestError(f"Size mismatch for bundled artifact: {relative}")

    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected_hash:
        raise ManifestError(f"SHA-256 mismatch for bundled artifact: {relative}")


def _validate_verified_artifact(
    artifact: Any,
    *,
    root: Path,
    index: int,
) -> None:
    if not isinstance(artifact, dict):
        raise ManifestError(f"artifacts[{index}] must be an object")
    prefix = f"artifacts[{index}]"

    _required_string(artifact.get("id"), f"{prefix}.id")
    kind = _required_string(artifact.get("kind"), f"{prefix}.kind")
    if kind not in {"runtime", "model"}:
        raise ManifestError(f"{prefix}.kind must be runtime or model")
    _required_string(artifact.get("runtime"), f"{prefix}.runtime")

    version = _required_string(artifact.get("version"), f"{prefix}.version")
    if version.lower() in _UNKNOWN_VALUES:
        raise ManifestError(f"{prefix}.version is not verified")

    url = _required_string(artifact.get("url"), f"{prefix}.url")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ManifestError(f"{prefix}.url must be an absolute HTTPS URL")

    license_name = _required_string(artifact.get("license"), f"{prefix}.license")
    if license_name.lower() in _UNKNOWN_VALUES:
        raise ManifestError(f"{prefix}.license is not verified")

    revision = _required_string(
        artifact.get("source_revision"), f"{prefix}.source_revision"
    ).lower()
    if not _SOURCE_REVISION.fullmatch(revision):
        raise ManifestError(f"{prefix}.source revision must be a 40-character commit")

    size = artifact.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise ManifestError(f"{prefix}.size must be a positive integer")
    _validate_sha256(artifact.get("sha256"), f"{prefix}.sha256")

    bundled = artifact.get("bundled")
    if not isinstance(bundled, bool):
        raise ManifestError(f"{prefix}.bundled must be a boolean")
    if bundled:
        _validate_local_file(artifact, root=root, field_prefix=prefix)


def verify_manifest(
    path: str | Path,
    *,
    root: str | Path,
    require_release_ready: bool = False,
) -> None:
    """Validate manifest structure, trust metadata, and bundled file hashes."""

    manifest_path = Path(path)
    repository_root = Path(root)
    manifest = _load_json(manifest_path)

    if manifest.get("schema_version") != "1.0":
        raise ManifestError("Unsupported artifact manifest schema version")
    if manifest.get("manifest_kind") not in {"runtime", "model"}:
        raise ManifestError("manifest_kind must be runtime or model")
    if not isinstance(manifest.get("release_ready"), bool):
        raise ManifestError("release_ready must be a boolean")

    artifacts = manifest.get("artifacts")
    unverified = manifest.get("unverified_artifacts")
    if not isinstance(artifacts, list) or not isinstance(unverified, list):
        raise ManifestError("artifacts and unverified_artifacts must be arrays")

    for index, artifact in enumerate(artifacts):
        _validate_verified_artifact(artifact, root=repository_root, index=index)

    for index, record in enumerate(unverified):
        if not isinstance(record, dict):
            raise ManifestError(f"unverified_artifacts[{index}] must be an object")
        _required_string(
            record.get("reason"), f"unverified_artifacts[{index}].reason"
        )
        _validate_local_file(
            record,
            root=repository_root,
            field_prefix=f"unverified_artifacts[{index}]",
        )

    if require_release_ready:
        if (
            not manifest["release_ready"]
            or unverified
            or not artifacts
        ):
            raise ManifestError(f"{manifest_path.name} is not release-ready")

