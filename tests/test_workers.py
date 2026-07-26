"""Lifecycle tests for background workers."""

from pathlib import Path

from app.ui.workers import TranscribeWorker


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
