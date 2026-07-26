"""Verification and durable storage for server-signed entitlement leases."""

from __future__ import annotations

import base64
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key


LEASE_CLAIM_VERSION = 1
LEASE_MAX_DURATION = timedelta(days=7)
LEASE_CLOCK_SKEW = timedelta(minutes=5)


class LeaseValidationError(ValueError):
    """A signed lease cannot be trusted or used by this desktop client."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class EntitlementClaims:
    claim_version: int
    issuer: str
    audience: str
    account_id: str
    device_id: str
    issued_at: datetime
    expires_at: datetime
    plan: str
    features: tuple[str, ...]
    limits: Mapping[str, Any]


def _decode_base64url(value: str, *, field: str) -> bytes:
    if not value:
        raise LeaseValidationError("MALFORMED_LEASE", f"{field} is empty")
    try:
        padding = "=" * (-len(value) % 4)
        return base64.b64decode(
            value + padding,
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, TypeError) as exc:
        raise LeaseValidationError(
            "MALFORMED_LEASE",
            f"{field} is not valid base64url",
        ) from exc


def _required_string(payload: Mapping[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        raise LeaseValidationError(
            "MALFORMED_CLAIMS",
            f"{name} must be a non-empty string",
        )
    return value


def _timestamp(payload: Mapping[str, Any], name: str) -> datetime:
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LeaseValidationError(
            "MALFORMED_CLAIMS",
            f"{name} must be a Unix timestamp",
        )
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise LeaseValidationError(
            "MALFORMED_CLAIMS",
            f"{name} is outside the supported range",
        ) from exc


class EntitlementLeaseVerifier:
    """Verify compact Ed25519 leases issued by MindType Cloud."""

    def __init__(
        self,
        public_key: str | bytes,
        *,
        issuer: str = "mindtype.space",
        audience: str = "mindtype-desktop",
    ):
        self._public_key = self._load_public_key(public_key)
        self._issuer = issuer
        self._audience = audience

    @staticmethod
    def _load_public_key(value: str | bytes) -> Ed25519PublicKey:
        encoded = value.encode("ascii") if isinstance(value, str) else value
        try:
            if encoded.lstrip().startswith(b"-----BEGIN"):
                key = load_pem_public_key(encoded)
                if not isinstance(key, Ed25519PublicKey):
                    raise TypeError("public key is not Ed25519")
                return key
            return Ed25519PublicKey.from_public_bytes(
                _decode_base64url(encoded.decode("ascii"), field="public key")
            )
        except LeaseValidationError:
            raise
        except (TypeError, ValueError, UnicodeError) as exc:
            raise LeaseValidationError(
                "INVALID_PUBLIC_KEY",
                "entitlement public key is invalid",
            ) from exc

    def verify(
        self,
        token: str,
        *,
        device_id: str,
        now: datetime | None = None,
    ) -> EntitlementClaims:
        if not isinstance(token, str) or token.count(".") != 1:
            raise LeaseValidationError(
                "MALFORMED_LEASE",
                "lease must contain payload and signature",
            )
        encoded_payload, encoded_signature = token.split(".", 1)
        payload_bytes = _decode_base64url(
            encoded_payload,
            field="lease payload",
        )
        signature = _decode_base64url(
            encoded_signature,
            field="lease signature",
        )
        try:
            self._public_key.verify(
                signature,
                encoded_payload.encode("ascii"),
            )
        except InvalidSignature as exc:
            raise LeaseValidationError(
                "INVALID_SIGNATURE",
                "lease signature is invalid",
            ) from exc

        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LeaseValidationError(
                "MALFORMED_CLAIMS",
                "lease payload is not valid JSON",
            ) from exc
        if not isinstance(payload, dict):
            raise LeaseValidationError(
                "MALFORMED_CLAIMS",
                "lease payload must be an object",
            )

        version = payload.get("claim_version")
        if version != LEASE_CLAIM_VERSION:
            raise LeaseValidationError(
                "SCHEMA_UNSUPPORTED",
                "lease claim version is not supported",
            )
        issuer = _required_string(payload, "iss")
        audience = _required_string(payload, "aud")
        if issuer != self._issuer or audience != self._audience:
            raise LeaseValidationError(
                "CLAIM_DESTINATION_MISMATCH",
                "lease issuer or audience does not match this client",
            )
        claimed_device_id = _required_string(payload, "device_id")
        if claimed_device_id != device_id:
            raise LeaseValidationError(
                "DEVICE_MISMATCH",
                "lease belongs to another device",
            )

        issued_at = _timestamp(payload, "iat")
        expires_at = _timestamp(payload, "exp")
        if expires_at <= issued_at:
            raise LeaseValidationError(
                "MALFORMED_CLAIMS",
                "lease expiry must be after issuance",
            )
        if expires_at - issued_at > LEASE_MAX_DURATION:
            raise LeaseValidationError(
                "LEASE_TOO_LONG",
                "lease exceeds the seven-day offline allowance",
            )
        checked_at = now or datetime.now(timezone.utc)
        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=timezone.utc)
        else:
            checked_at = checked_at.astimezone(timezone.utc)
        if issued_at > checked_at + LEASE_CLOCK_SKEW:
            raise LeaseValidationError(
                "LEASE_NOT_YET_VALID",
                "lease issuance time is in the future",
            )
        if expires_at <= checked_at:
            raise LeaseValidationError(
                "ENTITLEMENT_EXPIRED",
                "offline entitlement lease has expired",
            )

        raw_features = payload.get("features", [])
        raw_limits = payload.get("limits", {})
        if (
            not isinstance(raw_features, list)
            or not all(isinstance(item, str) for item in raw_features)
            or not isinstance(raw_limits, dict)
        ):
            raise LeaseValidationError(
                "MALFORMED_CLAIMS",
                "features and limits have invalid types",
            )
        return EntitlementClaims(
            claim_version=version,
            issuer=issuer,
            audience=audience,
            account_id=_required_string(payload, "sub"),
            device_id=claimed_device_id,
            issued_at=issued_at,
            expires_at=expires_at,
            plan=_required_string(payload, "plan"),
            features=tuple(raw_features),
            limits=MappingProxyType(dict(raw_limits)),
        )


class EntitlementLeaseStore:
    """Store only leases that verify for the current device."""

    def __init__(
        self,
        path: Path,
        verifier: EntitlementLeaseVerifier,
        *,
        device_id: str,
    ):
        self.path = path
        self._verifier = verifier
        self._device_id = device_id

    def load(self, *, now: datetime | None = None) -> EntitlementClaims:
        token = self.path.read_text(encoding="utf-8")
        return self._verifier.verify(
            token,
            device_id=self._device_id,
            now=now,
        )

    def save(
        self,
        token: str,
        *,
        now: datetime | None = None,
    ) -> EntitlementClaims:
        claims = self._verifier.verify(
            token,
            device_id=self._device_id,
            now=now,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=self.path.parent,
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(token)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self.path)
        finally:
            temporary_path.unlink(missing_ok=True)
        return claims

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
