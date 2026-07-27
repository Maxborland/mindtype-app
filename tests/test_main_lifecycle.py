from types import SimpleNamespace
from unittest.mock import MagicMock


def test_recovered_file_trial_usage_uses_canonical_duration() -> None:
    from app.main import MainWindow

    task = SimpleNamespace(
        result=None,
        trial_time_charged=False,
        claim_trial_time_charge=MagicMock(return_value=True),
    )
    window = SimpleNamespace(license_manager=MagicMock())

    MainWindow._record_file_trial_usage(
        window,
        task,
        "recovered-operation",
        recovered_duration_seconds=12.345,
    )

    task.claim_trial_time_charge.assert_called_once_with()
    window.license_manager.add_transcription_time.assert_called_once_with(
        12.345,
        operation_id="recovered-operation",
    )


def test_recording_is_rejected_before_capture_without_durable_storage() -> None:
    from app.main import MainWindow

    window = SimpleNamespace(
        audio_session=SimpleNamespace(
            recording=False,
            start=MagicMock(),
        ),
        _operation_coordinator=None,
        _add_journal_entry=MagicMock(),
        overlay=MagicMock(),
        _t=lambda key: key,
    )

    MainWindow._start_recording_with_overlay(window)

    window.audio_session.start.assert_not_called()
    window.overlay.show_error.assert_called_once_with("error")


def test_interrupted_capture_is_immediately_exposed_for_retry(
    tmp_path,
) -> None:
    from app.audio_sources import (
        AudioCaptureResult,
        AudioCaptureStatus,
        AudioSourceKind,
        MultiTrackCapture,
        RecordedTrack,
    )
    from app.dictation_state import DictationState
    from app.main import MainWindow

    source = tmp_path / "partial.wav"
    source.write_bytes(b"partial")
    capture = MultiTrackCapture(
        results=(
            AudioCaptureResult(
                status=AudioCaptureStatus.INTERRUPTED,
                track=RecordedTrack(
                    source=AudioSourceKind.MICROPHONE,
                    path=source,
                    sample_rate=16_000,
                    channels=1,
                    started_at_monotonic_ns=1,
                    ended_at_monotonic_ns=2,
                ),
                error="device disconnected",
            ),
        )
    )
    state = DictationState()
    state.begin_recording(started_at=1.0)
    coordinator = MagicMock()
    coordinator.adopt_multitrack_dictation.return_value = SimpleNamespace(
        operation_id="retry-operation"
    )
    window = SimpleNamespace(
        audio_session=SimpleNamespace(
            recording=True,
            stop=MagicMock(return_value=capture),
        ),
        _dictation=state,
        config=SimpleNamespace(
            config={
                "auto_insert_enabled": True,
                "transcriber_backend": "whisper_cpp",
            }
        ),
        license_manager=MagicMock(),
        overlay=MagicMock(),
        _announce_status=MagicMock(),
        _operation_coordinator=coordinator,
        _retryable_dictation_ids=[],
        _update_recovered_dictation_actions=MagicMock(),
        _add_journal_entry=MagicMock(),
        _t=lambda key: key,
    )

    MainWindow._stop_recording_with_auto_insert(window)

    assert window._retryable_dictation_ids == ["retry-operation"]
    window._update_recovered_dictation_actions.assert_called_once_with()


