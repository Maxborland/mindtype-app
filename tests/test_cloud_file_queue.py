from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import threading


class UnusedLocalTranscriber:
    def load_model(self, **_kwargs):
        raise AssertionError("cloud route must not load a local model")


def test_local_shutdown_cancels_model_loading_and_joins_worker(
    tmp_path: Path,
) -> None:
    from app.file_transcriber import FileTranscriptionQueue
    from app.transcription_models import TranscribeOptions

    entered = threading.Event()
    released = threading.Event()

    class BlockingTranscriber:
        def load_model(self, **_kwargs):
            entered.set()
            released.wait(5)

        def cancel_current(self):
            released.set()

        def transcribe_with_timestamps(self, **_kwargs):
            raise AssertionError("shutdown must stop before inference")

    queue = FileTranscriptionQueue(
        transcriber=BlockingTranscriber(),
        transcribe=TranscribeOptions(
            model_size="small",
            compute_type="int8",
            device="cpu",
            language="ru",
            beam_size=1,
            vad_filter=True,
            models_dir=tmp_path,
        ),
    )
    source = tmp_path / "pending.wav"
    source.touch()
    assert queue.add_files([source])
    queue.start()
    assert entered.wait(1)

    assert queue.stop_for_shutdown(timeout_seconds=1) is True
    assert queue.is_running is False


def test_cloud_file_queue_polls_durable_executor_and_reads_canonical_result(
    tmp_path: Path,
) -> None:
    from app.file_transcriber import FileTranscriptionQueue
    from app.operation_coordinator import OperationCoordinator
    from app.operation_models import OperationStage
    from app.operation_store import OperationStore
    from app.spool import SpoolManager
    from app.transcription_models import (
        FileStatus,
        FileTask,
        SummaryOptions,
        TranscribeOptions,
    )
    from tests.test_result_schema import canonical_result

    source = tmp_path / "meeting.wav"
    source.write_bytes(b"meeting-audio")
    coordinator = OperationCoordinator(
        store=OperationStore(tmp_path / "operations.sqlite3"),
        spool=SpoolManager(tmp_path / "spool"),
    )
    operation = coordinator.create_file_operation(
        source,
        route={
            "transcription": {
                "provider": "mindtype_cloud",
                "model": "auto",
            },
            "summary": {
                "provider": "mindtype_cloud",
                "model": "auto",
            },
        },
        operation_id="operation-cloud-queue",
    )

    class Executor:
        def __init__(self):
            self.calls = 0

        def advance_transcription(
            self,
            operation_id,
            *,
            options,
            summary_options,
        ):
            self.calls += 1
            if self.calls == 1:
                return coordinator.begin_attempt(
                    operation_id,
                    stage=OperationStage.TRANSCRIBE,
                )
            payload = canonical_result(operation_id)
            payload["source"]["sha256"] = operation.source_sha256
            payload["summary"] = {
                "text": "Проверяемый итог",
                "preset": "pm",
                "generated": True,
                "source_segment_ids": [],
            }
            completed = coordinator.save_canonical_result(
                operation_id,
                payload,
            )
            coordinator.acknowledge_result(operation_id)
            return completed

    completed = []
    queue = FileTranscriptionQueue(
        transcriber=UnusedLocalTranscriber(),
        transcribe=TranscribeOptions(
            model_size="large-v3",
            compute_type="int8",
            device="auto",
            language="ru",
            beam_size=5,
            vad_filter=True,
            models_dir=tmp_path,
        ),
        summary=SummaryOptions(enable=True, provider="mindtype_cloud"),
        cloud_executor=Executor(),
        cloud_transcribe_options={"language": "ru"},
        cloud_summary_options={
            "preset": "pm",
            "input_token_estimate": 100,
            "max_output_tokens": 800,
        },
        cloud_poll_interval=0,
        on_completed=completed.append,
    )
    task = FileTask(
        file_path=source,
        source_asset_path=operation.source_asset_path,
        operation_id=operation.operation_id,
    )

    queue._process_task(task)

    assert task.status is FileStatus.COMPLETED
    assert task.result is not None
    assert task.result.summary == "Проверяемый итог"
    assert task.result.detected_language == "ru"
    assert completed == [task]


