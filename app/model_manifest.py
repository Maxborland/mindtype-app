"""Runtime lookup and integrity verification for downloadable model weights."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")


class ModelManifestError(ValueError):
    pass


@dataclass(frozen=True)
class ModelArtifact:
    model_id: str
    filename: str
    version: str
    url: str
    size: int
    sha256: str
    license: str
    source_revision: str


def default_model_manifest_path() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root) / "manifests" / "models.json"
    return Path(__file__).resolve().parents[1] / "manifests" / "models.json"


def load_model_artifacts(
    path: Path | None = None,
) -> dict[str, ModelArtifact]:
    manifest_path = Path(path) if path is not None else default_model_manifest_path()
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelManifestError("model manifest is unavailable") from exc
    if (
        not isinstance(payload, Mapping)
        or payload.get("schema_version") != "1.0"
        or payload.get("manifest_kind") != "model"
        or payload.get("release_ready") is not True
    ):
        raise ModelManifestError("model manifest is not release-ready")
    records = payload.get("artifacts")
    if not isinstance(records, list) or not records:
        raise ModelManifestError("model manifest has no verified artifacts")

    result: dict[str, ModelArtifact] = {}
    for raw in records:
        if not isinstance(raw, Mapping):
            raise ModelManifestError("model artifact must be an object")
        model_id = str(raw.get("id") or "").strip()
        filename = str(raw.get("filename") or "").strip()
        digest = str(raw.get("sha256") or "").strip()
        size = raw.get("size")
        url = str(raw.get("url") or "").strip()
        source_revision = str(raw.get("source_revision") or "").strip()
        parsed_url = urlparse(url)
        if (
            not model_id
            or not re.fullmatch(r"ggml-[A-Za-z0-9._-]+\.bin", filename)
            or not _SHA256.fullmatch(digest)
            or parsed_url.scheme != "https"
            or not parsed_url.hostname
            or not _REVISION.fullmatch(source_revision)
            or source_revision not in url
            or not str(raw.get("version") or "").strip()
            or not str(raw.get("license") or "").strip()
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size <= 0
        ):
            raise ModelManifestError("model artifact integrity fields are invalid")
        if model_id in result:
            raise ModelManifestError("model artifact ids must be unique")
        result[model_id] = ModelArtifact(
            model_id=model_id,
            filename=filename,
            version=str(raw.get("version") or ""),
            url=url,
            size=size,
            sha256=digest,
            license=str(raw.get("license") or ""),
            source_revision=source_revision,
        )
    return result


def get_model_artifact(model_id: str) -> ModelArtifact:
    normalized = model_id.removeprefix("ggml-").removesuffix(".bin").lower()
    artifact = load_model_artifacts().get(normalized)
    if artifact is None:
        raise ModelManifestError(
            f"model {normalized!r} is not present in the verified manifest"
        )
    return artifact


def verify_model_file(path: Path, artifact: ModelArtifact) -> None:
    target = Path(path)
    if not target.is_file() or target.stat().st_size != artifact.size:
        raise ModelManifestError(
            f"{artifact.filename} size does not match the verified manifest"
        )
    digest = hashlib.sha256()
    with target.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != artifact.sha256:
        raise ModelManifestError(
            f"{artifact.filename} SHA-256 does not match the verified manifest"
        )


__all__ = [
    "ModelArtifact",
    "ModelManifestError",
    "get_model_artifact",
    "load_model_artifacts",
    "verify_model_file",
]
