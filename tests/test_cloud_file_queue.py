from __future__ import annotations

from pathlib import Path


class UnusedLocalTranscriber:
    def load_model(self, **_kwargs):
        raise AssertionError("cloud route must not load a local model")


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
        def transcribe_with_timestamps(self, **_kwargs):
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
