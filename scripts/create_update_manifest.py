"""Create the signed, installer-bound Windows update manifest."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.update_manifest import verify_update_manifest


def _decode_base64url(value: str, *, field: str) -> bytes:
    if not value:
        raise ValueError(f"{field} is required")
    try:
        return base64.b64decode(
            value + "=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} is not valid base64url") from exc


def _encode_base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def create_signed_update_envelope(
    *,
    installer: Path,
    private_key: str,
    channel: str,
    version: str,
    minimum_supported_version: str,
    url: str,
    rollout_percentage: int,
    authenticode_signer: str,
    published_at: datetime | None = None,
    release_notes: str = "",
) -> dict[str, Any]:
    artifact = Path(installer)
    content = artifact.read_bytes()
    signing_key = Ed25519PrivateKey.from_private_bytes(
        _decode_base64url(private_key, field="update private key")
    )
    timestamp = published_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise ValueError("published_at must include a timezone")
    manifest = {
        "schema_version": "1.0",
        "channel": channel,
        "version": version,
        "platform": "windows",
        "architecture": "x86_64",
        "minimum_supported_version": minimum_supported_version,
        "url": url,
        "sha256": hashlib.sha256(content).hexdigest(),
        "size": len(content),
        "published_at": timestamp.astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "rollout_percentage": rollout_percentage,
        "authenticode_signer": authenticode_signer,
        "release_notes": release_notes,
    }
    signature = signing_key.sign(_canonical_json(manifest))
    return {
        "manifest": manifest,
        "signature": _encode_base64url(signature),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--channel", default="stable")
    parser.add_argument("--version", required=True)
    parser.add_argument("--minimum-supported-version", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--rollout-percentage", type=int, default=10)
    parser.add_argument("--authenticode-signer", required=True)
    parser.add_argument("--release-notes", default="")
    parser.add_argument(
        "--private-key-env",
        default="MINDTYPE_UPDATE_PRIVATE_KEY",
    )
    parser.add_argument(
        "--public-key-env",
        default="MINDTYPE_UPDATE_PUBLIC_KEY",
    )
    args = parser.parse_args()

    private_key = os.environ.get(args.private_key_env, "")
    public_key = os.environ.get(args.public_key_env, "")
    if not private_key or not public_key:
        raise SystemExit("update signing keys are required")
    envelope = create_signed_update_envelope(
        installer=args.installer,
        private_key=private_key,
        channel=args.channel,
        version=args.version,
        minimum_supported_version=args.minimum_supported_version,
        url=args.url,
        rollout_percentage=args.rollout_percentage,
        authenticode_signer=args.authenticode_signer,
        release_notes=args.release_notes,
    )
    release_hostname = urlparse(args.url).hostname
    if not release_hostname:
        raise SystemExit("update URL has no hostname")
    verify_update_manifest(
        envelope,
        public_key=public_key,
        expected_channel=args.channel,
        expected_platform="windows",
        expected_architecture="x86_64",
        expected_signer=args.authenticode_signer,
        allowed_hosts={release_hostname},
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
