from __future__ import annotations

from pathlib import Path

import pytest


def _coordinator(root: Path):
    from app.operation_coordinator import OperationCoordinator
    from app.operation_store import OperationStore
    from app.spool import SpoolManager

    return OperationCoordinator(
        store=OperationStore(root / "operations.sqlite3"),
        spool=SpoolManager(root / "spool"),
    )


def _running_file(root: Path, operation_id: str, stage):
    coordinator = _coordinator(root)
    source = root / f"{operation_id}.wav"
    source.write_bytes(b"preserved-audio")
    operation = coordinator.create_file_operation(
        source,
        route={"transcription": {"provider": "mindtype_cloud", "model": "auto"}},
        operation_id=operation_id,
    )
    return coordinator, coordinator.begin_attempt(
        operation.operation_id,
        stage=stage,
    )


def test_restart_after_local_save_before_ack_reuses_result_and_cleans_once(
    tmp_path: Path,
) -> None:
    from app.operation_models import OperationStage, OperationStatus
    from tests.test_result_schema import canonical_result

    coordinator, running = _running_file(
        tmp_path,
        "saved-before-ack",
        OperationStage.TRANSCRIBE,
    )
    payload = canonical_result(running.operation_id)
    payload["source"]["sha256"] = running.source_sha256
    completed = coordinator.save_canonical_result(running.operation_id, payload)

    restarted = _coordinator(tmp_path)
    recovered = restarted.store.get(running.operation_id)
    same_result = restarted.save_canonical_result(running.operation_id, payload)

    assert recovered is not None
    assert recovered.status is OperationStatus.COMPLETED
    assert recovered.source_asset_path.is_file()
    assert recovered.canonical_result_path.is_file()
    assert same_result.canonical_result_path == completed.canonical_result_path

    restarted.acknowledge_result(running.operation_id)
    restarted.acknowledge_result(running.operation_id)
    assert not recovered.source_asset_path.exists()
    assert recovered.canonical_result_path.is_file()


def test_restart_of_running_work_retries_same_operation_and_attempt(
    tmp_path: Path,
) -> None:
    from app.operation_models import OperationStage, OperationStatus

    coordinator, running = _running_file(
        tmp_path,
        "interrupted-upload",
        OperationStage.UPLOAD,
    )
    restarted = _coordinator(tmp_path)
    tasks = restarted.restore_retryable_file_tasks()

    assert len(tasks) == 1
    assert tasks[0].operation_id == running.operation_id
    assert tasks[0].processing_path == running.source_asset_path
    retry = restarted.prepare_file_task(
        tasks[0],
        route=running.route,
    )
    assert retry.operation_id == running.operation_id
    assert retry.status is OperationStatus.RUNNING
    assert retry.attempt_count == running.attempt_count + 1
    assert retry.source_asset_path.read_bytes() == b"preserved-audio"


def test_restart_with_missing_source_fails_closed_with_metadata(
    tmp_path: Path,
) -> None:
    from app.operation_models import OperationStage, OperationStatus

    coordinator, running = _running_file(
        tmp_path,
        "missing-source",
        OperationStage.TRANSCRIBE,
    )
    running.source_asset_path.unlink()

    restarted = _coordinator(tmp_path)
    assert restarted.store.recover_incomplete() == []
    failed = restarted.store.get(running.operation_id)

    assert failed is not None
    assert failed.status is OperationStatus.FAILED
    assert failed.last_error_code == "SOURCE_MISSING"
    assert (
        tmp_path
        / "spool"
        / running.operation_id
        / "operation.json"
    ).is_file()


@pytest.mark.parametrize(
    "stage_name",
    ["UPLOAD", "TRANSCRIBE", "DIARIZE", "SUMMARIZE", "EXPORT", "INSERT"],
)
def test_cancelled_stage_cannot_resurrect_after_restart(
    tmp_path: Path,
    stage_name: str,
) -> None:
    from app.operation_coordinator import StaleOperationCallback
    from app.operation_models import OperationStage, OperationStatus
    from tests.test_result_schema import canonical_result

    stage = getattr(OperationStage, stage_name)
    operation_id = f"cancel-{stage.value}"
    coordinator, running = _running_file(tmp_path, operation_id, stage)
    coordinator.request_cancel(operation_id)

    restarted = _coordinator(tmp_path)
    restarted.store.recover_incomplete()
    cancelled = restarted.store.get(operation_id)
    payload = canonical_result(operation_id)
    payload["source"]["sha256"] = running.source_sha256

    assert cancelled is not None
    assert cancelled.status is OperationStatus.CANCELLED
    with pytest.raises(StaleOperationCallback):
        restarted.save_canonical_result(operation_id, payload)
    assert not (
        tmp_path / "spool" / operation_id / "result.json"
    ).exists()
