import base64

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from scripts.embed_release_trust_root import (
    embed_public_key,
    read_embedded_public_key,
    validate_public_key,
)


def _public_key() -> str:
    raw = Ed25519PrivateKey.generate().public_key().public_bytes(
        Encoding.Raw,
        PublicFormat.Raw,
    )
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def test_embed_release_trust_root_round_trip(tmp_path):
    target = tmp_path / "trust_root.py"
    target.write_text(
        '"""generated"""\n\nLICENSE_ED25519_PUBLIC_KEY = ""\n',
        encoding="utf-8",
    )
    key = _public_key()

    embed_public_key(key, target)

    assert read_embedded_public_key(target) == key
    assert validate_public_key(read_embedded_public_key(target)) == key


def test_invalid_key_does_not_replace_existing_trust_root(tmp_path):
    target = tmp_path / "trust_root.py"
    target.write_text(
        'LICENSE_ED25519_PUBLIC_KEY = "existing"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        embed_public_key("attacker-key", target)

    assert read_embedded_public_key(target) == "existing"