def test_dictation_ack_is_scheduled_after_result_delivery() -> None:
    from app.dictation_state import DictationState
    from app.main import MainWindow
    from app.operation_models import OperationStatus

    state = DictationState()
    token = state.begin_recovery(auto_insert=False)
    coordinator = MagicMock()
    coordinator.store.get.return_value = SimpleNamespace(
        status=OperationStatus.COMPLETED
    )
    window = SimpleNamespace(
        _dictation=state,
        _dictation_operation_ids={token: "operation-1"},
        _dictation_durations_ms={token: 1000},
        _operation_coordinator=coordinator,
        _retryable_dictation_ids=[],
        _update_recovered_dictation_actions=MagicMock(),
        _update_tray_icon=MagicMock(),
        _add_journal_entry=MagicMock(),
        _acknowledge_completed_operation=MagicMock(),
        overlay=MagicMock(),
        tray_icon=None,
        last_text="",
        _t=lambda key: key,
    )
    window._acknowledge_completed_operation.side_effect = (
        lambda _operation_id: (
            None
            if window.last_text == "Готовый текст"
            else (_ for _ in ()).throw(
                AssertionError("result was not delivered before ACK")
            )
        )
    )

    MainWindow._on_transcribed(
        window,
        token,
        "Готовый текст",
        "ru",
        0.9,
        "",
    )

    coordinator.complete_dictation.assert_called_once()
    coordinator.acknowledge_result.assert_not_called()
    assert window.last_text == "Готовый текст"
    window._acknowledge_completed_operation.assert_called_once_with(
        "operation-1"
    )


def test_unfinished_multitrack_stop_is_retried_by_timer(monkeypatch) -> None:
    from app.audio_sources import MultiTrackCapture
    from app.dictation_state import DictationPhase, DictationState
    from app.main import MainWindow

    state = DictationState()
    state.begin_recording(started_at=1.0)
    audio_session = MagicMock()
    audio_session.recording = True
    callbacks = []

    def stop():
        if audio_session.stop.call_count == 2:
            audio_session.recording = False
        return MultiTrackCapture(results=())

    audio_session.stop.side_effect = stop
    monkeypatch.setattr(
        "app.main.QTimer.singleShot",
        lambda delay, callback: callbacks.append((delay, callback)),
    )
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
    assert audio_session.stop.call_count == 1
    assert len(callbacks) == 1
    assert callbacks[0][0] == 100

    callbacks[0][1]()

    assert audio_session.stop.call_count == 2
    assert state.phase is DictationPhase.FAILED
    window.overlay.show_processing.assert_called()
    window.overlay.show_error.assert_called_once_with("error")


def test_audio_finalization_timer_does_not_stop_a_new_operation(
    monkeypatch,
) -> None:
    from app.main import MainWindow

    callbacks = []
    monkeypatch.setattr(
        "app.main.QTimer.singleShot",
        lambda _delay, callback: callbacks.append(callback),
    )
    window = SimpleNamespace(
        audio_session=SimpleNamespace(
            recording=True,
            stop=MagicMock(),
        ),
        _dictation=SimpleNamespace(operation_token=1),
    )

    MainWindow._schedule_audio_finalization_retry(window, 1)
    window._dictation.operation_token = 2
    callbacks[0]()

    window.audio_session.stop.assert_not_called()


def test_failed_recording_start_retries_retained_loopback_cleanup(
    monkeypatch,
) -> None:
    from app.audio_sources import AudioSourceKind, MultiTrackCapture
    from app.dictation_state import DictationState
    from app.main import MainWindow

    callbacks = []
    monkeypatch.setattr(
        "app.main.QTimer.singleShot",
        lambda delay, callback: callbacks.append((delay, callback)),
    )

    class RetainedAudioSession:
        recording = False

        def __init__(self) -> None:
            self.stop_calls = 0

        def start(self, *_args, **_kwargs) -> None:
            self.recording = True
            raise RuntimeError("microphone unavailable")

        def stop(self) -> MultiTrackCapture:
            self.stop_calls += 1
            if self.stop_calls == 2:
                self.recording = False
            return MultiTrackCapture(results=())

    audio_session = RetainedAudioSession()
    state = DictationState()
    window = SimpleNamespace(
        audio_session=audio_session,
        _operation_coordinator=MagicMock(),
        license_manager=MagicMock(),
        _dictation=state,
        _selected_device_id=lambda: None,
        _selected_audio_source=lambda: AudioSourceKind.MICROPHONE_SYSTEM,
        system_audio_box=SimpleNamespace(currentData=lambda: None),
        system_audio_consent_toggle=SimpleNamespace(isChecked=lambda: True),
        overlay=MagicMock(),
        _add_journal_entry=MagicMock(),
        _announce_status=MagicMock(),
        _update_tray_icon=MagicMock(),
        _t=lambda key: key,
    )
    window.license_manager.get_license_info.return_value = SimpleNamespace(
        is_trial=False
    )

    MainWindow._start_recording_with_overlay(window)

    assert audio_session.recording is True
    assert len(callbacks) == 1
    assert callbacks[0][0] == 100

    callbacks.pop(0)[1]()
    assert audio_session.recording is True
    assert len(callbacks) == 1

    callbacks.pop(0)[1]()
    assert audio_session.recording is False
    assert audio_session.stop_calls == 2


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


