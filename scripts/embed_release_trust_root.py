"""Validate and embed the entitlement public key for a frozen release."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = ROOT / "app" / "release_trust_root.py"
ASSIGNMENT = re.compile(
    r'^LICENSE_ED25519_PUBLIC_KEY = "(?P<key>[^"]*)"$',
    re.MULTILINE,
)


def validate_public_key(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("MINDTYPE_LICENSE_PUBLIC_KEY is required")
    try:
        raw = base64.b64decode(
            value + "=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
        Ed25519PublicKey.from_public_bytes(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError(
            "MINDTYPE_LICENSE_PUBLIC_KEY must be a base64url Ed25519 public key"
        ) from exc
    return value


def read_embedded_public_key(target: Path = DEFAULT_TARGET) -> str:
    match = ASSIGNMENT.search(target.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(f"trust-root assignment not found in {target}")
    return match.group("key")


def embed_public_key(value: str, target: Path = DEFAULT_TARGET) -> None:
    key = validate_public_key(value)
    current = target.read_text(encoding="utf-8")
    if ASSIGNMENT.search(current) is None:
        raise ValueError(f"trust-root assignment not found in {target}")
    rendered = ASSIGNMENT.sub(
        f"LICENSE_ED25519_PUBLIC_KEY = {json.dumps(key)}",
        current,
        count=1,
    )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    args = parser.parse_args()
    if args.check:
        validate_public_key(read_embedded_public_key(args.target))
        return 0
    embed_public_key(
        os.environ.get("MINDTYPE_LICENSE_PUBLIC_KEY", ""),
        args.target,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
