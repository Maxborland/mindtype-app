import hashlib
import json
from pathlib import Path

import pytest

from app.artifact_manifest import ManifestError, verify_manifest


ROOT = Path(__file__).resolve().parents[1]


def _write_manifest(path: Path, artifact_path: Path, **overrides) -> None:
    payload = artifact_path.read_bytes()
    artifact = {
        "id": "test-runtime",
        "kind": "runtime",
        "version": "1.2.3",
        "url": "https://downloads.example.com/runtime.bin",
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "license": "MIT",
        "runtime": "whisper.cpp",
        "source_revision": "a" * 40,
        "path": artifact_path.name,
        "bundled": True,
    }
    artifact.update(overrides)
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "manifest_kind": "runtime",
                "release_ready": True,
                "source_archive": {
                    "url": artifact["url"],
                    "size": 100,
                    "sha256": "b" * 64,
                    "source_revision": artifact["source_revision"],
                },
                "artifacts": [artifact],
                "unverified_artifacts": [],
            }
        ),
        encoding="utf-8",
    )


def test_verified_manifest_checks_local_size_and_hash(tmp_path):
    runtime = tmp_path / "runtime.bin"
    runtime.write_bytes(b"verified runtime")
    manifest = tmp_path / "runtime.json"
    _write_manifest(manifest, runtime)

    verify_manifest(manifest, root=tmp_path, require_release_ready=True)

    runtime.write_bytes(b"tampered runtime")
    with pytest.raises(ManifestError, match="SHA-256"):
        verify_manifest(manifest, root=tmp_path, require_release_ready=True)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("url", "http://downloads.example.com/runtime.bin", "HTTPS"),
        ("sha256", "not-a-hash", "SHA-256"),
        ("license", "UNKNOWN", "license"),
        ("source_revision", "main", "source revision"),
    ],
)
def test_verified_manifest_rejects_incomplete_trust_metadata(
    tmp_path, field, value, message
):
    runtime = tmp_path / "runtime.bin"
    runtime.write_bytes(b"verified runtime")
    manifest = tmp_path / "runtime.json"
    _write_manifest(manifest, runtime, **{field: value})

    with pytest.raises(ManifestError, match=message):
        verify_manifest(manifest, root=tmp_path, require_release_ready=True)


def test_checked_in_runtime_manifest_is_release_ready():
    manifest = ROOT / "manifests" / "whisper-runtime.windows-x64.json"
    verify_manifest(manifest, root=ROOT, require_release_ready=True)


def test_packaged_runtime_verification_uses_release_ready_manifest(monkeypatch):
    import app.artifact_manifest as artifact_manifest

    artifact_manifest.verify_packaged_runtime.cache_clear()
    monkeypatch.setattr(
        artifact_manifest,
        "default_runtime_manifest_path",
        lambda: ROOT / "manifests" / "whisper-runtime.windows-x64.json",
    )

    artifact_manifest.verify_packaged_runtime()


def test_checked_in_downloadable_model_manifest_is_release_ready():
    verify_manifest(
        ROOT / "manifests" / "models.json",
        root=ROOT,
        require_release_ready=True,
    )


def test_pyinstaller_bundles_only_the_declared_whisper_runtime_files():
    spec = (ROOT / "mindtype.spec").read_text(encoding="utf-8")

    assert 'ROOT / "bin" / "win-x64", "bin/win-x64"' not in spec
    for name in [
        "whisper-cli.exe",
        "whisper-server.exe",
        "whisper.dll",
        "ggml-base.dll",
        "ggml.dll",
        "ggml-cpu-alderlake.dll",
        "ggml-cpu-cannonlake.dll",
        "ggml-cpu-cascadelake.dll",
        "ggml-cpu-haswell.dll",
        "ggml-cpu-icelake.dll",
        "ggml-cpu-sandybridge.dll",
        "ggml-cpu-skylakex.dll",
        "ggml-cpu-sse42.dll",
        "ggml-cpu-x64.dll",
    ]:
        assert name in spec
    assert "ggml-vulkan.dll" not in spec
    assert '"ggml-cpu.dll"' not in spec
    assert 'ROOT / "manifests" / "models.json"' in spec
    assert (
        'ROOT / "manifests" / "whisper-runtime.windows-x64.json"'
        in spec
    )


def test_base_installer_excludes_optional_local_diarization_stack():
    spec = (ROOT / "mindtype.spec").read_text(encoding="utf-8")
    base = (ROOT / "requirements" / "base.in").read_text(encoding="utf-8")
    optional = (
        ROOT / "requirements" / "local-diarization.in"
    ).read_text(encoding="utf-8")

    for package in ["librosa", "scikit-learn"]:
        assert package not in base
        assert package in optional
    for module in ["librosa", "sklearn", "scipy", "numba", "llvmlite"]:
        assert f'"{module}"' in spec
