from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def signed_lease(
    private_key: Ed25519PrivateKey,
    *,
    device_id: str,
    now: datetime,
) -> str:
    payload = {
        "claim_version": 1,
        "iss": "mindtype.space",
        "aud": "mindtype-desktop",
        "sub": "account-1",
        "device_id": device_id,
        "iat": now.timestamp(),
        "exp": (now + timedelta(days=7)).timestamp(),
        "plan": "personal",
        "features": ["local", "cloud"],
        "limits": {"cloud_seconds": 3600},
    }
    encoded = b64url(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    return f"{encoded}.{b64url(private_key.sign(encoded.encode('ascii')))}"


class FakeRefreshStore:
    def __init__(self) -> None:
        self.token = None
        self.calls = []

    def save(self, device_id: str, token: str) -> None:
        self.calls.append(("save", device_id, token))
        self.token = token

    def load(self, device_id: str):
        self.calls.append(("load", device_id))
        return self.token

    def clear(self, device_id: str) -> None:
        self.calls.append(("clear", device_id))
        self.token = None


class FakeSessionClient:
    def __init__(self, response=None, error=None) -> None:
        self.response = response
        self.error = error
        self.calls = []

    def create_session(self, **request):
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return self.response


class ScriptedTransport:
    def __init__(self, response=None, error=None) -> None:
        self.response = response
        self.error = error
        self.requests = []

    def request(self, method, url, *, headers, body, timeout):
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "body": body,
                "timeout": timeout,
            }
        )
        if self.error is not None:
            raise self.error
        return self.response


def session_manager(
    tmp_path: Path,
    *,
    private_key: Ed25519PrivateKey,
    client,
    refresh_store,
    device_id: str,
):
    from app.licensing.entitlement import (
        EntitlementLeaseStore,
        EntitlementLeaseVerifier,
    )
    from app.licensing.session import CloudSessionManager

    public = private_key.public_key().public_bytes(
        Encoding.Raw,
        PublicFormat.Raw,
    )
    lease_store = EntitlementLeaseStore(
        tmp_path / "entitlement.lease",
        EntitlementLeaseVerifier(b64url(public)),
        device_id=device_id,
    )
    return CloudSessionManager(
        client=client,
        lease_store=lease_store,
        refresh_store=refresh_store,
        device_id=device_id,
    )


def test_session_adopts_verified_lease_and_keeps_access_token_in_memory(
    tmp_path: Path,
) -> None:
    from app.licensing.session import LicenseSession

    now = datetime.now(timezone.utc)
    private_key = Ed25519PrivateKey.generate()
    device_id = "device-hash"
    response = LicenseSession(
        access_token="access-token",
        access_expires_at=now + timedelta(minutes=15),
        refresh_token="refresh-token",
        entitlement_lease=signed_lease(
            private_key,
            device_id=device_id,
            now=now,
        ),
        claim_version=1,
    )
    client = FakeSessionClient(response=response)
    refresh_store = FakeRefreshStore()
    manager = session_manager(
        tmp_path,
        private_key=private_key,
        client=client,
        refresh_store=refresh_store,
        device_id=device_id,
    )

    claims = manager.activate(
        license_key="MT-AAAA-BBBB-CCCC",
        desktop_version="0.9.3",
        platform="windows",
        now=now,
    )

    assert claims.device_id == device_id
    assert manager.access_token(now=now) == "access-token"
    assert refresh_store.token == "refresh-token"
    assert (tmp_path / "entitlement.lease").is_file()
    assert client.calls == [
        {
            "license_key": "MT-AAAA-BBBB-CCCC",
            "device_id_hash": device_id,
            "desktop_version": "0.9.3",
            "platform": "windows",
        }
    ]
    assert "access-token" not in (
        tmp_path / "entitlement.lease"
    ).read_text(encoding="utf-8")


def test_invalid_lease_rolls_back_refresh_token(tmp_path: Path) -> None:
    from app.licensing.entitlement import LeaseValidationError
    from app.licensing.session import LicenseSession

    now = datetime.now(timezone.utc)
    private_key = Ed25519PrivateKey.generate()
    response = LicenseSession(
        access_token="access-token",
        access_expires_at=now + timedelta(minutes=15),
        refresh_token="refresh-token",
        entitlement_lease="invalid.lease",
        claim_version=1,
    )
    refresh_store = FakeRefreshStore()
    manager = session_manager(
        tmp_path,
        private_key=private_key,
        client=FakeSessionClient(response=response),
        refresh_store=refresh_store,
        device_id="device-hash",
    )

    with pytest.raises(LeaseValidationError):
        manager.activate(
            license_key="MT-AAAA-BBBB-CCCC",
            desktop_version="0.9.3",
            platform="windows",
            now=now,
        )

    assert refresh_store.token is None
    assert not (tmp_path / "entitlement.lease").exists()


