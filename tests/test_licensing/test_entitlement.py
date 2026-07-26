import base64
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
)

from app.licensing.entitlement import (
    EntitlementLeaseStore,
    EntitlementLeaseVerifier,
    LeaseValidationError,
)


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


@pytest.fixture
def signing_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


@pytest.fixture
def verifier(signing_key: Ed25519PrivateKey) -> EntitlementLeaseVerifier:
    public_key = signing_key.public_key().public_bytes(
        Encoding.Raw,
        PublicFormat.Raw,
    )
    return EntitlementLeaseVerifier(_b64url(public_key))


def _lease(
    signing_key: Ed25519PrivateKey,
    *,
    device_id: str = "device-123",
    issued_at: datetime | None = None,
    expires_at: datetime | None = None,
    claim_version: int = 1,
) -> str:
    issued_at = issued_at or datetime.now(timezone.utc)
    expires_at = expires_at or issued_at + timedelta(days=7)
    payload = {
        "claim_version": claim_version,
        "iss": "mindtype.space",
        "aud": "mindtype-desktop",
        "sub": "account-123",
        "device_id": device_id,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
        "plan": "personal",
        "features": ["local_processing", "cloud_processing"],
        "limits": {"max_devices": 2},
    }
    encoded_payload = _b64url(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    signature = signing_key.sign(encoded_payload.encode("ascii"))
    return f"{encoded_payload}.{_b64url(signature)}"


def test_valid_lease_is_verified_and_typed(
    signing_key: Ed25519PrivateKey,
    verifier: EntitlementLeaseVerifier,
) -> None:
    token = _lease(signing_key)

    claims = verifier.verify(token, device_id="device-123")

    assert claims.account_id == "account-123"
    assert claims.plan == "personal"
    assert claims.features == ("local_processing", "cloud_processing")
    assert claims.limits == {"max_devices": 2}


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("signature", "INVALID_SIGNATURE"),
        ("device", "DEVICE_MISMATCH"),
        ("version", "SCHEMA_UNSUPPORTED"),
    ],
)
def test_invalid_lease_fails_closed(
    signing_key: Ed25519PrivateKey,
    verifier: EntitlementLeaseVerifier,
    mutation: str,
    expected_code: str,
) -> None:
    token = _lease(
        signing_key,
        device_id="other-device" if mutation == "device" else "device-123",
        claim_version=2 if mutation == "version" else 1,
    )
    if mutation == "signature":
        payload, signature = token.split(".")
        signature_bytes = bytearray(
            base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        )
        signature_bytes[0] ^= 1
        token = f"{payload}.{_b64url(bytes(signature_bytes))}"

    with pytest.raises(LeaseValidationError) as exc:
        verifier.verify(token, device_id="device-123")

    assert exc.value.code == expected_code


def test_expired_lease_fails_closed(
    signing_key: Ed25519PrivateKey,
    verifier: EntitlementLeaseVerifier,
) -> None:
    now = datetime.now(timezone.utc)
    token = _lease(
        signing_key,
        issued_at=now - timedelta(days=7),
        expires_at=now - timedelta(minutes=1),
    )

    with pytest.raises(LeaseValidationError) as exc:
        verifier.verify(token, device_id="device-123", now=now)

    assert exc.value.code == "ENTITLEMENT_EXPIRED"


def test_lease_cannot_grant_more_than_seven_days(
    signing_key: Ed25519PrivateKey,
    verifier: EntitlementLeaseVerifier,
) -> None:
    now = datetime.now(timezone.utc)
    token = _lease(
        signing_key,
        issued_at=now,
        expires_at=now + timedelta(days=8),
    )

    with pytest.raises(LeaseValidationError) as exc:
        verifier.verify(token, device_id="device-123", now=now)

    assert exc.value.code == "LEASE_TOO_LONG"


def test_store_verifies_before_replace_and_preserves_last_valid_lease(
    tmp_path,
    signing_key: Ed25519PrivateKey,
    verifier: EntitlementLeaseVerifier,
) -> None:
    path = tmp_path / "entitlement.lease"
    store = EntitlementLeaseStore(path, verifier, device_id="device-123")
    valid_token = _lease(signing_key)
    store.save(valid_token)

    with pytest.raises(LeaseValidationError):
        store.save("not-a-signed-lease")

    assert path.read_text(encoding="utf-8") == valid_token
    assert store.load().plan == "personal"


def test_license_manager_migrates_legacy_cache_to_signed_lease(
    tmp_path,
    signing_key: Ed25519PrivateKey,
    verifier: EntitlementLeaseVerifier,
) -> None:
    from app.licensing.license_manager import LicenseManager, LicenseStatus

    data_dir = tmp_path / "MindType"
    with (
        patch(
            "app.licensing.license_manager._get_data_dir",
            return_value=data_dir,
        ),
        patch(
            "app.licensing.trial._get_data_dir",
            return_value=data_dir,
        ),
    ):
        manager = LicenseManager(lease_verifier=verifier)
        manager._license_data = {
            "license_key": "ABCDEFGHJKMNPQRS",
            "validated_at": datetime.now().isoformat(),
        }
        manager._save_license()
        assert manager._license_file.exists()

        manager.install_entitlement_lease(
            _lease(signing_key, device_id=manager.get_device_id())
        )
        restarted = LicenseManager(lease_verifier=verifier)

    info = restarted.get_license_info()
    assert info.status is LicenseStatus.VALID
    assert info.plan == "personal"
    assert info.max_devices == 2
    assert not manager._license_file.exists()
    assert manager._lease_file.exists()
    assert manager._lease_marker_file.exists()


def test_expired_seen_lease_does_not_start_a_new_local_trial(
    tmp_path,
    signing_key: Ed25519PrivateKey,
    verifier: EntitlementLeaseVerifier,
) -> None:
    from app.licensing.license_manager import LicenseManager, LicenseStatus

    data_dir = tmp_path / "MindType"
    now = datetime.now(timezone.utc)
    with (
        patch(
            "app.licensing.license_manager._get_data_dir",
            return_value=data_dir,
        ),
        patch(
            "app.licensing.trial._get_data_dir",
            return_value=data_dir,
        ),
    ):
        manager = LicenseManager(lease_verifier=verifier)
        data_dir.mkdir(parents=True, exist_ok=True)
        manager._lease_file.write_text(
            _lease(
                signing_key,
                device_id=manager.get_device_id(),
                issued_at=now - timedelta(days=7),
                expires_at=now - timedelta(minutes=1),
            ),
            encoding="utf-8",
        )
        manager._lease_marker_file.write_text("1", encoding="ascii")
        restarted = LicenseManager(lease_verifier=verifier)
        has_access, info = restarted.check_access()

    assert has_access is False
    assert info.status is LicenseStatus.INVALID
    assert restarted._trial_manager.has_trial_started() is False