def test_retryable_cloud_file_stays_actionable_with_same_operation(
    tmp_path: Path,
) -> None:
    from app.file_transcriber import FileTranscriptionQueue
    from app.operation_coordinator import OperationCoordinator
    from app.operation_models import OperationStage, OperationStatus
    from app.operation_store import OperationStore
    from app.spool import SpoolManager
    from app.transcription_models import (
        FileStatus,
        FileTask,
        TranscribeOptions,
    )

    source = tmp_path / "meeting.wav"
    source.write_bytes(b"audio")
    route = {
        "transcription": {
            "provider": "mindtype_cloud",
            "model": "auto",
        }
    }
    coordinator = OperationCoordinator(
        store=OperationStore(tmp_path / "operations.sqlite3"),
        spool=SpoolManager(tmp_path / "spool"),
    )
    operation = coordinator.create_file_operation(
        source,
        route=route,
        operation_id="retryable-cloud-file",
    )

    class Executor:
        def advance_transcription(self, operation_id, **_options):
            coordinator.begin_attempt(
                operation_id,
                stage=OperationStage.TRANSCRIBE,
            )
            return coordinator.mark_retryable(
                operation_id,
                error_code="INSUFFICIENT_CREDITS",
            )

    completed = []
    queue = FileTranscriptionQueue(
        transcriber=UnusedLocalTranscriber(),
        transcribe=TranscribeOptions(
            model_size="small",
            compute_type="int8",
            device="cpu",
            language="ru",
            beam_size=1,
            vad_filter=True,
            models_dir=tmp_path,
        ),
        cloud_executor=Executor(),
        cloud_poll_interval=0,
        on_completed=completed.append,
    )
    task = FileTask(
        file_path=source,
        source_asset_path=operation.source_asset_path,
        operation_id=operation.operation_id,
    )
    queue._running.set()

    queue._process_cloud_task(task)

    assert task.status is FileStatus.PENDING
    assert task.error_message == "INSUFFICIENT_CREDITS"
    assert queue.is_running is False
    assert completed == [task]
    resumed = coordinator.prepare_file_task(task, route=route)
    assert resumed.operation_id == operation.operation_id
    assert resumed.status is OperationStatus.RUNNING
    assert resumed.attempt_count == 2


def test_stopping_cloud_file_queue_does_not_cancel_shared_local_backend(
    tmp_path: Path,
) -> None:
    from unittest.mock import MagicMock

    from app.file_transcriber import FileTranscriptionQueue
    from app.transcription_models import TranscribeOptions

    transcriber = MagicMock()
    queue = FileTranscriptionQueue(
        transcriber=transcriber,
        transcribe=TranscribeOptions(
            model_size="small",
            compute_type="int8",
            device="cpu",
            language="ru",
            beam_size=1,
            vad_filter=True,
            models_dir=tmp_path,
        ),
        cloud_executor=MagicMock(),
    )

    queue.cancel()

    transcriber.cancel_current.assert_not_called()


