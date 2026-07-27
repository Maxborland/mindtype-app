"""Short-lived cloud session boundary for desktop licensing."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional, Protocol
from urllib.parse import urlparse

from .entitlement import EntitlementClaims, EntitlementLeaseStore
from ..providers.mindtype_cloud import (
    HTTPTransport,
    ResponseTooLargeError,
    TransportError,
    UrlLibTransport,
)


class LicenseSessionError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        authoritative: bool,
    ) -> None:
        super().__init__(message or code)
        self.code = code
        self.retryable = retryable
        self.authoritative = authoritative


class CredentialStoreError(RuntimeError):
    """Windows Credential Manager could not safely store session material."""


@dataclass(frozen=True)
class LicenseSession:
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    entitlement_lease: str
    claim_version: int


class RefreshTokenStore(Protocol):
    def save(self, device_id: str, token: str) -> None: ...

    def load(self, device_id: str) -> Optional[str]: ...

    def clear(self, device_id: str) -> None: ...


class EntitlementLeaseInstaller(Protocol):
    def __call__(
        self,
        token: str,
        *,
        now: Optional[datetime] = None,
    ) -> EntitlementClaims: ...


class KeyringRefreshTokenStore:
    """Store refresh tokens only in the OS credential backend."""

    SERVICE = "MindType Cloud"

    def __init__(self, *, keyring_backend: Optional[object] = None) -> None:
        if keyring_backend is None:
            try:
                import keyring

                backend = keyring.get_keyring()
            except Exception as exc:
                raise CredentialStoreError(
                    "Windows Credential Manager is unavailable"
                ) from exc
            backend_module = type(backend).__module__
            if not backend_module.startswith("keyring.backends.Windows"):
                raise CredentialStoreError(
                    "refresh tokens require the Windows keyring backend"
                )
            self._keyring = keyring
        else:
            self._keyring = keyring_backend

    @staticmethod
    def _account(device_id: str) -> str:
        if not device_id:
            raise CredentialStoreError("device ID is missing")
        return f"refresh:{device_id}"

    def save(self, device_id: str, token: str) -> None:
        if not token:
            raise CredentialStoreError("refresh token is missing")
        try:
            self._keyring.set_password(
                self.SERVICE,
                self._account(device_id),
                token,
            )
        except Exception as exc:
            raise CredentialStoreError(
                "refresh token could not be stored securely"
            ) from exc

    def load(self, device_id: str) -> Optional[str]:
        try:
            token = self._keyring.get_password(
                self.SERVICE,
                self._account(device_id),
            )
        except Exception as exc:
            raise CredentialStoreError(
                "refresh token could not be read securely"
            ) from exc
        return str(token) if token else None

    def clear(self, device_id: str) -> None:
        account = self._account(device_id)
        try:
            if self._keyring.get_password(self.SERVICE, account) is not None:
                self._keyring.delete_password(self.SERVICE, account)
        except Exception as exc:
            raise CredentialStoreError(
                "refresh token could not be cleared"
            ) from exc


class LicenseSessionClient:
    """HTTPS client for POST /api/license/session."""

    def __init__(
        self,
        base_url: str,
        *,
        transport: Optional[HTTPTransport] = None,
        timeout: float = 30,
    ) -> None:
        parsed = urlparse(base_url)
        loopback = parsed.hostname in {"127.0.0.1", "::1", "localhost"}
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and loopback
        ):
            raise ValueError("license session endpoint must use HTTPS")
        if not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("license session base URL is invalid")
        self.base_url = base_url.rstrip("/")
        self.transport = transport or UrlLibTransport()
        self.timeout = timeout

    @staticmethod
    def _payload(response_body: bytes) -> dict[str, Any]:
        try:
            payload = json.loads(response_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LicenseSessionError(
                "SCHEMA_UNSUPPORTED",
                "license session response is not valid JSON",
                retryable=False,
                authoritative=False,
            ) from exc
        if not isinstance(payload, dict):
            raise LicenseSessionError(
                "SCHEMA_UNSUPPORTED",
                "license session response must be an object",
                retryable=False,
                authoritative=False,
            )
        return payload

    @staticmethod
    def _required_string(
        payload: Mapping[str, Any],
        name: str,
    ) -> str:
        value = payload.get(name)
        if not isinstance(value, str) or not value:
            raise LicenseSessionError(
                "SCHEMA_UNSUPPORTED",
                f"license session is missing {name}",
                retryable=False,
                authoritative=False,
            )
        return value

    def create_session(
        self,
        *,
        license_key: str,
        device_id_hash: str,
        desktop_version: str,
        platform: str,
    ) -> LicenseSession:
        body = json.dumps(
            {
                "license_key": license_key,
                "device_id_hash": device_id_hash,
                "desktop_version": desktop_version,
                "platform": platform,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            response = self.transport.request(
                "POST",
                f"{self.base_url}/api/license/session",
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                body=body,
                timeout=self.timeout,
            )
        except ResponseTooLargeError as exc:
            raise LicenseSessionError(
                "SCHEMA_UNSUPPORTED",
                str(exc),
                retryable=False,
                authoritative=False,
            ) from exc
        except TransportError as exc:
            raise LicenseSessionError(
                "PROVIDER_UNAVAILABLE",
                str(exc),
                retryable=True,
                authoritative=False,
            ) from exc
        payload = self._payload(response.body)
        if not 200 <= response.status < 300:
            raw_error = payload.get("error")
            error = raw_error if isinstance(raw_error, Mapping) else {}
            code = str(error.get("code") or f"HTTP_{response.status}")
            authoritative = bool(
                error.get(
                    "authoritative",
                    response.status in {401, 403, 404, 410},
                )
            )
            raise LicenseSessionError(
                code,
                str(error.get("message") or code),
                retryable=bool(
                    error.get(
                        "retryable",
                        response.status == 429 or response.status >= 500,
                    )
                ),
                authoritative=authoritative,
            )

        return self._parse_session_payload(payload)

    def _parse_session_payload(
        self,
        payload: Mapping[str, Any],
    ) -> LicenseSession:
        expires_text = self._required_string(
            payload,
            "access_expires_at",
        )
        try:
            expires_at = datetime.fromisoformat(
                expires_text.replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise LicenseSessionError(
                "SCHEMA_UNSUPPORTED",
                "access_expires_at must be ISO-8601",
                retryable=False,
                authoritative=False,
            ) from exc
        if expires_at.tzinfo is None:
            raise LicenseSessionError(
                "SCHEMA_UNSUPPORTED",
                "access_expires_at must include timezone",
                retryable=False,
                authoritative=False,
            )
        claim_version = payload.get("claim_version")
        if claim_version != 1:
            raise LicenseSessionError(
                "SCHEMA_UNSUPPORTED",
                "license session claim version is unsupported",
                retryable=False,
                authoritative=False,
            )
        return LicenseSession(
            access_token=self._required_string(payload, "access_token"),
            access_expires_at=expires_at.astimezone(timezone.utc),
            refresh_token=self._required_string(payload, "refresh_token"),
            entitlement_lease=self._required_string(
                payload,
                "entitlement_lease",
            ),
            claim_version=claim_version,
        )

    def refresh_session(self, *, refresh_token: str) -> LicenseSession:
        body = json.dumps(
            {"refresh_token": refresh_token},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            response = self.transport.request(
                "POST",
                f"{self.base_url}/api/license/session/refresh",
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                body=body,
                timeout=self.timeout,
            )
        except ResponseTooLargeError as exc:
            raise LicenseSessionError(
                "SCHEMA_UNSUPPORTED",
                str(exc),
                retryable=False,
                authoritative=False,
            ) from exc
        except TransportError as exc:
            raise LicenseSessionError(
                "PROVIDER_UNAVAILABLE",
                str(exc),
                retryable=True,
                authoritative=False,
            ) from exc
        payload = self._payload(response.body)
        if not 200 <= response.status < 300:
            raw_error = payload.get("error")
            error = raw_error if isinstance(raw_error, Mapping) else {}
            code = str(error.get("code") or f"HTTP_{response.status}")
            raise LicenseSessionError(
                code,
                str(error.get("message") or code),
                retryable=bool(
                    error.get(
                        "retryable",
                        response.status == 429 or response.status >= 500,
                    )
                ),
                authoritative=bool(
                    error.get(
                        "authoritative",
                        response.status in {401, 403, 404, 410},
                    )
                ),
            )
        return self._parse_session_payload(payload)

    def deactivate_session(self, *, access_token: str) -> None:
        try:
            response = self.transport.request(
                "POST",
                f"{self.base_url}/api/license/deactivate",
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                body=b"{}",
                timeout=self.timeout,
            )
        except ResponseTooLargeError as exc:
            raise LicenseSessionError(
                "SCHEMA_UNSUPPORTED",
                str(exc),
                retryable=False,
                authoritative=False,
            ) from exc
        except TransportError as exc:
            raise LicenseSessionError(
                "PROVIDER_UNAVAILABLE",
                str(exc),
                retryable=True,
                authoritative=False,
            ) from exc
        payload = self._payload(response.body)
        if not 200 <= response.status < 300:
            raw_error = payload.get("error")
            error = raw_error if isinstance(raw_error, Mapping) else {}
            code = str(error.get("code") or f"HTTP_{response.status}")
            raise LicenseSessionError(
                code,
                str(error.get("message") or code),
                retryable=bool(
                    error.get(
                        "retryable",
                        response.status == 429 or response.status >= 500,
                    )
                ),
                authoritative=bool(
                    error.get(
                        "authoritative",
                        response.status in {401, 403, 404, 410},
                    )
                ),
            )
        if payload.get("success") is not True:
            raise LicenseSessionError(
                "SCHEMA_UNSUPPORTED",
                "license deactivation response is invalid",
                retryable=False,
                authoritative=False,
            )


class CloudSessionManager:
    """Adopt a session without ever persisting access or license keys."""

    def __init__(
        self,
        *,
        client: LicenseSessionClient,
        lease_store: EntitlementLeaseStore,
        install_lease: EntitlementLeaseInstaller,
        refresh_store: RefreshTokenStore,
        device_id: str,
    ) -> None:
        self.client = client
        self.lease_store = lease_store
        self.install_lease = install_lease
        self.refresh_store = refresh_store
        self.device_id = device_id
        self._access_token: Optional[str] = None
        self._access_expires_at: Optional[datetime] = None
        self._claims: Optional[EntitlementClaims] = None
        self._session_lock = threading.RLock()

    def _clear_memory_and_lease(self) -> None:
        self._access_token = None
        self._access_expires_at = None
        self._claims = None
        self.lease_store.clear()

    def _clear_access_token(self) -> None:
        self._access_token = None
        self._access_expires_at = None

    def clear(self) -> None:
        with self._session_lock:
            self._clear_memory_and_lease()
            self.refresh_store.clear(self.device_id)

    def deactivate_remote(self, *, now: Optional[datetime] = None) -> None:
        """Deactivate the current device; local cleanup follows server ACK."""
        with self._session_lock:
            token = self.access_token(now=now)
            if token is None:
                self.refresh_access_token(now=now)
                token = self.access_token(now=now)
            if token is None:
                raise LicenseSessionError(
                    "AUTH_REQUIRED",
                    "cloud access token is unavailable",
                    retryable=False,
                    authoritative=False,
                )
            self.client.deactivate_session(access_token=token)

    def activate(
        self,
        *,
        license_key: str,
        desktop_version: str,
        platform: str,
        now: Optional[datetime] = None,
    ) -> EntitlementClaims:
        checked_at = now or datetime.now(timezone.utc)
        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=timezone.utc)
        else:
            checked_at = checked_at.astimezone(timezone.utc)
        with self._session_lock:
            try:
                session = self.client.create_session(
                    license_key=license_key,
                    device_id_hash=self.device_id,
                    desktop_version=desktop_version,
                    platform=platform,
                )
            except LicenseSessionError as exc:
                if exc.authoritative:
                    self._clear_memory_and_lease()
                    self.refresh_store.clear(self.device_id)
                raise

            preserve_existing = self._claims is not None
            if not preserve_existing:
                try:
                    self.lease_store.load(now=checked_at)
                    preserve_existing = True
                except Exception:
                    pass
            return self._adopt_session(
                session,
                checked_at=checked_at,
                preserve_existing_on_failure=preserve_existing,
            )

    def _adopt_session(
        self,
        session: LicenseSession,
        *,
        checked_at: datetime,
        preserve_existing_on_failure: bool = False,
    ) -> EntitlementClaims:
        expires_at = session.access_expires_at.astimezone(timezone.utc)
        if not checked_at < expires_at <= checked_at + timedelta(minutes=20):
            raise LicenseSessionError(
                "SCHEMA_UNSUPPORTED",
                "access token lifetime is outside the desktop contract",
                retryable=False,
                authoritative=False,
            )

        self.refresh_store.save(self.device_id, session.refresh_token)
        try:
            claims = self.install_lease(
                session.entitlement_lease,
                now=checked_at,
            )
        except Exception:
            if not preserve_existing_on_failure:
                self.refresh_store.clear(self.device_id)
                self._clear_memory_and_lease()
            raise
        self._access_token = session.access_token
        self._access_expires_at = expires_at
        self._claims = claims
        return claims

    def refresh_access_token(
        self,
        *,
        now: Optional[datetime] = None,
        force: bool = False,
    ) -> EntitlementClaims:
        checked_at = now or datetime.now(timezone.utc)
        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=timezone.utc)
        else:
            checked_at = checked_at.astimezone(timezone.utc)
        with self._session_lock:
            if (
                not force
                and self._access_token is not None
                and self._access_expires_at is not None
                and self._access_expires_at
                > checked_at + timedelta(seconds=30)
                and self._claims is not None
            ):
                return self._claims
            refresh_token = self.refresh_store.load(self.device_id)
            if not refresh_token:
                self._clear_access_token()
                raise LicenseSessionError(
                    "AUTH_REQUIRED",
                    "cloud refresh token is missing",
                    retryable=False,
                    authoritative=False,
                )
            try:
                session = self.client.refresh_session(
                    refresh_token=refresh_token,
                )
            except LicenseSessionError as exc:
                if exc.authoritative:
                    self._clear_memory_and_lease()
                    self.refresh_store.clear(self.device_id)
                raise
            return self._adopt_session(
                session,
                checked_at=checked_at,
                preserve_existing_on_failure=True,
            )

    def access_token(
        self,
        *,
        now: Optional[datetime] = None,
    ) -> Optional[str]:
        with self._session_lock:
            if self._access_token is None or self._access_expires_at is None:
                return None
            checked_at = now or datetime.now(timezone.utc)
            if checked_at.tzinfo is None:
                checked_at = checked_at.replace(tzinfo=timezone.utc)
            else:
                checked_at = checked_at.astimezone(timezone.utc)
            if self._access_expires_at <= checked_at + timedelta(seconds=30):
                self._access_token = None
                self._access_expires_at = None
                return None
            return self._access_token


__all__ = [
    "CloudSessionManager",
    "CredentialStoreError",
    "KeyringRefreshTokenStore",
    "LicenseSession",
    "LicenseSessionClient",
    "LicenseSessionError",
    "RefreshTokenStore",
]
