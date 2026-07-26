from pathlib import Path


def test_file_operation_completes_only_after_result_and_ack_cleans_spool_source(
    tmp_path: Path,
) -> None:
    from datetime import timedelta

    from app.operation_coordinator import OperationCoordinator
    from app.operation_models import OperationStage, OperationStatus, utc_now
    from app.operation_store import OperationStore
    from app.spool import SpoolManager
    from tests.test_result_schema import canonical_result

    original = tmp_path / "meeting.wav"
    original.write_bytes(b"meeting-audio")
    spool = SpoolManager(tmp_path / "spool")
    coordinator = OperationCoordinator(
        store=OperationStore(tmp_path / "operations.sqlite3"),
        spool=spool,
    )
    route = {
        "transcription": {"provider": "mindtype_cloud", "model": "auto"},
    }

    created = coordinator.create_file_operation(
        original,
        route=route,
        operation_id="operation-e2e",
    )
    coordinator.begin_attempt("operation-e2e", stage=OperationStage.UPLOAD)
    result = canonical_result("operation-e2e")
    result["source"].update(
        display_name=original.name,
        sha256=created.source_sha256,
    )
    completed = coordinator.save_canonical_result("operation-e2e", result)
    coordinator.acknowledge_result("operation-e2e")
    removed = spool.cleanup_expired(now=utc_now() + timedelta(days=8))

    assert created.source_asset_path != original
    assert created.source_asset_path.exists() is False
    assert original.read_bytes() == b"meeting-audio"
    assert completed.status is OperationStatus.COMPLETED
    assert completed.canonical_result_path.is_file()
    assert completed.canonical_result_path.parent == (
        tmp_path / "spool" / "operation-e2e"
    )
    assert removed == []
    assert completed.canonical_result_path.is_file()


def test_dictation_is_not_processable_until_recording_is_finalized(
    tmp_path: Path,
) -> None:
    from app.operation_coordinator import OperationCoordinator
    from app.operation_models import OperationKind, OperationStage
    from app.operation_store import OperationStore
    from app.spool import SpoolManager

    store = OperationStore(tmp_path / "operations.sqlite3")
    coordinator = OperationCoordinator(
        store=store,
        spool=SpoolManager(tmp_path / "spool"),
    )
    operation_id, part_path = coordinator.prepare_dictation(
        operation_id="dictation-1"
    )
    part_path.write_bytes(b"wave-data")

    assert store.get(operation_id) is None

    finalized = coordinator.finalize_dictation(
        operation_id,
        route={"transcription": {"provider": "local", "model": "tiny"}},
    )

    assert finalized.kind is OperationKind.DICTATION
    assert finalized.stage is OperationStage.PERSIST
    assert finalized.source_asset_path.name == "source.wav"
    assert finalized.source_asset_path.is_file()


def test_cancellation_ignores_late_success_and_finishes_once(
    tmp_path: Path,
) -> None:
    import pytest

    from app.operation_coordinator import (
        OperationCoordinator,
        StaleOperationCallback,
    )
    from app.operation_models import OperationStage, OperationStatus
    from app.operation_store import OperationStore
    from app.spool import SpoolManager
    from tests.test_result_schema import canonical_result

    original = tmp_path / "meeting.wav"
    original.write_bytes(b"meeting-audio")
    spool = SpoolManager(tmp_path / "spool")
    coordinator = OperationCoordinator(
        store=OperationStore(tmp_path / "operations.sqlite3"),
        spool=spool,
    )
    created = coordinator.create_file_operation(
        original,
        route={"transcription": {"provider": "mindtype_cloud", "model": "auto"}},
        operation_id="operation-cancel",
    )
    coordinator.begin_attempt("operation-cancel", stage=OperationStage.UPLOAD)
    requested = coordinator.request_cancel("operation-cancel")
    late_result = canonical_result("operation-cancel")
    late_result["source"]["sha256"] = created.source_sha256

    with pytest.raises(StaleOperationCallback):
        coordinator.save_canonical_result("operation-cancel", late_result)

    cancelled = coordinator.finish_cancel("operation-cancel")

    assert requested.status is OperationStatus.CANCEL_REQUESTED
    assert cancelled.status is OperationStatus.CANCELLED
    assert not (
        tmp_path / "spool" / "operation-cancel" / "result.json"
    ).exists()
