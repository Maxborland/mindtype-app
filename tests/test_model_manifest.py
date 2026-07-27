from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


def test_checked_in_model_manifest_has_pinned_downloads() -> None:
    from app.model_manifest import load_model_artifacts

    artifacts = load_model_artifacts()

    assert {"tiny", "small", "medium", "large-v3"} <= artifacts.keys()
    for artifact in artifacts.values():
        assert artifact.url.startswith("https://")
        assert artifact.source_revision in artifact.url
        assert len(artifact.sha256) == 64
        assert artifact.size > 0


def test_model_file_requires_exact_size_and_sha256(tmp_path: Path) -> None:
    from app.model_manifest import (
        ModelArtifact,
        ModelManifestError,
        verify_model_file,
    )

    content = b"verified model"
    path = tmp_path / "ggml-test.bin"
    path.write_bytes(content)
    artifact = ModelArtifact(
        model_id="test",
        filename=path.name,
        version="test",
        url="https://example.com/ggml-test.bin",
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        license="MIT",
        source_revision="a" * 40,
    )

    verify_model_file(path, artifact)
    path.write_bytes(b"tampered model")
    with pytest.raises(ModelManifestError):
        verify_model_file(path, artifact)


def test_non_release_ready_manifest_cannot_authorize_downloads(
    tmp_path: Path,
) -> None:
    from app.model_manifest import ModelManifestError, load_model_artifacts

    manifest = tmp_path / "models.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "manifest_kind": "model",
                "release_ready": False,
                "artifacts": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ModelManifestError, match="release-ready"):
        load_model_artifacts(manifest)