def test_local_transcription_can_use_cloud_summary_without_repeating_stt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.file_transcriber import FileTranscriptionQueue
    from app.operation_coordinator import OperationCoordinator
    from app.operation_store import OperationStore
    from app.spool import SpoolManager
    from app.transcription_models import (
        FileStatus,
        FileTask,
        PostProcessOptions,
        SummaryOptions,
        TranscribeOptions,
    )

    source = tmp_path / "local interview.wav"
    source.write_bytes(b"local-audio")
    coordinator = OperationCoordinator(
        store=OperationStore(tmp_path / "operations.sqlite3"),
        spool=SpoolManager(tmp_path / "spool"),
    )
    task = FileTask(file_path=source)
    coordinator.prepare_file_task(
        task,
        route={
            "transcription": {"provider": "local", "model": "whisper"},
            "summary": {
                "provider": "mindtype_cloud",
                "model": "auto",
            },
        },
    )
    monkeypatch.setattr(
        "app.file_transcriber.get_file_duration",
        lambda _path: 1.0,
    )

    class LocalTranscriber:
        calls = 0

        def transcribe_with_timestamps(self, **_kwargs):
            self.calls += 1
            return (
                [{"start": 0.0, "end": 1.0, "text": "Локальный текст"}],
                "ru",
                0.95,
            )

    class SummaryExecutor:
        def __init__(self):
            self.coordinator = coordinator
            self.calls = []

        def advance_summary(
            self,
            operation_id,
            *,
            canonical_transcript,
            options,
        ):
            self.calls.append(
                (operation_id, canonical_transcript, dict(options))
            )
            result = dict(canonical_transcript)
            result["summary"] = {
                "text": "Облачный итог локальной расшифровки",
                "preset": "pm",
                "generated": True,
                "source_segment_ids": ["segment-0001"],
            }
            completed = coordinator.save_canonical_result(
                operation_id,
                result,
            )
            coordinator.acknowledge_result(operation_id)
            return completed

        def cancel(self, operation_id):
            coordinator.request_cancel(operation_id)
            return coordinator.finish_cancel(operation_id)

    summary_executor = SummaryExecutor()
    completed = []
    queue = FileTranscriptionQueue(
        transcriber=LocalTranscriber(),
        transcribe=TranscribeOptions(
            model_size="small",
            compute_type="int8",
            device="cpu",
            language="ru",
            beam_size=1,
            vad_filter=True,
            models_dir=tmp_path,
        ),
        summary=SummaryOptions(
            enable=True,
            provider="mindtype_cloud",
            preset_name="PM",
        ),
        postprocess=PostProcessOptions(enable=False),
        cloud_summary_executor=summary_executor,
        cloud_summary_options={
            "preset": "pm",
            "input_token_estimate": 100,
            "max_output_tokens": 800,
        },
        cloud_poll_interval=0,
        on_completed=completed.append,
    )

    queue._process_task(task)

    assert task.status is FileStatus.COMPLETED
    assert task.result is not None
    assert task.result.full_text == "Локальный текст"
    assert task.result.summary == "Облачный итог локальной расшифровки"
    assert len(summary_executor.calls) == 1
    assert summary_executor.calls[0][1]["route"]["transcription"][
        "provider"
    ] == "local"
    assert task.source_asset_path.exists() is False
    assert completed == [task]


