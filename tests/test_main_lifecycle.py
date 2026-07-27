from types import SimpleNamespace
from unittest.mock import MagicMock


def test_unfinished_multitrack_stop_can_be_retried() -> None:
    from app.audio_sources import MultiTrackCapture
    from app.dictation_state import DictationPhase, DictationState
    from app.main import MainWindow

    state = DictationState()
    state.begin_recording(started_at=1.0)
    audio_session = MagicMock()
    audio_session.recording = True
    audio_session.stop.return_value = MultiTrackCapture(results=())
    window = SimpleNamespace(
        audio_session=audio_session,
        _dictation=state,
        config=SimpleNamespace(
            config={"auto_insert_enabled": True}
        ),
        overlay=MagicMock(),
        license_manager=MagicMock(),
        _add_journal_entry=MagicMock(),
        _announce_status=MagicMock(),
        _t=lambda key: key,
    )

    MainWindow._stop_recording_with_auto_insert(window)
    MainWindow._stop_recording_with_auto_insert(window)

    assert audio_session.stop.call_count == 2
    assert state.phase is DictationPhase.RECORDING
    window.overlay.show_processing.assert_called()
    window.overlay.show_error.assert_not_called()


def test_failed_projection_keeps_source_pending_ack(
    tmp_path,
    monkeypatch,
) -> None:
    from app.main import MainWindow
    from app.transcription_models import FileStatus, FileTask

    canonical_path = tmp_path / "result.json"
    canonical_path.write_text("{}", encoding="utf-8")
    operation = SimpleNamespace(
        operation_id="operation-1",
        canonical_result_path=canonical_path,
    )
    coordinator = MagicMock()
    coordinator.sync_file_task.return_value = operation
    task = FileTask(
        file_path=tmp_path / "meeting.wav",
        status=FileStatus.COMPLETED,
        operation_id=operation.operation_id,
    )
    monkeypatch.setattr(
        "app.main.CanonicalExporter.export_bundle",
        MagicMock(side_effect=PermissionError("destination locked")),
    )
    window = SimpleNamespace(
        _operation_coordinator=coordinator,
        _preserve_cloud_jobs_on_shutdown=False,
        _output_dir=tmp_path / "exports",
        _file_widgets={},
        _task_key=lambda path: str(path),
        license_manager=MagicMock(),
        _file_processing_batch_size=0,
    )

    MainWindow._on_file_task_completed(window, task)

    coordinator.acknowledge_result.assert_not_called()
    assert task.status is FileStatus.COMPLETED
    assert "Export failed" in task.warning


def test_recovered_dictation_action_starts_the_preserved_operation(
    tmp_path,
    monkeypatch,
) -> None:
    from app.dictation_state import DictationPhase, DictationState
    from app.main import MainWindow
    from app.operation_models import OperationStatus

    source = tmp_path / "recovered.wav"
    source.write_bytes(b"preserved")
    operation = SimpleNamespace(
        operation_id="dictation-retry",
        status=OperationStatus.RETRYABLE,
        source_asset_path=source,
    )
    coordinator = MagicMock()
    coordinator.store.get.return_value = operation
    monkeypatch.setattr("app.main.get_file_duration", lambda _path: 1.25)
    window = SimpleNamespace(
        _operation_coordinator=coordinator,
        _retryable_dictation_ids=[operation.operation_id],
        license_manager=MagicMock(),
        audio_session=SimpleNamespace(recording=False),
        _dictation=DictationState(),
        _dictation_operation_ids={},
        _dictation_durations_ms={},
        _update_recovered_dictation_actions=MagicMock(),
        _show_trial_expired_dialog=MagicMock(),
        _add_journal_entry=MagicMock(),
        _announce_status=MagicMock(),
        _run_transcription=MagicMock(),
        overlay=MagicMock(),
        _t=lambda key: key,
    )
    window.license_manager.check_transcription_entitlement.return_value = (
        True,
        None,
    )

    MainWindow._retry_next_recovered_dictation(window)

    coordinator.begin_attempt.assert_called_once()
    assert window._retryable_dictation_ids == []
    assert window._dictation.phase is DictationPhase.TRANSCRIBING
    token = window._dictation.operation_token
    assert window._dictation_operation_ids[token] == operation.operation_id
    assert window._dictation_durations_ms[token] == 1250
    window._run_transcription.assert_called_once_with(source, token)
