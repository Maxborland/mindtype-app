from __future__ import annotations

import hashlib
import io
from pathlib import Path
from unittest.mock import MagicMock, patch
import urllib.request

import pytest


def manifest_for(installer: Path):
    from app.update_manifest import VerifiedUpdateManifest
    from datetime import datetime, timezone

    content = installer.read_bytes()
    return VerifiedUpdateManifest(
        schema_version="1.0",
        channel="stable",
        version="1.2.3",
        platform="windows",
        architecture="x86_64",
        minimum_supported_version="0.9.0",
        url="https://releases.mindtype.space/setup.exe",
        sha256=hashlib.sha256(content).hexdigest(),
        size=len(content),
        published_at=datetime.now(timezone.utc),
        rollout_percentage=100,
        authenticode_signer="CN=MindType",
        release_notes="",
    )


def test_installer_size_and_hash_are_checked_before_authenticode(
    tmp_path: Path,
) -> None:
    from app.update_installer import (
        InstallerVerificationError,
        verify_downloaded_installer,
    )

    installer = tmp_path / "MindType-Setup.exe"
    installer.write_bytes(b"installer")
    manifest = manifest_for(installer)
    installer.write_bytes(b"tampered!")
    checker = MagicMock()

    with pytest.raises(InstallerVerificationError, match="SHA-256"):
        verify_downloaded_installer(
            installer,
            manifest,
            authenticode_checker=checker,
        )

    checker.assert_not_called()


def test_valid_installer_requires_expected_authenticode_subject(
    tmp_path: Path,
) -> None:
    from app.update_installer import (
        AuthenticodeIdentity,
        verify_downloaded_installer,
    )

    installer = tmp_path / "MindType-Setup.exe"
    installer.write_bytes(b"installer")
    manifest = manifest_for(installer)
    checker = MagicMock(
        return_value=AuthenticodeIdentity(
            status="Valid",
            subject="CN=MindType",
            thumbprint="ABCDEF",
        )
    )

    identity = verify_downloaded_installer(
        installer,
        manifest,
        authenticode_checker=checker,
    )

    assert identity.thumbprint == "ABCDEF"
    checker.assert_called_once_with(installer, "CN=MindType")


def test_authenticode_checker_passes_path_out_of_command_text(
    tmp_path: Path,
) -> None:
    from app.update_installer import verify_windows_authenticode

    installer = tmp_path / "setup'; Remove-Item important; '.exe"
    installer.write_bytes(b"installer")
    process = MagicMock()
    process.returncode = 0
    process.stdout = (
        '{"status":"Valid","subject":"CN=MindType","thumbprint":"ABC"}'
    )

    with patch("subprocess.run", return_value=process) as run:
        identity = verify_windows_authenticode(
            installer,
            "CN=MindType",
        )

    command = run.call_args.args[0]
    environment = run.call_args.kwargs["env"]
    assert str(installer) not in " ".join(command)
    assert environment["MINDTYPE_INSTALLER_PATH"] == str(installer)
    assert identity.status == "Valid"


@pytest.mark.parametrize(
    ("status", "subject", "match"),
    [
        ("NotSigned", "", "not valid"),
        ("Valid", "CN=Attacker", "signer"),
    ],
)
def test_authenticode_checker_fails_closed(
    tmp_path: Path,
    status: str,
    subject: str,
    match: str,
) -> None:
    from app.update_installer import (
        InstallerVerificationError,
        verify_windows_authenticode,
    )

    installer = tmp_path / "setup.exe"
    installer.write_bytes(b"installer")
    process = MagicMock()
    process.returncode = 0
    process.stdout = (
        f'{{"status":"{status}","subject":"{subject}",'
        '"thumbprint":"ABC"}'
    )

    with (
        patch("subprocess.run", return_value=process),
        pytest.raises(InstallerVerificationError, match=match),
    ):
        verify_windows_authenticode(installer, "CN=MindType")


def test_redirect_handler_rejects_downgrade_and_unlisted_host() -> None:
    from app.update_installer import (
        InstallerVerificationError,
        SafeUpdateRedirectHandler,
    )

    handler = SafeUpdateRedirectHandler({"releases.mindtype.space"})
    request = urllib.request.Request(
        "https://releases.mindtype.space/setup.exe"
    )

    with pytest.raises(InstallerVerificationError, match="HTTPS"):
        handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "http://releases.mindtype.space/setup.exe",
        )
    with pytest.raises(InstallerVerificationError, match="allowlist"):
        handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://evil.example/setup.exe",
        )


def test_default_redirect_policy_allows_github_release_asset_host() -> None:
    from app.update_installer import SafeUpdateRedirectHandler
    from app.updater import UPDATE_DOWNLOAD_HOSTS

    handler = SafeUpdateRedirectHandler(UPDATE_DOWNLOAD_HOSTS)
    redirected = handler.redirect_request(
        urllib.request.Request(
            "https://github.com/Maxborland/mindtype-app/releases/download/v1/app.exe"
        ),
        None,
        302,
        "Found",
        {},
        (
            "https://release-assets.githubusercontent.com/"
            "github-production-release-asset/app.exe"
        ),
    )

    assert redirected.full_url.startswith(
        "https://release-assets.githubusercontent.com/"
    )


class FakeDownloadResponse:
    def __init__(self, content: bytes, *, final_url: str) -> None:
        self._stream = io.BytesIO(content)
        self._url = final_url
        self.headers = {"Content-Length": str(len(content))}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size=-1):
        return self._stream.read(size)

    def geturl(self):
        return self._url


class FakeOpener:
    def __init__(self, response) -> None:
        self.response = response
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        return self.response


def test_download_is_published_only_after_all_verification(
    tmp_path: Path,
) -> None:
    from app.update_installer import (
        AuthenticodeIdentity,
        download_verified_installer,
    )

    content = b"signed-installer"
    seed = tmp_path / "seed.exe"
    seed.write_bytes(content)
    manifest = manifest_for(seed)
    destination = tmp_path / "MindType-1.2.3-Setup.exe"
    opener = FakeOpener(
        FakeDownloadResponse(content, final_url=manifest.url)
    )
    checker = MagicMock(
        return_value=AuthenticodeIdentity(
            status="Valid",
            subject="CN=MindType",
            thumbprint="ABC",
        )
    )

    published = download_verified_installer(
        manifest,
        destination,
        allowed_hosts={"releases.mindtype.space"},
        opener=opener,
        authenticode_checker=checker,
    )

    assert published == destination
    assert published.read_bytes() == content
    assert not destination.with_name(f"{destination.name}.part").exists()
    checker.assert_called_once()


def test_truncated_download_is_removed_without_overwriting_existing_installer(
    tmp_path: Path,
) -> None:
    from app.update_installer import (
        InstallerVerificationError,
        download_verified_installer,
    )

    expected = tmp_path / "expected.exe"
    expected.write_bytes(b"complete-installer")
    manifest = manifest_for(expected)
    destination = tmp_path / "MindType-1.2.3-Setup.exe"
    destination.write_bytes(b"previous-valid-installer")
    opener = FakeOpener(
        FakeDownloadResponse(b"short", final_url=manifest.url)
    )

    with pytest.raises(InstallerVerificationError, match="Content-Length"):
        download_verified_installer(
            manifest,
            destination,
            allowed_hosts={"releases.mindtype.space"},
            opener=opener,
            authenticode_checker=MagicMock(),
        )

    assert destination.read_bytes() == b"previous-valid-installer"
    assert not destination.with_name(f"{destination.name}.part").exists()
