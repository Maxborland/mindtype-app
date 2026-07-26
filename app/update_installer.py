"""Verification boundary for a downloaded Windows installer."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional
from urllib.parse import urlparse

from .update_manifest import VerifiedUpdateManifest


class InstallerVerificationError(ValueError):
    """The downloaded installer failed one of the trust-chain checks."""


@dataclass(frozen=True)
class AuthenticodeIdentity:
    status: str
    subject: str
    thumbprint: str


def _validate_download_url(
    url: str,
    *,
    allowed_hosts: Iterable[str],
) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise InstallerVerificationError("update download must use HTTPS")
    if parsed.username or parsed.password or parsed.fragment:
        raise InstallerVerificationError(
            "update download URL contains forbidden components"
        )
    allowed = {host.casefold() for host in allowed_hosts}
    if not parsed.hostname or parsed.hostname.casefold() not in allowed:
        raise InstallerVerificationError(
            "update download host is not in allowlist"
        )
    return url


class SafeUpdateRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject a redirect before urllib can follow it outside the trust scope."""

    def __init__(self, allowed_hosts: Iterable[str]) -> None:
        super().__init__()
        self.allowed_hosts = frozenset(allowed_hosts)

    def redirect_request(
        self,
        request,
        file_pointer,
        code,
        message,
        headers,
        new_url,
    ):
        _validate_download_url(
            new_url,
            allowed_hosts=self.allowed_hosts,
        )
        return super().redirect_request(
            request,
            file_pointer,
            code,
            message,
            headers,
            new_url,
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def verify_windows_authenticode(
    path: Path,
    expected_subject: str,
) -> AuthenticodeIdentity:
    """Ask Windows to validate the signature without interpolating the path."""
    installer = Path(path).resolve(strict=True)
    environment = os.environ.copy()
    environment["MINDTYPE_INSTALLER_PATH"] = str(installer)
    script = (
        "$signature = Get-AuthenticodeSignature "
        "-LiteralPath $env:MINDTYPE_INSTALLER_PATH; "
        "[ordered]@{"
        "status=[string]$signature.Status;"
        "subject=[string]$signature.SignerCertificate.Subject;"
        "thumbprint=[string]$signature.SignerCertificate.Thumbprint"
        "} | ConvertTo-Json -Compress"
    )
    try:
        process = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
            env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise InstallerVerificationError(
            "Authenticode verification could not run"
        ) from exc
    if process.returncode != 0:
        raise InstallerVerificationError(
            "Authenticode verification failed"
        )
    try:
        payload = json.loads(process.stdout)
        identity = AuthenticodeIdentity(
            status=str(payload.get("status") or ""),
            subject=str(payload.get("subject") or ""),
            thumbprint=str(payload.get("thumbprint") or ""),
        )
    except (AttributeError, json.JSONDecodeError) as exc:
        raise InstallerVerificationError(
            "Authenticode returned an invalid response"
        ) from exc
    if identity.status != "Valid":
        raise InstallerVerificationError(
            f"Authenticode signature is not valid: {identity.status}"
        )
    if not expected_subject or identity.subject != expected_subject:
        raise InstallerVerificationError(
            "Authenticode signer does not match the release trust root"
        )
    if not identity.thumbprint:
        raise InstallerVerificationError(
            "Authenticode signer certificate has no thumbprint"
        )
    return identity


def verify_downloaded_installer(
    path: Path,
    manifest: VerifiedUpdateManifest,
    *,
    authenticode_checker: Callable[
        [Path, str], AuthenticodeIdentity
    ] = verify_windows_authenticode,
) -> AuthenticodeIdentity:
    """Verify local bytes before they can ever be offered for execution."""
    installer = Path(path)
    if not installer.is_file():
        raise InstallerVerificationError("downloaded installer is missing")
    if installer.stat().st_size != manifest.size:
        raise InstallerVerificationError(
            "downloaded installer size does not match manifest"
        )
    if _sha256(installer) != manifest.sha256:
        raise InstallerVerificationError(
            "downloaded installer SHA-256 does not match manifest"
        )
    return authenticode_checker(
        installer,
        manifest.authenticode_signer,
    )


def download_verified_installer(
    manifest: VerifiedUpdateManifest,
    destination: Path,
    *,
    allowed_hosts: Iterable[str],
    opener: Optional[object] = None,
    authenticode_checker: Callable[
        [Path, str], AuthenticodeIdentity
    ] = verify_windows_authenticode,
    timeout: float = 60,
) -> Path:
    """Download into a side file and publish only fully authenticated bytes."""
    allowed = frozenset(allowed_hosts)
    _validate_download_url(manifest.url, allowed_hosts=allowed)
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(f"{target.name}.part")
    part.unlink(missing_ok=True)
    transport = opener or urllib.request.build_opener(
        SafeUpdateRedirectHandler(allowed)
    )
    request = urllib.request.Request(
        manifest.url,
        headers={"Accept": "application/octet-stream"},
    )
    try:
        with transport.open(request, timeout=timeout) as response:
            _validate_download_url(
                response.geturl(),
                allowed_hosts=allowed,
            )
            raw_length = response.headers.get("Content-Length")
            if raw_length is not None:
                try:
                    content_length = int(raw_length)
                except (TypeError, ValueError) as exc:
                    raise InstallerVerificationError(
                        "download Content-Length is invalid"
                    ) from exc
                if content_length != manifest.size:
                    raise InstallerVerificationError(
                        "download Content-Length does not match manifest"
                    )
            received = 0
            with part.open("xb") as stream:
                while chunk := response.read(1024 * 1024):
                    received += len(chunk)
                    if received > manifest.size:
                        raise InstallerVerificationError(
                            "download exceeded manifest size"
                        )
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            if received != manifest.size:
                raise InstallerVerificationError(
                    "download size does not match manifest"
                )
        verify_downloaded_installer(
            part,
            manifest,
            authenticode_checker=authenticode_checker,
        )
        os.replace(part, target)
        return target
    except Exception:
        part.unlink(missing_ok=True)
        raise


__all__ = [
    "AuthenticodeIdentity",
    "InstallerVerificationError",
    "SafeUpdateRedirectHandler",
    "download_verified_installer",
    "verify_downloaded_installer",
    "verify_windows_authenticode",
]
