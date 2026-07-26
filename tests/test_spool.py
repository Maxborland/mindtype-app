import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


def test_recording_becomes_durable_only_after_atomic_finalize(tmp_path: Path) -> None:
    from app.spool import SpoolManager

    spool = SpoolManager(tmp_path / "spool")
    part_path = spool.prepare_recording("operation-1")
    part_path.write_bytes(b"wave-data")

    asset = spool.finalize_recording("operation-1")

    assert asset.path == tmp_path / "spool" / "operation-1" / "source.wav"
    assert asset.path.read_bytes() == b"wave-data"
    assert asset.sha256 == hashlib.sha256(b"wave-data").hexdigest()
    assert asset.size == len(b"wave-data")
    assert not part_path.exists()


def test_imported_source_is_spooled_without_mutating_original(tmp_path: Path) -> None:
    from app.spool import SpoolManager

    original = tmp_path / "customer interview.flac"
    original.write_bytes(b"original-audio")
    spool = SpoolManager(tmp_path / "spool")

    asset = spool.import_source("operation-2", original)

    assert asset.path == tmp_path / "spool" / "operation-2" / "source.flac"
    assert asset.path.read_bytes() == b"original-audio"
    assert original.read_bytes() == b"original-audio"
    assert asset.sha256 == hashlib.sha256(b"original-audio").hexdigest()


def test_imported_source_is_an_independent_copy(tmp_path: Path) -> None:
    from app.spool import SpoolManager

    original = tmp_path / "mutable.wav"
    original.write_bytes(b"first-version")
    spool = SpoolManager(tmp_path / "spool")

    asset = spool.import_source("operation-copy", original)
    original.write_bytes(b"second-version")

    assert asset.hardlinked is False
    assert asset.path.read_bytes() == b"first-version"
    assert asset.sha256 == hashlib.sha256(b"first-version").hexdigest()


def test_track_import_uses_controlled_name_and_ack_cleanup_removes_audio(
    tmp_path: Path,
) -> None:
    from app.audio_sources import AudioSourceKind
    from app.spool import SpoolManager

    original = tmp_path / "captured.wav"
    original.write_bytes(b"track-audio")
    spool = SpoolManager(tmp_path / "spool")

    track = spool.import_track(
        "operation-tracks",
        original,
        source=AudioSourceKind.SYSTEM,
    )
    source = spool.import_source("operation-tracks", original)
    removed = spool.delete_source("operation-tracks")

    assert track.path.name == "track-system.wav"
    assert set(removed) == {track.path, source.path}
    assert original.is_file()


def test_retention_cleanup_removes_only_expired_spool_assets(tmp_path: Path) -> None:
    from app.spool import SpoolManager

    now = datetime.now(timezone.utc)
    spool = SpoolManager(tmp_path / "spool")
    expired_source = tmp_path / "expired.wav"
    retained_source = tmp_path / "retained.wav"
    expired_source.write_bytes(b"expired")
    retained_source.write_bytes(b"retained")
    spool.import_source("expired-operation", expired_source)
    spool.import_source("retained-operation", retained_source)
    spool.write_operation_metadata(
        "expired-operation",
        retention_deadline=now - timedelta(seconds=1),
    )
    spool.write_operation_metadata(
        "retained-operation",
        retention_deadline=now + timedelta(days=1),
    )
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")

    removed = spool.cleanup_expired(now=now)

    assert removed == ["expired-operation"]
    assert not (tmp_path / "spool" / "expired-operation").exists()
    assert (tmp_path / "spool" / "retained-operation" / "source.wav").exists()
    assert expired_source.read_bytes() == b"expired"
    assert retained_source.read_bytes() == b"retained"
    assert outside.read_text(encoding="utf-8") == "keep"


def test_spool_rejects_path_traversal_and_oversized_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.spool as spool_module
    from app.spool import InvalidSpoolPath, SourceTooLarge, SpoolManager

    source = tmp_path / "large.wav"
    source.write_bytes(b"four")
    spool = SpoolManager(tmp_path / "spool")

    with pytest.raises(InvalidSpoolPath):
        spool.prepare_recording("../outside")

    monkeypatch.setattr(spool_module, "MAX_SOURCE_SIZE", 3)
    with pytest.raises(SourceTooLarge):
        spool.import_source("operation-large", source)
