from pathlib import Path


def test_completed_file_is_projected_for_ui_before_ack(tmp_path: Path) -> None:
    from app.operation_coordinator import OperationCoordinator
    from app.operation_models import OperationStage
    from app.operation_store import OperationStore
    from app.exporters import ExportFormat
    from app.recovery import project_completed_operation
    from app.spool import SpoolManager
    from tests.test_result_schema import canonical_result

    source = tmp_path / "meeting.wav"
    source.write_bytes(b"audio")
    coordinator = OperationCoordinator(
        store=OperationStore(tmp_path / "operations.sqlite3"),
        spool=SpoolManager(tmp_path / "spool"),
    )
    operation = coordinator.create_file_operation(
        source,
        route={"transcription": {"provider": "local", "model": "tiny"}},
        operation_id="completed-file",
    )
    running = coordinator.begin_attempt(
        operation.operation_id,
        stage=OperationStage.TRANSCRIBE,
    )
    payload = canonical_result(operation.operation_id)
    payload["source"]["display_name"] = "meeting.wav"
    payload["source"]["sha256"] = running.source_sha256
    completed = coordinator.save_canonical_result(
        operation.operation_id,
        payload,
    )

    projected = project_completed_operation(
        completed,
        output_dir=tmp_path / "exports",
        formats=(ExportFormat.JSON,),
    )

    assert projected.file_task is not None
    assert projected.file_task.status.value == "completed"
    assert projected.file_task.operation_id == operation.operation_id
    assert projected.file_task.output_files["json"].is_file()
    assert projected.dictation_text is None
    assert completed.source_asset_path.is_file()


def test_completed_file_recovery_projection_is_idempotent(tmp_path: Path) -> None:
    from app.exporters import ExportFormat
    from app.operation_coordinator import OperationCoordinator
    from app.operation_models import OperationStage
    from app.operation_store import OperationStore
    from app.recovery import project_completed_operation
    from app.spool import SpoolManager
    from tests.test_result_schema import canonical_result

    source = tmp_path / "meeting.wav"
    source.write_bytes(b"audio")
    coordinator = OperationCoordinator(
        store=OperationStore(tmp_path / "operations.sqlite3"),
        spool=SpoolManager(tmp_path / "spool"),
    )
    created = coordinator.create_file_operation(
        source,
        route={"transcription": {"provider": "local", "model": "tiny"}},
        operation_id="stable-recovery-id",
    )
    running = coordinator.begin_attempt(
        created.operation_id,
        stage=OperationStage.TRANSCRIBE,
    )
    payload = canonical_result(created.operation_id)
    payload["source"]["display_name"] = "meeting.wav"
    payload["source"]["sha256"] = running.source_sha256
    completed = coordinator.save_canonical_result(created.operation_id, payload)
    output_dir = tmp_path / "exports"

    first = project_completed_operation(
        completed,
        output_dir=output_dir,
        formats=(ExportFormat.JSON,),
    )
    second = project_completed_operation(
        completed,
        output_dir=output_dir,
        formats=(ExportFormat.JSON,),
    )

    assert first.file_task is not None
    assert second.file_task is not None
    assert first.file_task.output_files == second.file_task.output_files
    assert len(list(output_dir.glob("*.json"))) == 1
