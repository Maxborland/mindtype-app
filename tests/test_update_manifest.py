from __future__ import annotations

import base64
import json
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def public_key_text(private_key: Ed25519PrivateKey) -> str:
    raw = private_key.public_key().public_bytes(
        Encoding.Raw,
        PublicFormat.Raw,
    )
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def signed_envelope(
    private_key: Ed25519PrivateKey,
    **overrides,
) -> dict:
    manifest = {
        "schema_version": "1.0",
        "channel": "stable",
        "version": "1.2.3",
        "platform": "windows",
        "architecture": "x86_64",
        "minimum_supported_version": "0.9.0",
        "url": "https://releases.mindtype.space/MindType-1.2.3-Setup.exe",
        "sha256": "a" * 64,
        "size": 53_000_000,
        "published_at": "2026-07-26T12:00:00+00:00",
        "rollout_percentage": 25,
        "authenticode_signer": "CN=MindType",
        "release_notes": "Reliability update",
    }
    manifest.update(overrides)
    canonical = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    signature = base64.urlsafe_b64encode(
        private_key.sign(canonical)
    ).rstrip(b"=").decode("ascii")
    return {"manifest": manifest, "signature": signature}


def test_signed_update_manifest_is_verified_and_normalized() -> None:
    from app.update_manifest import verify_update_manifest

    private_key = Ed25519PrivateKey.generate()
    verified = verify_update_manifest(
        signed_envelope(private_key),
        public_key=public_key_text(private_key),
        expected_channel="stable",
        expected_platform="windows",
        expected_architecture="x86_64",
        expected_signer="CN=MindType",
        allowed_hosts={"releases.mindtype.space"},
        now=datetime(2026, 7, 26, 13, tzinfo=timezone.utc),
    )

    assert verified.version == "1.2.3"
    assert verified.size == 53_000_000
    assert verified.sha256 == "a" * 64
    assert verified.url.endswith("MindType-1.2.3-Setup.exe")


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("url", "http://releases.mindtype.space/setup.exe", "HTTPS"),
        ("url", "https://evil.example/setup.exe", "allowlist"),
        ("sha256", "abc", "SHA-256"),
        ("size", 0, "size"),
        ("channel", "beta", "channel"),
        ("authenticode_signer", "CN=Attacker", "signer"),
        ("published_at", "not-a-date", "published_at"),
    ],
)
def test_manifest_rejects_invalid_trust_metadata(
    field: str,
    value,
    error: str,
) -> None:
    from app.update_manifest import UpdateManifestError, verify_update_manifest

    private_key = Ed25519PrivateKey.generate()
    envelope = signed_envelope(private_key, **{field: value})

    with pytest.raises(UpdateManifestError, match=error):
        verify_update_manifest(
            envelope,
            public_key=public_key_text(private_key),
            expected_channel="stable",
            expected_platform="windows",
            expected_architecture="x86_64",
            expected_signer="CN=MindType",
            allowed_hosts={"releases.mindtype.space"},
            now=datetime(2026, 7, 26, 13, tzinfo=timezone.utc),
        )


def test_tampered_signed_manifest_is_rejected() -> None:
    from app.update_manifest import UpdateManifestError, verify_update_manifest

    private_key = Ed25519PrivateKey.generate()
    envelope = signed_envelope(private_key)
    envelope["manifest"]["url"] = "https://evil.example/setup.exe"

    with pytest.raises(UpdateManifestError, match="signature"):
        verify_update_manifest(
            envelope,
            public_key=public_key_text(private_key),
            expected_channel="stable",
            expected_platform="windows",
            expected_architecture="x86_64",
            expected_signer="CN=MindType",
            allowed_hosts={
                "releases.mindtype.space",
                "evil.example",
            },
        )


def test_rollout_is_stable_per_device_and_version() -> None:
    from app.update_manifest import device_is_in_rollout

    decisions = {
        device_is_in_rollout(
            device_id="device-123",
            version="1.2.3",
            percentage=25,
        )
        for _ in range(10)
    }

    assert len(decisions) == 1
    assert device_is_in_rollout(
        device_id="device-123",
        version="1.2.3",
        percentage=0,
    ) is False
    assert device_is_in_rollout(
        device_id="device-123",
        version="1.2.3",
        percentage=100,
    ) is True


def test_release_signer_builds_verifiable_manifest_from_installer(
    tmp_path,
) -> None:
    import base64
    import hashlib

    from cryptography.hazmat.primitives import serialization

    from app.update_manifest import verify_update_manifest
    from scripts.create_update_manifest import create_signed_update_envelope

    installer = tmp_path / "MindType-1.2.3-Setup.exe"
    installer.write_bytes(b"signed-installer")
    private_key = Ed25519PrivateKey.generate()
    private_raw = private_key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public_raw = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )

    def encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    envelope = create_signed_update_envelope(
        installer=installer,
        private_key=encode(private_raw),
        channel="stable",
        version="1.2.3",
        minimum_supported_version="1.0.0",
        url="https://github.com/example/releases/MindType-1.2.3-Setup.exe",
        rollout_percentage=10,
        authenticode_signer="CN=MindType",
    )
    verified = verify_update_manifest(
        envelope,
        public_key=encode(public_raw),
        expected_channel="stable",
        expected_platform="windows",
        expected_architecture="x86_64",
        expected_signer="CN=MindType",
        allowed_hosts={"github.com"},
    )

    assert verified.sha256 == hashlib.sha256(b"signed-installer").hexdigest()
    assert verified.size == len(b"signed-installer")
    assert verified.rollout_percentage == 10
