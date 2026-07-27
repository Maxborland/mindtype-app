import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

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


def test_store_rejects_clock_rollback_after_prior_validation(
    tmp_path,
    signing_key: Ed25519PrivateKey,
    verifier: EntitlementLeaseVerifier,
) -> None:
    issued_at = datetime(2026, 7, 20, tzinfo=timezone.utc)
    path = tmp_path / "entitlement.lease"
    store = EntitlementLeaseStore(path, verifier, device_id="device-123")
    store.save(
        _lease(
            signing_key,
            issued_at=issued_at,
            expires_at=issued_at + timedelta(days=7),
        ),
        now=issued_at + timedelta(days=2),
    )

    with pytest.raises(LeaseValidationError) as exc:
        store.load(now=issued_at + timedelta(hours=1))

    assert exc.value.code == "CLOCK_ROLLBACK"
    assert store.clock_path.is_file()


def test_store_rejects_missing_clock_for_an_adopted_lease(
    tmp_path,
    signing_key: Ed25519PrivateKey,
    verifier: EntitlementLeaseVerifier,
) -> None:
    issued_at = datetime(2026, 7, 20, tzinfo=timezone.utc)
    path = tmp_path / "entitlement.lease"
    store = EntitlementLeaseStore(path, verifier, device_id="device-123")
    store.save(
        _lease(
            signing_key,
            issued_at=issued_at,
            expires_at=issued_at + timedelta(days=7),
        ),
        now=issued_at + timedelta(days=2),
    )
    store.clock_path.unlink()

    with pytest.raises(LeaseValidationError) as exc:
        store.load(now=issued_at + timedelta(hours=1))

    assert exc.value.code == "ENTITLEMENT_CLOCK_INVALID"
    assert not store.clock_path.exists()


