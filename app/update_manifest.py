"""Fail-closed verification for the Windows update manifest."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Optional
from urllib.parse import urlparse

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class UpdateManifestError(ValueError):
    """The update metadata cannot establish the release trust chain."""


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){1,3}$")


@dataclass(frozen=True)
class VerifiedUpdateManifest:
    schema_version: str
    channel: str
    version: str
    platform: str
    architecture: str
    minimum_supported_version: str
    url: str
    sha256: str
    size: int
    published_at: datetime
    rollout_percentage: int
    authenticode_signer: str
    release_notes: str


def _base64url_decode(value: Any, *, field: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise UpdateManifestError(f"{field} must be non-empty base64url")
    try:
        return base64.b64decode(
            value + "=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (TypeError, ValueError) as exc:
        raise UpdateManifestError(f"{field} is not valid base64url") from exc


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    try:
        rendered = json.dumps(
            dict(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise UpdateManifestError("manifest is not canonical JSON data") from exc
    return rendered.encode("utf-8")


def _string(
    payload: Mapping[str, Any],
    field: str,
) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise UpdateManifestError(f"{field} must be a non-empty string")
    return value


def _parse_published_at(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise UpdateManifestError("published_at must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise UpdateManifestError("published_at must include a timezone")
    return parsed.astimezone(timezone.utc)


def verify_update_manifest(
    envelope: Mapping[str, Any],
    *,
    public_key: str,
    expected_channel: str,
    expected_platform: str,
    expected_architecture: str,
    expected_signer: str,
    allowed_hosts: Iterable[str],
    now: Optional[datetime] = None,
) -> VerifiedUpdateManifest:
    """Authenticate and validate one signed update manifest envelope."""
    if not isinstance(envelope, Mapping):
        raise UpdateManifestError("update envelope must be an object")
    raw_manifest = envelope.get("manifest")
    if not isinstance(raw_manifest, Mapping):
        raise UpdateManifestError("update envelope has no manifest object")

    try:
        verifier = Ed25519PublicKey.from_public_bytes(
            _base64url_decode(public_key, field="update public key")
        )
    except ValueError as exc:
        raise UpdateManifestError(
            "update public key is not Ed25519"
        ) from exc
    signature = _base64url_decode(
        envelope.get("signature"),
        field="manifest signature",
    )
    try:
        verifier.verify(signature, _canonical_json(raw_manifest))
    except InvalidSignature as exc:
        raise UpdateManifestError(
            "manifest signature is invalid"
        ) from exc

    schema_version = _string(raw_manifest, "schema_version")
    if schema_version != "1.0":
        raise UpdateManifestError("unsupported update manifest schema")
    channel = _string(raw_manifest, "channel")
    if channel != expected_channel:
        raise UpdateManifestError("manifest channel does not match client")
    platform = _string(raw_manifest, "platform")
    if platform != expected_platform:
        raise UpdateManifestError("manifest platform does not match client")
    architecture = _string(raw_manifest, "architecture")
    if architecture != expected_architecture:
        raise UpdateManifestError(
            "manifest architecture does not match client"
        )

    version = _string(raw_manifest, "version")
    minimum_version = _string(
        raw_manifest,
        "minimum_supported_version",
    )
    if not _VERSION.fullmatch(version) or not _VERSION.fullmatch(
        minimum_version
    ):
        raise UpdateManifestError("version fields are invalid")

    url = _string(raw_manifest, "url")
    parsed_url = urlparse(url)
    if parsed_url.scheme != "https":
        raise UpdateManifestError("update URL must use HTTPS")
    if parsed_url.username or parsed_url.password or parsed_url.fragment:
        raise UpdateManifestError("update URL contains forbidden components")
    allowed = {host.casefold() for host in allowed_hosts}
    if not parsed_url.hostname or parsed_url.hostname.casefold() not in allowed:
        raise UpdateManifestError("update URL host is not in allowlist")
    if expected_platform == "windows" and not parsed_url.path.casefold().endswith(
        ".exe"
    ):
        raise UpdateManifestError("Windows update URL must point to an EXE")

    sha256 = _string(raw_manifest, "sha256")
    if not _SHA256.fullmatch(sha256):
        raise UpdateManifestError(
            "sha256 must be a lowercase SHA-256 digest"
        )
    size = raw_manifest.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise UpdateManifestError("size must be a positive integer")

    percentage = raw_manifest.get("rollout_percentage")
    if (
        isinstance(percentage, bool)
        or not isinstance(percentage, int)
        or not 0 <= percentage <= 100
    ):
        raise UpdateManifestError(
            "rollout_percentage must be an integer from 0 to 100"
        )

    signer = _string(raw_manifest, "authenticode_signer")
    if not expected_signer or signer != expected_signer:
        raise UpdateManifestError(
            "manifest Authenticode signer does not match client trust root"
        )
    published_at = _parse_published_at(
        _string(raw_manifest, "published_at")
    )
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        raise ValueError("now must include a timezone")
    if published_at > clock.astimezone(timezone.utc) + timedelta(hours=24):
        raise UpdateManifestError("published_at is unreasonably far in future")

    release_notes = raw_manifest.get("release_notes", "")
    if not isinstance(release_notes, str):
        raise UpdateManifestError("release_notes must be a string")
    return VerifiedUpdateManifest(
        schema_version=schema_version,
        channel=channel,
        version=version,
        platform=platform,
        architecture=architecture,
        minimum_supported_version=minimum_version,
        url=url,
        sha256=sha256,
        size=size,
        published_at=published_at,
        rollout_percentage=percentage,
        authenticode_signer=signer,
        release_notes=release_notes,
    )


def device_is_in_rollout(
    *,
    device_id: str,
    version: str,
    percentage: int,
) -> bool:
    """Return a stable rollout decision without exposing the device ID."""
    if not 0 <= percentage <= 100:
        raise ValueError("percentage must be from 0 to 100")
    if percentage == 0:
        return False
    if percentage == 100:
        return True
    digest = hashlib.sha256(
        f"{version}\0{device_id}".encode("utf-8")
    ).digest()
    bucket = int.from_bytes(digest[:8], "big") % 100
    return bucket < percentage


__all__ = [
    "UpdateManifestError",
    "VerifiedUpdateManifest",
    "device_is_in_rollout",
    "verify_update_manifest",
]