def test_initial_projection_uses_operation_id_for_crash_safe_replay(
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
    export_bundle = MagicMock(return_value={})
    monkeypatch.setattr(
        "app.main.CanonicalExporter.export_bundle",
        export_bundle,
    )
    task = FileTask(
        file_path=tmp_path / "meeting.wav",
        status=FileStatus.COMPLETED,
        operation_id=operation.operation_id,
        result=SimpleNamespace(duration=60.0),
    )
    events = []
    license_manager = MagicMock()
    license_manager.add_transcription_time.side_effect = (
        lambda *_args, **_kwargs: events.append("usage")
    )
    acknowledge = MagicMock(
        side_effect=lambda _operation_id: events.append("ack")
    )
    window = SimpleNamespace(
        _operation_coordinator=coordinator,
        _preserve_cloud_jobs_on_shutdown=False,
        _output_dir=tmp_path / "exports",
        _file_widgets={},
        _task_key=lambda path: str(path),
        _acknowledge_completed_operation=acknowledge,
        license_manager=license_manager,
        _file_processing_batch_size=0,
    )

    MainWindow._on_file_task_completed(window, task)

    assert export_bundle.call_args.kwargs == {
        "idempotency_key": operation.operation_id,
    }
    license_manager.add_transcription_time.assert_called_once_with(
        60.0,
        operation_id=operation.operation_id,
    )
    assert events == ["usage", "ack"]

def test_recovered_cloud_file_is_removed_only_after_remote_cancel(
    tmp_path,
    monkeypatch,
) -> None:
    from app.main import MainWindow
    from app.operation_models import OperationStatus
    from app.transcription_models import FileStatus, FileTask

    created = []

    class Signal:
        def connect(self, callback):
            self.callback = callback

        def emit(self, *args):
            self.callback(*args)

    class FakeWorker:
        def __init__(self, executor, operation_id):
            self.executor = executor
            self.operation_id = operation_id
            self.resolved = Signal()
            self.failed = Signal()
            self.finished = Signal()
            self.started = False
            created.append(self)

        def start(self):
            self.started = True

    monkeypatch.setattr("app.main.CloudCancellationWorker", FakeWorker)
    task = FileTask(
        file_path=tmp_path / "meeting.wav",
        status=FileStatus.PENDING,
        operation_id="cloud-recovery",
    )
    operation = SimpleNamespace(
        status=OperationStatus.RETRYABLE,
        server_job_ids={"transcription": "server-job"},
    )
    coordinator = MagicMock()
    coordinator.store.get.return_value = operation
    widget = MagicMock()
    window = SimpleNamespace(
        _operation_coordinator=coordinator,
        _file_tasks=[task],
        _file_widgets={str(task.file_path): widget},
        _task_key=lambda path: str(path),
        _init_mindtype_cloud=MagicMock(),
        _cloud_executor=MagicMock(),
        _cancellation_workers=set(),
        _add_journal_entry=MagicMock(),
        _update_file_queue_ui=MagicMock(),
    )
    window._discard_cloud_task = lambda current: (
        MainWindow._discard_cloud_task(window, current)
    )
    window._retry_file_task_cancellation = lambda current: (
        MainWindow._retry_file_task_cancellation(window, current)
    )
    window._on_file_task_cancellation_resolved = lambda current: (
        MainWindow._on_file_task_cancellation_resolved(window, current)
    )
    window._on_file_task_cancellation_failed = (
        lambda current, operation_id, error: (
            MainWindow._on_file_task_cancellation_failed(
                window,
                current,
                operation_id,
                error,
            )
        )
    )
    window._remove_file_task_from_queue = lambda current: (
        MainWindow._remove_file_task_from_queue(window, current)
    )

    MainWindow._on_remove_file_task(window, task)

    coordinator.request_cancel.assert_called_once_with(task.operation_id)
    assert task.cancellation_pending is True
    assert task in window._file_tasks
    widget.deleteLater.assert_not_called()
    assert created[0].started is True

    created[0].resolved.emit(task.operation_id)

    assert task.cancellation_pending is False
    assert task.status is FileStatus.CANCELLED
    assert task not in window._file_tasks
    widget.deleteLater.assert_called_once_with()


def test_stopped_batch_schedules_remote_cancel_outside_gui_thread(
    tmp_path,
    monkeypatch,
) -> None:
    from app.main import MainWindow
    from app.operation_models import OperationStatus
    from app.transcription_models import FileStatus, FileTask

    created = []

    class Signal:
        def connect(self, callback):
            self.callback = callback

        def emit(self, *args):
            self.callback(*args)

    class FakeWorker:
        def __init__(self, executor, operation_id):
            self.executor = executor
            self.operation_id = operation_id
            self.resolved = Signal()
            self.failed = Signal()
            self.finished = Signal()
            self.started = False
            created.append(self)

        def start(self):
            self.started = True

    monkeypatch.setattr("app.main.CloudCancellationWorker", FakeWorker)
    task = FileTask(
        file_path=tmp_path / "queued.wav",
        status=FileStatus.CANCELLED,
        operation_id="queued-cloud-job",
    )
    task.cancellation_pending = True
    running = SimpleNamespace(
        operation_id=task.operation_id,
        status=OperationStatus.RUNNING,
        canonical_result_path=None,
    )
    cancel_requested = SimpleNamespace(
        operation_id=task.operation_id,
        status=OperationStatus.CANCEL_REQUESTED,
        canonical_result_path=None,
    )
    coordinator = MagicMock()
    coordinator.sync_file_task.return_value = running
    coordinator.request_cancel.return_value = cancel_requested
    widget = MagicMock()
    window = SimpleNamespace(
        _operation_coordinator=coordinator,
        _preserve_cloud_jobs_on_shutdown=False,
        _file_tasks=[task],
        _file_widgets={str(task.file_path): widget},
        _task_key=lambda path: str(path),
        _init_mindtype_cloud=MagicMock(),
        _cloud_executor=MagicMock(),
        _cancellation_workers=set(),
        _add_journal_entry=MagicMock(),
        _file_processing_batch_size=0,
    )
    window._retry_file_task_cancellation = (
        lambda current, **options: MainWindow._retry_file_task_cancellation(
            window,
            current,
            **options,
        )
    )
    window._on_file_batch_cancellation_resolved = (
        lambda current: MainWindow._on_file_batch_cancellation_resolved(
            window,
            current,
        )
    )
    window._on_file_batch_cancellation_failed = (
        lambda current, operation_id, error: (
            MainWindow._on_file_batch_cancellation_failed(
                window,
                current,
                operation_id,
                error,
            )
        )
    )

    MainWindow._on_file_task_completed(window, task)

    coordinator.request_cancel.assert_called_once_with(task.operation_id)
    window._cloud_executor.cancel.assert_not_called()
    assert created[0].started is True
    assert task in window._file_tasks

    created[0].resolved.emit(task.operation_id)

    assert task.cancellation_pending is False
    assert task in window._file_tasks
    widget.update_status.assert_called()


def test_server_rejected_access_token_forces_cloud_session_refresh() -> None:
    from app.main import MainWindow

    session_manager = MagicMock()
    window = SimpleNamespace(
        _cloud_session_manager=session_manager,
        license_manager=MagicMock(),
    )

    MainWindow._refresh_mindtype_cloud_session(window, "rejected-access")

    session_manager.refresh_access_token.assert_called_once_with(
        force=True,
        rejected_access_token="rejected-access",
    )


def test_file_batch_prioritizes_one_persisted_cloud_route() -> None:
    from pathlib import Path

    from app.main import MainWindow
    from app.transcription_models import FileTask

    cloud_route = {
        "transcription": {
            "provider": "mindtype_cloud",
            "model": "auto",
        }
    }
    other_cloud_route = {
        "transcription": {
            "provider": "mindtype_cloud",
            "model": "accurate",
        }
    }
    requested_route = {
        "transcription": {
            "provider": "local",
            "model": "small",
        }
    }
    first = FileTask(
        file_path=Path("first.wav"),
        operation_id="cloud-first",
    )
    same_route = FileTask(
        file_path=Path("same.wav"),
        operation_id="cloud-same",
    )
    other_route = FileTask(
        file_path=Path("other.wav"),
        operation_id="cloud-other",
    )
    new_local = FileTask(file_path=Path("new-local.wav"))
    operations = {
        first.operation_id: SimpleNamespace(
            route=cloud_route,
            server_job_ids={"transcription": "job-1"},
        ),
        same_route.operation_id: SimpleNamespace(
            route=cloud_route,
            server_job_ids={"transcription": "job-2"},
        ),
        other_route.operation_id: SimpleNamespace(
            route=other_cloud_route,
            server_job_ids={"transcription": "job-3"},
        ),
    }
    store = SimpleNamespace(
        get=lambda operation_id: operations.get(operation_id)
    )
    window = SimpleNamespace(
        _operation_coordinator=SimpleNamespace(store=store)
    )

    selected, route = MainWindow._select_file_processing_batch(
        window,
        [first, same_route, other_route, new_local],
        requested_route,
    )

    assert selected == [first, same_route]
    assert route == cloud_route


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
        route={
            "transcription": {
                "provider": "local",
                "model": "large-v3",
                "backend": "whisper_cpp",
            }
        },
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
    assert window._retryable_dictation_ids == [operation.operation_id]
    assert window._dictation.phase is DictationPhase.TRANSCRIBING
    token = window._dictation.operation_token
    assert window._dictation_operation_ids[token] == operation.operation_id
    assert window._dictation_durations_ms[token] == 1250
    window._run_transcription.assert_called_once_with(source, token)


def test_recovered_dictation_uses_its_disclosed_local_backend() -> None:
    from app.main import MainWindow

    recovered_transcriber = MagicMock()
    window = SimpleNamespace(
        _transcriber_backend="openrouter",
        transcriber=MagicMock(),
        _build_transcriber=MagicMock(return_value=recovered_transcriber),
    )
    operation = SimpleNamespace(
        route={
            "transcription": {
                "provider": "local",
                "model": "large-v3",
                "backend": "whisper_cpp",
            }
        }
    )

    selected, owned = MainWindow._transcriber_for_operation(
        window,
        operation,
    )

    assert selected is recovered_transcriber
    assert owned is True
    window._build_transcriber.assert_called_once_with("whisper_cpp")


def test_failed_recovered_dictation_stays_actionable() -> None:
    from app.dictation_state import DictationState
    from app.main import MainWindow
    from app.operation_models import OperationStatus

    state = DictationState()
    token = state.begin_recovery(auto_insert=False)
    operation_id = "dictation-retry"
    coordinator = MagicMock()
    coordinator.store.get.return_value = SimpleNamespace(
        status=OperationStatus.RETRYABLE
    )
    window = SimpleNamespace(
        _dictation=state,
        _dictation_operation_ids={token: operation_id},
        _dictation_durations_ms={token: 1000},
        _retryable_dictation_ids=[],
        _operation_coordinator=coordinator,
        _update_recovered_dictation_actions=MagicMock(),
        _update_tray_icon=MagicMock(),
        _add_journal_entry=MagicMock(),
        overlay=MagicMock(),
        _t=lambda key: key,
    )

    MainWindow._on_transcribed(
        window,
        token,
        "",
        "",
        0.0,
        "temporary failure",
    )

    assert window._retryable_dictation_ids == [operation_id]
    window._update_recovered_dictation_actions.assert_called_once()


def test_canonical_persistence_failure_is_immediately_actionable() -> None:
    from app.dictation_state import DictationState
    from app.main import MainWindow
    from app.operation_models import OperationStatus

    state = DictationState()
    token = state.begin_recovery(auto_insert=False)
    operation_id = "dictation-persist-retry"
    coordinator = MagicMock()
    coordinator.complete_dictation.side_effect = OSError("disk unavailable")
    coordinator.store.get.side_effect = [
        SimpleNamespace(status=OperationStatus.RUNNING),
        SimpleNamespace(status=OperationStatus.RETRYABLE),
    ]
    window = SimpleNamespace(
        _dictation=state,
        _dictation_operation_ids={token: operation_id},
        _dictation_durations_ms={token: 1000},
        _retryable_dictation_ids=[],
        _operation_coordinator=coordinator,
        _update_recovered_dictation_actions=MagicMock(),
        _update_tray_icon=MagicMock(),
        _add_journal_entry=MagicMock(),
        overlay=MagicMock(),
        _t=lambda key: key,
    )

    MainWindow._on_transcribed(
        window,
        token,
        "Сохранённый звук",
        "ru",
        0.9,
        "",
    )

    coordinator.mark_retryable.assert_called_once_with(
        operation_id,
        error_code="CANONICAL_PERSIST_FAILED",
    )
    assert window._retryable_dictation_ids == [operation_id]
    window._update_recovered_dictation_actions.assert_called_once()


def test_update_install_preparation_stops_native_runtime_and_preserves_cloud_jobs(
) -> None:
    from app.main import MainWindow

    file_queue = SimpleNamespace(
        is_running=True,
        uses_local_transcriber=True,
        stop_for_shutdown=MagicMock(),
    )
    window = SimpleNamespace(
        _really_quit=False,
        _preserve_cloud_jobs_on_shutdown=False,
        _file_queue=file_queue,
        _cleanup_all=MagicMock(),
    )
    window._prepare_for_full_exit = lambda: (
        MainWindow._prepare_for_full_exit(window)
    )

    MainWindow._prepare_for_update_install(window)

    assert window._really_quit is True
    assert window._preserve_cloud_jobs_on_shutdown is True
    file_queue.stop_for_shutdown.assert_called_once_with()
    window._cleanup_all.assert_called_once_with()


def test_update_install_is_blocked_until_local_file_worker_stops() -> None:
    from app.main import MainWindow

    file_queue = SimpleNamespace(
        uses_local_transcriber=True,
        stop_for_shutdown=MagicMock(return_value=False),
    )
    window = SimpleNamespace(
        _really_quit=False,
        _preserve_cloud_jobs_on_shutdown=False,
        _file_queue=file_queue,
        _cleanup_all=MagicMock(),
    )
    window._prepare_for_full_exit = lambda: (
        MainWindow._prepare_for_full_exit(window)
    )

    import pytest

    with pytest.raises(
        RuntimeError,
        match="Local file transcription did not stop",
    ):
        MainWindow._prepare_for_update_install(window)

    window._cleanup_all.assert_called_once_with()


def test_downloaded_update_stays_bound_to_install_prompt_after_deferral(
) -> None:
    from app.main import MainWindow

    class Signal:
        def __init__(self):
            self.callback = None

        def disconnect(self):
            self.callback = None

        def connect(self, callback):
            self.callback = callback

    signal = Signal()
    button = MagicMock()
    button.clicked = signal
    prompt = MagicMock()
    window = SimpleNamespace(
        update_progress=MagicMock(),
        check_update_btn=button,
        update_status_label=MagicMock(),
        _prompt_install_downloaded_update=prompt,
        _t=lambda key: key,
    )

    MainWindow._on_update_download_finished(
        window,
        True,
        "MindType-Setup.exe",
        "",
    )

    assert signal.callback is prompt
    prompt.assert_called_once_with()