def test_retryable_cloud_summary_keeps_hybrid_task_pending(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.file_transcriber import FileTranscriptionQueue
    from app.operation_coordinator import OperationCoordinator
    from app.operation_models import OperationStage, OperationStatus
    from app.operation_store import OperationStore
    from app.spool import SpoolManager
    from app.transcription_models import (
        FileStatus,
        FileTask,
        PostProcessOptions,
        SummaryOptions,
        TranscribeOptions,
    )

    source = tmp_path / "hybrid interview.wav"
    source.write_bytes(b"local-audio")
    coordinator = OperationCoordinator(
        store=OperationStore(tmp_path / "operations.sqlite3"),
        spool=SpoolManager(tmp_path / "spool"),
    )
    task = FileTask(file_path=source)
    route = {
        "transcription": {"provider": "local", "model": "whisper"},
        "summary": {"provider": "mindtype_cloud", "model": "auto"},
    }
    coordinator.prepare_file_task(task, route=route)
    monkeypatch.setattr(
        "app.file_transcriber.get_file_duration",
        lambda _path: 1.0,
    )

    class LocalTranscriber:
        calls = 0

        def load_model(self, **_kwargs):
            raise AssertionError(
                "summary resume must not load the local model"
            )

        def transcribe_with_timestamps(self, **_kwargs):
            self.calls += 1
            return (
                [{"start": 0.0, "end": 1.0, "text": "Локальный текст"}],
                "ru",
                0.95,
            )

    class SummaryExecutor:
        def __init__(self):
            self.coordinator = coordinator
            self.calls = 0

        def advance_summary(
            self,
            operation_id,
            *,
            canonical_transcript,
            **_options,
        ):
            self.calls += 1
            if self.calls == 1:
                coordinator.save_canonical_checkpoint(
                    operation_id,
                    canonical_transcript,
                    stage=OperationStage.SUMMARIZE,
                )
                operation = coordinator.store.get(operation_id)
                coordinator.store.transition(
                    operation_id,
                    operation.status,
                    stage=OperationStage.SUMMARIZE,
                    server_job_ids={"summary": "summary-1"},
                )
                return coordinator.mark_retryable(
                    operation_id,
                    error_code="INSUFFICIENT_CREDITS",
                )
            result = dict(canonical_transcript)
            result["summary"] = {
                "text": "Облачный итог после resume",
                "preset": "pm",
                "generated": True,
                "source_segment_ids": ["segment-0001"],
            }
            return coordinator.save_canonical_result(
                operation_id,
                result,
            )

    completed = []
    transcriber = LocalTranscriber()
    queue = FileTranscriptionQueue(
        transcriber=transcriber,
        transcribe=TranscribeOptions(
            model_size="small",
            compute_type="int8",
            device="cpu",
            language="ru",
            beam_size=1,
            vad_filter=True,
            models_dir=tmp_path,
        ),
        summary=SummaryOptions(
            enable=True,
            provider="mindtype_cloud",
            preset_name="PM",
        ),
        postprocess=PostProcessOptions(enable=False),
        cloud_summary_executor=SummaryExecutor(),
        cloud_poll_interval=0,
        on_completed=completed.append,
    )
    queue._running.set()

    queue._process_task(task)

    assert task.status is FileStatus.PENDING
    assert task.error_message == "INSUFFICIENT_CREDITS"
    assert queue.is_running is False
    assert completed == [task]
    resumed = coordinator.prepare_file_task(task, route=route)
    assert resumed.operation_id == task.operation_id
    assert resumed.status is OperationStatus.RUNNING
    assert resumed.attempt_count == 2

    queue._queue.put(task)
    queue._running.set()
    queue._worker()

    assert transcriber.calls == 1
    assert task.status is FileStatus.COMPLETED
    assert task.result.summary == "Облачный итог после resume"
    assert len(completed) == 2


def test_failed_cloud_cancel_stays_durable_for_startup_recovery(
    tmp_path: Path,
) -> None:
    import pytest

    from app.file_transcriber import FileTranscriptionQueue
    from app.operation_coordinator import OperationCoordinator
    from app.operation_models import OperationStatus
    from app.operation_store import OperationStore
    from app.spool import SpoolManager
    from app.transcription_models import (
        FileStatus,
        FileTask,
        TranscribeOptions,
    )

    source = tmp_path / "meeting.wav"
    source.write_bytes(b"audio")
    coordinator = OperationCoordinator(
        store=OperationStore(tmp_path / "operations.sqlite3"),
        spool=SpoolManager(tmp_path / "spool"),
    )
    operation = coordinator.create_file_operation(
        source,
        route={
            "transcription": {
                "provider": "mindtype_cloud",
                "model": "auto",
            }
        },
        operation_id="cancel-recovery",
    )

    class FailingExecutor:
        def cancel(self, operation_id):
            coordinator.request_cancel(operation_id)
            raise RuntimeError("network unavailable")

    queue = FileTranscriptionQueue(
        transcriber=UnusedLocalTranscriber(),
        transcribe=TranscribeOptions(
            model_size="small",
            compute_type="int8",
            device="cpu",
            language="ru",
            beam_size=1,
            vad_filter=True,
            models_dir=tmp_path,
        ),
        cloud_executor=FailingExecutor(),
    )
    task = FileTask(
        file_path=source,
        source_asset_path=operation.source_asset_path,
        operation_id=operation.operation_id,
        status=FileStatus.TRANSCRIBING,
    )
    queue._cancelled.set()

    with pytest.raises(RuntimeError, match="network unavailable"):
        queue._process_cloud_task(task)

    task.status = FileStatus.CANCELLED
    durable = coordinator.sync_file_task(task)
    assert task.cancellation_pending is True
    assert durable.status is OperationStatus.CANCEL_REQUESTED


def test_pending_cloud_cancel_respects_poll_interval(
    tmp_path: Path,
) -> None:
    from app.file_transcriber import FileTranscriptionQueue
    from app.operation_models import OperationStage, OperationStatus
    from app.transcription_models import FileTask, TranscribeOptions

    calls = []

    class Executor:
        def cancel(self, _operation_id):
            calls.append("cancel")
            status = (
                OperationStatus.CANCEL_REQUESTED
                if len(calls) == 1
                else OperationStatus.CANCELLED
            )
            return SimpleNamespace(
                status=status,
                stage=OperationStage.TRANSCRIBE,
            )

    queue = FileTranscriptionQueue(
        transcriber=UnusedLocalTranscriber(),
        transcribe=TranscribeOptions(
            model_size="small",
            compute_type="int8",
            device="cpu",
            language="ru",
            beam_size=1,
            vad_filter=True,
            models_dir=tmp_path,
        ),
        cloud_executor=Executor(),
        cloud_poll_interval=0.25,
    )
    waits = []
    queue._cloud_wait_interrupted.wait = waits.append
    queue._cancelled.set()
    task = FileTask(file_path=tmp_path / "meeting.wav")

    queue._process_cloud_task(task)

    assert calls == ["cancel", "cancel"]
    assert waits == [0.25]


def test_cancel_pending_recovered_cloud_job_defers_remote_executor(
    tmp_path: Path,
) -> None:
    from app.file_transcriber import FileTranscriptionQueue
    from app.transcription_models import (
        FileStatus,
        FileTask,
        TranscribeOptions,
    )

    operation = SimpleNamespace(
        server_job_ids={"transcription": "server-job"}
    )
    cancel_calls = []

    class Executor:
        coordinator = SimpleNamespace(
            store=SimpleNamespace(get=lambda _operation_id: operation)
        )

        def cancel(self, operation_id):
            cancel_calls.append(operation_id)

    completed = []
    queue = FileTranscriptionQueue(
        transcriber=UnusedLocalTranscriber(),
        transcribe=TranscribeOptions(
            model_size="small",
            compute_type="int8",
            device="cpu",
            language="ru",
            beam_size=1,
            vad_filter=True,
            models_dir=tmp_path,
        ),
        cloud_executor=Executor(),
        on_completed=completed.append,
    )
    task = FileTask(
        file_path=tmp_path / "meeting.wav",
        operation_id="recovered-cloud-job",
    )
    queue._tasks.append(task)

    assert queue.cancel() == [task]

    assert cancel_calls == []
    assert completed == [task]
    assert task.status is FileStatus.CANCELLED
    assert task.cancellation_pending is True


def test_shutdown_stops_cloud_polling_without_remote_cancel(
    tmp_path: Path,
) -> None:
    from app.file_transcriber import FileTranscriptionQueue
    from app.transcription_models import FileTask, TranscribeOptions

    class Executor:
        def __init__(self):
            self.cancelled = []
            self.advanced = []

        def cancel(self, operation_id):
            self.cancelled.append(operation_id)
            raise AssertionError("shutdown must not cancel the remote job")

        def advance_transcription(self, operation_id, **_options):
            self.advanced.append(operation_id)
            raise AssertionError("shutdown must stop before another poll")

    executor = Executor()
    queue = FileTranscriptionQueue(
        transcriber=UnusedLocalTranscriber(),
        transcribe=TranscribeOptions(
            model_size="small",
            compute_type="int8",
            device="cpu",
            language="ru",
            beam_size=1,
            vad_filter=True,
            models_dir=tmp_path,
        ),
        cloud_executor=executor,
    )
    task = FileTask(
        file_path=tmp_path / "meeting.wav",
        operation_id="preserved-cloud-job",
    )

    queue.stop_for_shutdown()
    queue._process_cloud_task(task)

    assert executor.cancelled == []
    assert executor.advanced == []
