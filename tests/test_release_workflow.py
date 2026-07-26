"""Static release-contract checks that run without GitHub credentials."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
CANONICAL = WORKFLOWS / "build-release.yml"


def test_one_workflow_owns_version_tag_releases():
    tag_owners = []
    for workflow in WORKFLOWS.glob("*.yml"):
        text = workflow.read_text(encoding="utf-8")
        if re.search(r"tags:\s*\n\s*-\s*['\"]v\\?\\?\\*|tags:\s*\n\s*-\s*['\"]v\\?\\*",
                     text):
            tag_owners.append(workflow.name)

    assert tag_owners == ["build-release.yml"]


def test_actions_are_pinned_to_commit_shas():
    text = CANONICAL.read_text(encoding="utf-8")
    action_refs = re.findall(r"uses:\s*([^\s#]+)", text)

    assert action_refs
    assert all(re.search(r"@[0-9a-f]{40}$", ref) for ref in action_refs)


def test_release_runs_tests_and_uses_existing_build_spec():
    workflow = CANONICAL.read_text(encoding="utf-8")
    build_script = (ROOT / "build_windows.ps1").read_text(encoding="utf-8")

    assert "python -m pytest -q" in workflow
    assert "build_windows.ps1" in workflow
    assert 'Join-Path $RootDir "mindtype.spec"' in build_script
    assert (ROOT / "mindtype.spec").is_file()


def test_tag_release_requires_signing_and_publishes_checksum():
    text = CANONICAL.read_text(encoding="utf-8")

    assert "WINDOWS_SIGNING_CERT_BASE64" in text
    assert "Get-AuthenticodeSignature" in text
    assert "Get-FileHash" in text
    assert ".sha256" in text


def test_uninstall_preserves_user_data():
    installer = (ROOT / "installer" / "windows.iss").read_text(
        encoding="utf-8"
    )

    assert "[UninstallDelete]" not in installer
    assert "{userappdata}" not in installer
    assert "{localappdata}" not in installer


def test_onnx_dependencies_use_a_compatible_transformers_range():
    base = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    onnx = (ROOT / "requirements-local-onnx.txt").read_text(encoding="utf-8")
    assistant = (ROOT / "requirements-assistant.txt").read_text(encoding="utf-8")

    assert "transformers" not in base
    assert "optimum" not in base
    assert "onnxruntime" not in base
    assert "openwakeword" not in base
    assert "transformers>=4.56.0,<4.58.0" in onnx
    assert "optimum[onnxruntime]>=2.1.0,<2.3.0" in onnx
    assert "openwakeword>=0.6.0" in assistant


def test_base_pyinstaller_excludes_optional_ml_runtimes():
    spec = (ROOT / "mindtype.spec").read_text(encoding="utf-8")

    for module in ["torch", "transformers", "optimum", "onnxruntime", "openwakeword"]:
        assert f'"{module}"' in spec