def test_authoritative_negative_clears_cached_session_and_lease(
    tmp_path: Path,
) -> None:
    from app.licensing.session import (
        LicenseSession,
        LicenseSessionError,
    )

    now = datetime.now(timezone.utc)
    private_key = Ed25519PrivateKey.generate()
    device_id = "device-hash"
    refresh_store = FakeRefreshStore()
    initial = LicenseSession(
        access_token="access-token",
        access_expires_at=now + timedelta(minutes=15),
        refresh_token="refresh-token",
        entitlement_lease=signed_lease(
            private_key,
            device_id=device_id,
            now=now,
        ),
        claim_version=1,
    )
    client = FakeSessionClient(response=initial)
    manager = session_manager(
        tmp_path,
        private_key=private_key,
        client=client,
        refresh_store=refresh_store,
        device_id=device_id,
    )
    manager.activate(
        license_key="MT-AAAA-BBBB-CCCC",
        desktop_version="0.9.3",
        platform="windows",
        now=now,
    )
    client.error = LicenseSessionError(
        "ENTITLEMENT_EXPIRED",
        "expired",
        retryable=False,
        authoritative=True,
    )

    with pytest.raises(LicenseSessionError):
        manager.activate(
            license_key="MT-AAAA-BBBB-CCCC",
            desktop_version="0.9.3",
            platform="windows",
            now=now,
        )

    assert refresh_store.token is None
    assert not (tmp_path / "entitlement.lease").exists()
    assert manager.access_token(now=now) is None


def test_network_error_preserves_existing_offline_lease(tmp_path: Path) -> None:
    from app.licensing.session import (
        LicenseSession,
        LicenseSessionError,
    )

    now = datetime.now(timezone.utc)
    private_key = Ed25519PrivateKey.generate()
    device_id = "device-hash"
    refresh_store = FakeRefreshStore()
    initial = LicenseSession(
        access_token="access-token",
        access_expires_at=now + timedelta(minutes=15),
        refresh_token="refresh-token",
        entitlement_lease=signed_lease(
            private_key,
            device_id=device_id,
            now=now,
        ),
        claim_version=1,
    )
    client = FakeSessionClient(response=initial)
    manager = session_manager(
        tmp_path,
        private_key=private_key,
        client=client,
        refresh_store=refresh_store,
        device_id=device_id,
    )
    manager.activate(
        license_key="MT-AAAA-BBBB-CCCC",
        desktop_version="0.9.3",
        platform="windows",
        now=now,
    )
    client.error = LicenseSessionError(
        "PROVIDER_UNAVAILABLE",
        "offline",
        retryable=True,
        authoritative=False,
    )

    with pytest.raises(LicenseSessionError):
        manager.activate(
            license_key="MT-AAAA-BBBB-CCCC",
            desktop_version="0.9.3",
            platform="windows",
            now=now,
        )

    assert refresh_store.token == "refresh-token"
    assert (tmp_path / "entitlement.lease").is_file()
    assert manager.access_token(now=now) == "access-token"


def test_missing_refresh_token_preserves_valid_offline_lease(
    tmp_path: Path,
) -> None:
    from app.licensing.session import (
        LicenseSession,
        LicenseSessionError,
    )

    now = datetime.now(timezone.utc)
    private_key = Ed25519PrivateKey.generate()
    device_id = "device-hash"
    refresh_store = FakeRefreshStore()
    manager = session_manager(
        tmp_path,
        private_key=private_key,
        client=FakeSessionClient(
            response=LicenseSession(
                access_token="access-token",
                access_expires_at=now + timedelta(minutes=15),
                refresh_token="refresh-token",
                entitlement_lease=signed_lease(
                    private_key,
                    device_id=device_id,
                    now=now,
                ),
                claim_version=1,
            )
        ),
        refresh_store=refresh_store,
        device_id=device_id,
    )
    manager.activate(
        license_key="MT-AAAA-BBBB-CCCC",
        desktop_version="0.9.3",
        platform="windows",
        now=now,
    )
    refresh_store.token = None

    with pytest.raises(LicenseSessionError) as exc:
        manager.refresh_access_token(now=now + timedelta(minutes=16))

    assert exc.value.code == "AUTH_REQUIRED"
    assert exc.value.authoritative is False
    assert manager.access_token(now=now + timedelta(minutes=16)) is None
    assert (tmp_path / "entitlement.lease").is_file()
    assert manager.lease_store.load(
        now=now + timedelta(minutes=16)
    ).device_id == device_id