def test_authoritative_lease_rebuilds_missing_clock(
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
        manager.install_entitlement_lease(
            _lease(
                signing_key,
                device_id=manager.get_device_id(),
                issued_at=now,
                expires_at=now + timedelta(days=7),
            ),
            now=now,
        )
        manager._lease_store.clock_path.unlink()
        manager.install_entitlement_lease(
            _lease(
                signing_key,
                device_id=manager.get_device_id(),
                issued_at=now + timedelta(minutes=1),
                expires_at=now + timedelta(days=7),
            ),
            now=now + timedelta(minutes=1),
        )

    assert manager._lease_store.clock_path.is_file()
    assert manager.get_license_info().status is LicenseStatus.VALID


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


def test_lease_migration_marker_survives_crash_before_lease_publish(
    tmp_path,
    signing_key: Ed25519PrivateKey,
    verifier: EntitlementLeaseVerifier,
) -> None:
    import app.licensing.entitlement as entitlement_module
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
        durable_write = entitlement_module.write_durable_text

        def crash_before_lease(path: Path, value: str) -> None:
            if path == manager._lease_file:
                raise OSError("power loss")
            durable_write(path, value)

        with patch.object(
            entitlement_module,
            "write_durable_text",
            side_effect=crash_before_lease,
        ):
            with pytest.raises(OSError, match="power loss"):
                manager.install_entitlement_lease(
                    _lease(
                        signing_key,
                        device_id=manager.get_device_id(),
                    )
                )
        restarted = LicenseManager(lease_verifier=verifier)

    assert manager._lease_marker_file.is_file()
    assert manager._license_file.is_file()
    assert not manager._lease_file.exists()
    assert restarted._license_data is None
    assert restarted.get_license_info().status is LicenseStatus.INVALID


def test_missing_adopted_lease_invalidates_in_memory_claims(
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
        manager.install_entitlement_lease(
            _lease(
                signing_key,
                device_id=manager.get_device_id(),
                issued_at=now,
                expires_at=now + timedelta(days=7),
            ),
            now=now,
        )
        assert manager.get_license_info().status is LicenseStatus.VALID
        manager._lease_file.unlink()

        info = manager.get_license_info()

    assert info.status is LicenseStatus.INVALID
    assert manager._lease_claims is None
    assert manager._lease_error_code == "ENTITLEMENT_REQUIRED"


def test_online_lease_keeps_legacy_cloud_credential_until_session_cutover(
    tmp_path,
    signing_key: Ed25519PrivateKey,
    verifier: EntitlementLeaseVerifier,
) -> None:
    from app.licensing.key_validator import KeyValidator, generate_license_key
    from app.licensing.license_manager import (
        LicenseManager,
        ValidationResult,
    )

    data_dir = tmp_path / "MindType"
    key = generate_license_key()
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
        response = {
            "valid": True,
            "entitlementLease": _lease(
                signing_key,
                device_id=manager.get_device_id(),
            ),
            "plan": "personal",
        }
        with patch.object(
            manager,
            "_make_api_request",
            return_value=(response, None),
        ):
            result, _message, _data = manager.activate_online(key)
        restarted = LicenseManager(lease_verifier=verifier)

    assert result is ValidationResult.SUCCESS
    assert restarted.get_license_info().license_key == KeyValidator.format_key(
        key
    )
    assert restarted._license_file.is_file()
    assert restarted._lease_file.is_file()


def test_lease_revalidation_is_due_before_offline_expiry(
    tmp_path,
    signing_key: Ed25519PrivateKey,
    verifier: EntitlementLeaseVerifier,
) -> None:
    from app.licensing.license_manager import LicenseManager

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
        manager.install_entitlement_lease(
            _lease(
                signing_key,
                device_id=manager.get_device_id(),
                issued_at=now - timedelta(days=6, minutes=1),
                expires_at=now + timedelta(hours=23, minutes=59),
            )
        )
        manager._license_data = {
            "license_key": "ABCDEFGHJKMNPQRS",
            "validated_at": (now - timedelta(days=6, minutes=1))
            .replace(tzinfo=None)
            .isoformat(),
        }

    assert manager.needs_revalidation() is True


def test_hybrid_lease_honors_configured_revalidation_interval(
    tmp_path,
    signing_key: Ed25519PrivateKey,
    verifier: EntitlementLeaseVerifier,
) -> None:
    from app.licensing.license_manager import LicenseManager

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
        patch("app.env.LICENSE_REVALIDATION_INTERVAL", 86400),
    ):
        manager = LicenseManager(lease_verifier=verifier)
        manager.install_entitlement_lease(
            _lease(
                signing_key,
                device_id=manager.get_device_id(),
                issued_at=now,
                expires_at=now + timedelta(days=7),
            )
        )
        manager._license_data = {
            "license_key": "ABCDEFGHJKMNPQRS",
            "validated_at": (now - timedelta(days=2))
            .replace(tzinfo=None)
            .isoformat(),
        }

        assert manager.needs_revalidation() is True


def test_lease_only_activation_renews_before_expiry(
    tmp_path,
    signing_key: Ed25519PrivateKey,
    verifier: EntitlementLeaseVerifier,
) -> None:
    from app.licensing.license_manager import LicenseManager, ValidationResult

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
        manager.install_entitlement_lease(
            _lease(
                signing_key,
                device_id=manager.get_device_id(),
                issued_at=now - timedelta(days=6, minutes=1),
                expires_at=now + timedelta(hours=23, minutes=59),
            )
        )
        renewals = []

        def renew() -> None:
            renewals.append("renewed")
            manager.install_entitlement_lease(
                _lease(
                    signing_key,
                    device_id=manager.get_device_id(),
                    issued_at=now,
                    expires_at=now + timedelta(days=7),
                )
            )

        manager.set_entitlement_renewer(renew)

        assert manager.needs_revalidation() is True
        assert manager.revalidate_if_needed() is ValidationResult.SUCCESS

    assert renewals == ["renewed"]
    assert manager.needs_revalidation() is False


def test_seen_lease_without_legacy_cache_attempts_session_renewal(
    tmp_path,
    signing_key: Ed25519PrivateKey,
    verifier: EntitlementLeaseVerifier,
) -> None:
    from app.licensing.license_manager import LicenseManager, ValidationResult

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
        manager.install_entitlement_lease(
            _lease(
                signing_key,
                device_id=manager.get_device_id(),
                issued_at=now,
                expires_at=now + timedelta(days=7),
            )
        )
        manager._lease_claims = None
        renew = MagicMock()
        manager.set_entitlement_renewer(renew)

        assert manager.needs_revalidation() is True
        assert manager.revalidate_if_needed() is ValidationResult.SUCCESS

    renew.assert_called_once_with()


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
