"""Lifecycle tests for background workers."""

from pathlib import Path
from unittest.mock import MagicMock

from app.ui.workers import CloudDictationWorker, TranscribeWorker


class CompletingTranscriber:
    def __init__(self):
        self.after_last_item = None
        self.cancel_calls = 0

    def load_model(self, **kwargs):
        return None

    def transcribe_stream(self, *args, **kwargs):
        yield "готовый текст", "ru", 1.0
        if self.after_last_item:
            self.after_last_item()

    def cancel_current(self):
        self.cancel_calls += 1


def make_worker(transcriber) -> TranscribeWorker:
    return TranscribeWorker(
        transcriber,
        Path("recording.wav"),
        model_size="tiny",
        compute_type="int8",
        device="cpu",
        cpu_threads=1,
        num_workers=1,
        language="ru",
        beam_size=1,
        vad_filter=False,
        models_dir=Path("models"),
    )


def test_cancel_after_final_stream_item_emits_only_cancelled():
    transcriber = CompletingTranscriber()
    worker = make_worker(transcriber)
    transcriber.after_last_item = worker.cancel
    finished = []
    cancelled = []
    worker.finished.connect(lambda *args: finished.append(args))
    worker.cancelled.connect(lambda: cancelled.append(True))

    worker.run()

    assert cancelled == [True]
    assert finished == []
    assert transcriber.cancel_calls == 1


def test_cloud_dictation_worker_returns_saved_canonical_text(tmp_path):
    from app.operation_coordinator import OperationCoordinator
    from app.operation_models import OperationStage
    from app.operation_store import OperationStore
    from app.spool import SpoolManager
    from tests.test_result_schema import canonical_result

    source = tmp_path / "dictation.wav"
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
        operation_id="cloud-dictation",
    )

    class Executor:
        def advance_transcription(self, operation_id, *, options):
            coordinator.begin_attempt(
                operation_id,
                stage=OperationStage.TRANSCRIBE,
            )
            payload = canonical_result(operation_id)
            payload["source"]["sha256"] = operation.source_sha256
            return coordinator.save_canonical_result(operation_id, payload)

        def cancel(self, operation_id):
            raise AssertionError(operation_id)

    worker = CloudDictationWorker(
        Executor(),
        operation.operation_id,
        options={"language": "ru"},
        poll_interval_ms=0,
    )
    finished = []
    worker.finished.connect(lambda *args: finished.append(args))

    worker.run()

    assert len(finished) == 1
    assert finished[0][1:] == ("ru", 0.94, "")


def test_cloud_cancel_only_calls_network_from_worker_thread():
    executor = MagicMock()
    worker = CloudDictationWorker(
        executor,
        "operation-1",
        options={},
        poll_interval_ms=0,
    )
    cancelled = []
    worker.cancelled.connect(lambda: cancelled.append(True))

    worker.cancel()

    executor.cancel.assert_not_called()

    worker.run()

    executor.cancel.assert_called_once_with("operation-1")
    assert cancelled == [True]