def test_invalid_rotated_lease_preserves_prior_lease_and_refresh_token(
    tmp_path: Path,
) -> None:
    from app.licensing.entitlement import LeaseValidationError
    from app.licensing.session import LicenseSession

    now = datetime.now(timezone.utc)
    private_key = Ed25519PrivateKey.generate()
    device_id = "device-hash"
    initial = LicenseSession(
        access_token="access-token",
        access_expires_at=now + timedelta(minutes=15),
        refresh_token="refresh-token",
        entitlement_lease=signed_lease(
            private_key,
            device_id=device_id,
            now=now,
        ),
        claim_version=1,
    )
    refresh_store = FakeRefreshStore()
    client = FakeSessionClient(response=initial)
    manager = session_manager(
        tmp_path,
        private_key=private_key,
        client=client,
        refresh_store=refresh_store,
        device_id=device_id,
    )
    manager.activate(
        license_key="MT-AAAA-BBBB-CCCC",
        desktop_version="0.9.3",
        platform="windows",
        now=now,
    )
    prior_lease = (tmp_path / "entitlement.lease").read_text(
        encoding="utf-8"
    )
    client.refresh_session = lambda **_request: LicenseSession(
        access_token="rotated-access",
        access_expires_at=now + timedelta(minutes=31),
        refresh_token="rotated-refresh",
        entitlement_lease="invalid.lease",
        claim_version=1,
    )

    with pytest.raises(LeaseValidationError):
        manager.refresh_access_token(now=now + timedelta(minutes=16))

    assert refresh_store.token == "rotated-refresh"
    assert (tmp_path / "entitlement.lease").read_text(
        encoding="utf-8"
    ) == prior_lease
    assert manager.lease_store.load(
        now=now + timedelta(minutes=16)
    ).device_id == device_id


def test_keyring_refresh_store_never_falls_back_to_plaintext() -> None:
    from app.licensing.session import (
        CredentialStoreError,
        KeyringRefreshTokenStore,
    )

    class BrokenKeyring:
        def set_password(self, *_args):
            raise RuntimeError("credential manager unavailable")

        def get_password(self, *_args):
            raise RuntimeError("credential manager unavailable")

        def delete_password(self, *_args):
            raise RuntimeError("credential manager unavailable")

    store = KeyringRefreshTokenStore(keyring_backend=BrokenKeyring())

    with pytest.raises(CredentialStoreError):
        store.save("device-hash", "secret-refresh-token")
    with pytest.raises(CredentialStoreError):
        store.load("device-hash")


def test_session_client_uses_declared_endpoint_and_parses_short_lived_token():
    from app.licensing.session import LicenseSessionClient
    from app.providers.mindtype_cloud import HTTPResponse

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    transport = ScriptedTransport(
        response=HTTPResponse(
            status=200,
            headers={},
            body=json.dumps(
                {
                    "access_token": "access",
                    "access_expires_at": expires_at.isoformat(),
                    "refresh_token": "refresh",
                    "entitlement_lease": "lease.signature",
                    "claim_version": 1,
                }
            ).encode("utf-8"),
        )
    )
    client = LicenseSessionClient(
        "https://mindtype.space",
        transport=transport,
    )

    session = client.create_session(
        license_key="MT-AAAA-BBBB-CCCC",
        device_id_hash="device-hash",
        desktop_version="0.9.3",
        platform="windows",
    )

    request = transport.requests[0]
    assert request["method"] == "POST"
    assert request["url"] == "https://mindtype.space/api/license/session"
    assert json.loads(request["body"]) == {
        "license_key": "MT-AAAA-BBBB-CCCC",
        "device_id_hash": "device-hash",
        "desktop_version": "0.9.3",
        "platform": "windows",
    }
    assert session.access_token == "access"


def test_session_client_preserves_authoritative_negative() -> None:
    from app.licensing.session import (
        LicenseSessionClient,
        LicenseSessionError,
    )
    from app.providers.mindtype_cloud import HTTPResponse

    transport = ScriptedTransport(
        response=HTTPResponse(
            status=403,
            headers={},
            body=json.dumps(
                {
                    "error": {
                        "code": "ENTITLEMENT_EXPIRED",
                        "message": "expired",
                        "retryable": False,
                        "authoritative": True,
                    }
                }
            ).encode("utf-8"),
        )
    )
    client = LicenseSessionClient(
        "https://mindtype.space",
        transport=transport,
    )

    with pytest.raises(LicenseSessionError) as raised:
        client.create_session(
            license_key="MT-AAAA-BBBB-CCCC",
            device_id_hash="device-hash",
            desktop_version="0.9.3",
            platform="windows",
        )

    assert raised.value.code == "ENTITLEMENT_EXPIRED"
    assert raised.value.authoritative is True
    assert raised.value.retryable is False


def test_session_client_network_failure_is_not_authoritative() -> None:
    from app.licensing.session import (
        LicenseSessionClient,
        LicenseSessionError,
    )
    from app.providers.mindtype_cloud import TransportError

    client = LicenseSessionClient(
        "https://mindtype.space",
        transport=ScriptedTransport(error=TransportError("offline")),
    )

    with pytest.raises(LicenseSessionError) as raised:
        client.create_session(
            license_key="MT-AAAA-BBBB-CCCC",
            device_id_hash="device-hash",
            desktop_version="0.9.3",
            platform="windows",
        )

    assert raised.value.code == "PROVIDER_UNAVAILABLE"
    assert raised.value.authoritative is False
    assert raised.value.retryable is True


def test_session_client_rotates_refresh_token_without_license_key() -> None:
    from app.licensing.session import LicenseSessionClient
    from app.providers.mindtype_cloud import HTTPResponse

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    transport = ScriptedTransport(
        response=HTTPResponse(
            status=200,
            headers={},
            body=json.dumps(
                {
                    "access_token": "new-access",
                    "access_expires_at": expires_at.isoformat(),
                    "refresh_token": "new-refresh",
                    "entitlement_lease": "lease.signature",
                    "claim_version": 1,
                }
            ).encode("utf-8"),
        )
    )
    client = LicenseSessionClient(
        "https://mindtype.space",
        transport=transport,
    )

    session = client.refresh_session(refresh_token="old-refresh")

    request = transport.requests[0]
    assert request["url"].endswith("/api/license/session/refresh")
    assert json.loads(request["body"]) == {"refresh_token": "old-refresh"}
    assert session.access_token == "new-access"
    assert session.refresh_token == "new-refresh"


def test_manager_refresh_rotates_credential_and_access_token(
    tmp_path: Path,
) -> None:
    from app.licensing.session import LicenseSession

    now = datetime.now(timezone.utc)
    private_key = Ed25519PrivateKey.generate()
    device_id = "device-hash"
    refresh_store = FakeRefreshStore()
    refresh_store.token = "old-refresh"
    response = LicenseSession(
        access_token="new-access",
        access_expires_at=now + timedelta(minutes=15),
        refresh_token="new-refresh",
        entitlement_lease=signed_lease(
            private_key,
            device_id=device_id,
            now=now,
        ),
        claim_version=1,
    )
    client = FakeSessionClient(response=response)
    client.refresh_session = lambda **request: (
        client.calls.append(request) or response
    )
    manager = session_manager(
        tmp_path,
        private_key=private_key,
        client=client,
        refresh_store=refresh_store,
        device_id=device_id,
    )

    manager.refresh_access_token(now=now)

    assert client.calls == [{"refresh_token": "old-refresh"}]
    assert refresh_store.token == "new-refresh"
    assert manager.access_token(now=now) == "new-access"


def test_concurrent_refreshes_share_one_rotated_session(
    tmp_path: Path,
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from app.licensing.session import LicenseSession

    now = datetime.now(timezone.utc)
    private_key = Ed25519PrivateKey.generate()
    device_id = "device-hash"
    refresh_store = FakeRefreshStore()
    refresh_store.token = "old-refresh"
    response = LicenseSession(
        access_token="new-access",
        access_expires_at=now + timedelta(minutes=15),
        refresh_token="new-refresh",
        entitlement_lease=signed_lease(
            private_key,
            device_id=device_id,
            now=now,
        ),
        claim_version=1,
    )
    entered = Event()
    release = Event()
    client = FakeSessionClient()

    def refresh_session(**request):
        client.calls.append(request)
        entered.set()
        assert release.wait(timeout=2)
        return response

    client.refresh_session = refresh_session
    manager = session_manager(
        tmp_path,
        private_key=private_key,
        client=client,
        refresh_store=refresh_store,
        device_id=device_id,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(manager.refresh_access_token, now=now)
        assert entered.wait(timeout=2)
        second = executor.submit(manager.refresh_access_token, now=now)
        release.set()
        first_claims = first.result(timeout=2)
        second_claims = second.result(timeout=2)

    assert client.calls == [{"refresh_token": "old-refresh"}]
    assert first_claims == second_claims
    assert refresh_store.token == "new-refresh"
    assert manager.access_token(now=now) == "new-access"
