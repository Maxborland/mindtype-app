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


def test_recorded_dictation_is_adopted_and_completed_before_source_cleanup(
    tmp_path: Path,
) -> None:
    import json

    from app.operation_coordinator import OperationCoordinator
    from app.operation_models import OperationStage, OperationStatus
    from app.operation_store import OperationStore
    from app.spool import SpoolManager

    recorder_file = tmp_path / "recorder-temp.wav"
    recorder_file.write_bytes(b"dictation-audio")
    coordinator = OperationCoordinator(
        store=OperationStore(tmp_path / "operations.sqlite3"),
        spool=SpoolManager(tmp_path / "spool"),
    )
    route = {
        "transcription": {"provider": "local", "model": "tiny"},
    }

    adopted = coordinator.adopt_recorded_dictation(
        recorder_file,
        route=route,
        operation_id="dictation-adopted",
    )
    coordinator.begin_attempt(
        adopted.operation_id,
        stage=OperationStage.TRANSCRIBE,
    )
    completed = coordinator.complete_dictation(
        adopted.operation_id,
        text="Проверка диктовки",
        language="ru",
        confidence=0.91,
        duration_ms=2_500,
    )

    assert not recorder_file.exists()
    assert completed.status is OperationStatus.COMPLETED
    assert completed.source_asset_path.exists()
    payload = json.loads(
        completed.canonical_result_path.read_text(encoding="utf-8")
    )
    assert payload["transcript"]["segments"][0]["text"] == "Проверка диктовки"

    coordinator.acknowledge_result(adopted.operation_id)
    assert not completed.source_asset_path.exists()
    assert completed.canonical_result_path.is_file()


def test_multitrack_dictation_keeps_tracks_and_projects_channels(
    tmp_path: Path,
) -> None:
    import json
    import wave

    import numpy as np

    from app.audio_sources import (
        AudioCaptureResult,
        AudioCaptureStatus,
        AudioSourceKind,
        MultiTrackCapture,
        RecordedTrack,
    )
    from app.operation_coordinator import OperationCoordinator
    from app.operation_models import OperationStage
    from app.operation_store import OperationStore
    from app.spool import SpoolManager

    def write_wav(path: Path, channels: int, sample_rate: int) -> None:
        with wave.open(str(path), "wb") as output:
            output.setnchannels(channels)
            output.setsampwidth(2)
            output.setframerate(sample_rate)
            output.writeframes(
                np.zeros((sample_rate // 10, channels), dtype="<i2").tobytes()
            )

    mic_path = tmp_path / "mic.wav"
    system_path = tmp_path / "system.wav"
    write_wav(mic_path, 1, 16_000)
    write_wav(system_path, 2, 48_000)
    capture = MultiTrackCapture(
        results=(
            AudioCaptureResult(
                AudioCaptureStatus.COMPLETED,
                RecordedTrack(
                    AudioSourceKind.MICROPHONE,
                    mic_path,
                    16_000,
                    1,
                    10,
                    100_000_010,
                ),
            ),
            AudioCaptureResult(
                AudioCaptureStatus.COMPLETED,
                RecordedTrack(
                    AudioSourceKind.SYSTEM,
                    system_path,
                    48_000,
                    2,
                    20,
                    100_000_020,
                ),
            ),
        )
    )
    coordinator = OperationCoordinator(
        store=OperationStore(tmp_path / "operations.sqlite3"),
        spool=SpoolManager(tmp_path / "spool"),
    )

    operation = coordinator.adopt_multitrack_dictation(
        capture,
        route={"transcription": {"provider": "local", "model": "tiny"}},
        operation_id="multitrack-dictation",
    )
    coordinator.begin_attempt(
        operation.operation_id,
        stage=OperationStage.TRANSCRIBE,
    )
    completed = coordinator.complete_dictation(
        operation.operation_id,
        text="Встреча",
        language="ru",
        confidence=1.0,
        duration_ms=100,
    )
    payload = json.loads(
        completed.canonical_result_path.read_text(encoding="utf-8")
    )
    operation_dir = tmp_path / "spool" / "multitrack-dictation"

    assert operation.source_asset_path.name == "source.wav"
    assert (operation_dir / "track-microphone.wav").is_file()
    assert (operation_dir / "track-system.wav").is_file()
    assert [channel["source"] for channel in payload["source"]["channels"]] == [
        "microphone",
        "system",
    ]
    assert not mic_path.exists()
    assert not system_path.exists()

    coordinator.acknowledge_result(operation.operation_id)
    assert not operation.source_asset_path.exists()
    assert not (operation_dir / "track-microphone.wav").exists()
    assert not (operation_dir / "track-system.wav").exists()


def test_interrupted_multitrack_capture_is_retryable_with_partial_track(
    tmp_path: Path,
) -> None:
    import wave

    import numpy as np

    from app.audio_sources import (
        AudioCaptureResult,
        AudioCaptureStatus,
        AudioSourceKind,
        MultiTrackCapture,
        RecordedTrack,
    )
    from app.operation_coordinator import OperationCoordinator
    from app.operation_models import OperationStatus
    from app.operation_store import OperationStore
    from app.spool import SpoolManager

    partial = tmp_path / "partial.wav"
    with wave.open(str(partial), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(np.zeros(160, dtype="<i2").tobytes())
    capture = MultiTrackCapture(
        results=(
            AudioCaptureResult(
                AudioCaptureStatus.INTERRUPTED,
                RecordedTrack(
                    AudioSourceKind.MICROPHONE,
                    partial,
                    16_000,
                    1,
                    1,
                    10_000_001,
                ),
                "device disconnected",
            ),
        )
    )
    coordinator = OperationCoordinator(
        store=OperationStore(tmp_path / "operations.sqlite3"),
        spool=SpoolManager(tmp_path / "spool"),
    )

    operation = coordinator.adopt_multitrack_dictation(
        capture,
        route={"transcription": {"provider": "local", "model": "tiny"}},
        operation_id="interrupted-dictation",
    )

    assert operation.status is OperationStatus.RETRYABLE
    assert operation.source_asset_path.is_file()
    assert "device disconnected" in (operation.last_error_code or "")


def test_failed_multitrack_projection_cleans_spool_copies_not_originals(
    tmp_path: Path,
) -> None:
    import wave

    import numpy as np
    import pytest

    from app.audio_sources import (
        AudioCaptureResult,
        AudioCaptureStatus,
        AudioSourceKind,
        MultiTrackCapture,
        RecordedTrack,
    )
    from app.operation_coordinator import OperationCoordinator
    from app.operation_store import OperationStore
    from app.spool import SpoolManager

    valid = tmp_path / "mic.wav"
    with wave.open(str(valid), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(np.zeros(160, dtype="<i2").tobytes())
    corrupt = tmp_path / "system.wav"
    corrupt.write_bytes(b"not-a-wave")
    capture = MultiTrackCapture(
        results=(
            AudioCaptureResult(
                AudioCaptureStatus.COMPLETED,
                RecordedTrack(
                    AudioSourceKind.MICROPHONE,
                    valid,
                    16_000,
                    1,
                    1,
                    10_000_001,
                ),
            ),
            AudioCaptureResult(
                AudioCaptureStatus.COMPLETED,
                RecordedTrack(
                    AudioSourceKind.SYSTEM,
                    corrupt,
                    48_000,
                    2,
                    1,
                    10_000_001,
                ),
            ),
        )
    )
    coordinator = OperationCoordinator(
        store=OperationStore(tmp_path / "operations.sqlite3"),
        spool=SpoolManager(tmp_path / "spool"),
    )

    with pytest.raises(wave.Error):
        coordinator.adopt_multitrack_dictation(
            capture,
            route={"transcription": {"provider": "local", "model": "tiny"}},
            operation_id="failed-projection",
        )

    operation_dir = tmp_path / "spool" / "failed-projection"
    assert list(operation_dir.glob("source.*")) == []
    assert list(operation_dir.glob("track-*.wav")) == []
    assert valid.is_file()
    assert corrupt.is_file()


def test_file_task_completion_persists_canonical_raw_and_processed_result(
    tmp_path: Path,
) -> None:
    import json

    from app.operation_coordinator import OperationCoordinator
    from app.operation_models import OperationStage, OperationStatus
    from app.operation_store import OperationStore
    from app.spool import SpoolManager
    from app.transcription_models import (
        FileTask,
        SpeakerStats,
        TranscriptionResult,
        TranscriptionSegment,
    )

    original = tmp_path / "interview.wav"
    original.write_bytes(b"interview-audio")
    coordinator = OperationCoordinator(
        store=OperationStore(tmp_path / "operations.sqlite3"),
        spool=SpoolManager(tmp_path / "spool"),
    )
    operation = coordinator.create_file_operation(
        original,
        route={
            "transcription": {"provider": "mindtype_cloud", "model": "auto"},
            "diarization": {"provider": "mindtype_cloud", "model": "auto"},
            "summary": {"provider": "openrouter", "model": "anthropic/claude"},
        },
        operation_id="file-canonical",
    )
    coordinator.begin_attempt(
        operation.operation_id,
        stage=OperationStage.TRANSCRIBE,
    )
    task = FileTask(
        file_path=original,
        source_asset_path=operation.source_asset_path,
        display_name=original.name,
        operation_id=operation.operation_id,
        warning="low confidence",
    )
    task.result = TranscriptionResult(
        file_path=original,
        segments=[
            TranscriptionSegment(
                start=0.0,
                end=1.25,
                text="сырой текст",
                speaker="SPEAKER_00",
                words=[{"start": 0.0, "end": 0.5, "word": "сырой"}],
            )
        ],
        detected_language="ru",
        language_probability=0.88,
        duration=1.25,
        model_used="auto",
        processed_text="Исправленный текст.",
        summary="Краткий итог встречи.",
        summary_preset_name="PM",
        speaker_stats=[
            SpeakerStats("SPEAKER_00", "Интервьюер", 1.25, 1, 2),
        ],
        num_speakers=1,
        speaker_names={"SPEAKER_00": "Интервьюер"},
    )

    completed = coordinator.complete_file_task(task)
    payload = json.loads(
        completed.canonical_result_path.read_text(encoding="utf-8")
    )

    assert completed.status is OperationStatus.COMPLETED
    assert payload["transcript"]["segments"][0]["text"] == "сырой текст"
    assert payload["transcript"]["processed_text"] == "Исправленный текст."
    assert payload["transcript"]["segments"][0]["start_ms"] == 0
    assert payload["transcript"]["segments"][0]["end_ms"] == 1250
    assert payload["summary"]["generated"] is True
    assert payload["summary"]["source_segment_ids"] == ["segment-0001"]
    assert payload["warnings"] == ["low confidence"]


def test_file_completion_accepts_word_without_end_timestamp(
    tmp_path: Path,
) -> None:
    import json

    from app.operation_coordinator import OperationCoordinator
    from app.operation_store import OperationStore
    from app.spool import SpoolManager
    from app.transcription_models import (
        FileTask,
        TranscriptionResult,
        TranscriptionSegment,
    )

    source = tmp_path / "meeting.wav"
    source.write_bytes(b"audio")
    coordinator = OperationCoordinator(
        store=OperationStore(tmp_path / "operations.sqlite3"),
        spool=SpoolManager(tmp_path / "spool"),
    )
    task = FileTask(file_path=source)
    coordinator.prepare_file_task(
        task,
        route={
            "transcription": {"provider": "local", "model": "test"},
            "diarization": {"provider": "disabled", "model": "none"},
            "summary": {"provider": "disabled", "model": "none"},
        },
    )
    task.result = TranscriptionResult(
        file_path=source,
        segments=[
            TranscriptionSegment(
                start=0.0,
                end=1.0,
                text="hello",
                words=[{"start": 0.2, "word": "hello"}],
            )
        ],
        detected_language="en",
        language_probability=1.0,
        duration=1.0,
        model_used="test",
    )

    completed = coordinator.complete_file_task(task)

    payload = json.loads(
        completed.canonical_result_path.read_text(encoding="utf-8")
    )
    word = payload["transcript"]["segments"][0]["words"][0]
    assert word["start_ms"] == 200
    assert word["end_ms"] == 200


def test_restart_restores_file_task_from_spool_without_starting_retry(
    tmp_path: Path,
) -> None:
    from app.operation_coordinator import OperationCoordinator
    from app.operation_models import OperationStage, OperationStatus
    from app.operation_store import OperationStore
    from app.spool import SpoolManager
    from app.transcription_models import FileStatus

    original = tmp_path / "customer interview.wav"
    original.write_bytes(b"audio")
    database = tmp_path / "operations.sqlite3"
    spool_root = tmp_path / "spool"
    coordinator = OperationCoordinator(
        store=OperationStore(database),
        spool=SpoolManager(spool_root),
    )
    operation = coordinator.create_file_operation(
        original,
        route={"transcription": {"provider": "local", "model": "tiny"}},
        operation_id="file-recovery",
    )
    started = coordinator.begin_attempt(
        operation.operation_id,
        stage=OperationStage.TRANSCRIBE,
    )
    original.unlink()

    reopened = OperationCoordinator(
        store=OperationStore(database),
        spool=SpoolManager(spool_root),
    )
    restored = reopened.restore_retryable_file_tasks()
    persisted = reopened.store.get(operation.operation_id)

    assert len(restored) == 1
    assert restored[0].status is FileStatus.PENDING
    assert restored[0].operation_id == operation.operation_id
    assert restored[0].processing_path == operation.source_asset_path
    assert restored[0].file_name == "customer interview.wav"
    assert persisted.status is OperationStatus.RETRYABLE
    assert persisted.attempt_count == started.attempt_count


def test_restart_adopts_result_saved_before_database_transition(
    tmp_path: Path,
) -> None:
    from datetime import timedelta

    from app.operation_coordinator import OperationCoordinator
    from app.operation_models import (
        OperationStage,
        OperationStatus,
        utc_now,
    )
    from app.operation_store import OperationStore
    from app.result_schema import write_canonical_result
    from app.spool import SpoolManager
    from tests.test_result_schema import canonical_result

    original = tmp_path / "saved-before-crash.wav"
    original.write_bytes(b"audio")
    database = tmp_path / "operations.sqlite3"
    spool_root = tmp_path / "spool"
    coordinator = OperationCoordinator(
        store=OperationStore(database),
        spool=SpoolManager(spool_root),
    )
    operation = coordinator.create_file_operation(
        original,
        route={"transcription": {"provider": "local", "model": "tiny"}},
        operation_id="result-before-transition",
    )
    coordinator.begin_attempt(
        operation.operation_id,
        stage=OperationStage.TRANSCRIBE,
    )
    expired = utc_now() - timedelta(seconds=1)
    coordinator.store.transition(
        operation.operation_id,
        OperationStatus.RUNNING,
        retention_deadline=expired,
    )
    coordinator.spool.write_operation_metadata(
        operation.operation_id,
        retention_deadline=expired,
        display_name=original.name,
    )
    payload = canonical_result(operation.operation_id)
    payload["source"]["sha256"] = operation.source_sha256
    result_path = spool_root / operation.operation_id / "result.json"
    write_canonical_result(
        result_path,
        payload,
        expected_operation_id=operation.operation_id,
    )

    reopened = OperationCoordinator(
        store=OperationStore(database),
        spool=SpoolManager(spool_root),
    )
    restored = reopened.restore_retryable_file_tasks()
    recovered = reopened.store.get(operation.operation_id)

    assert restored == []
    assert recovered.status is OperationStatus.COMPLETED
    assert recovered.canonical_result_path == result_path.resolve()
    assert recovered.progress == 100
    assert recovered.retention_deadline is None
    assert reopened.spool.read_operation_metadata(
        operation.operation_id
    )["retention_deadline"] is None


def test_startup_recovery_exposes_retryable_dictation(
    tmp_path: Path,
) -> None:
    from app.operation_coordinator import OperationCoordinator
    from app.operation_models import OperationStage
    from app.operation_store import OperationStore
    from app.spool import SpoolManager

    database = tmp_path / "operations.sqlite3"
    spool_root = tmp_path / "spool"
    recorder_path = tmp_path / "recording.wav"
    recorder_path.write_bytes(b"dictation-audio")
    coordinator = OperationCoordinator(
        store=OperationStore(database),
        spool=SpoolManager(spool_root),
    )
    operation = coordinator.adopt_recorded_dictation(
        recorder_path,
        route={"transcription": {"provider": "local", "model": "tiny"}},
        operation_id="recover-dictation",
    )
    coordinator.begin_attempt(
        operation.operation_id,
        stage=OperationStage.TRANSCRIBE,
    )

    reopened = OperationCoordinator(
        store=OperationStore(database),
        spool=SpoolManager(spool_root),
    )
    recovery = reopened.restore_startup()

    assert recovery.retryable_files == ()
    assert [item.operation_id for item in recovery.retryable_dictations] == [
        operation.operation_id
    ]
    assert recovery.completed_pending_ack == ()


def test_file_task_progress_and_error_are_persisted_without_source_loss(
    tmp_path: Path,
) -> None:
    from app.operation_coordinator import OperationCoordinator
    from app.operation_models import OperationStage, OperationStatus
    from app.operation_store import OperationStore
    from app.spool import SpoolManager
    from app.transcription_models import FileStatus, FileTask

    original = tmp_path / "meeting.wav"
    original.write_bytes(b"audio")
    coordinator = OperationCoordinator(
        store=OperationStore(tmp_path / "operations.sqlite3"),
        spool=SpoolManager(tmp_path / "spool"),
    )
    operation = coordinator.create_file_operation(
        original,
        route={"transcription": {"provider": "local", "model": "tiny"}},
        operation_id="file-progress",
    )
    coordinator.begin_attempt(
        operation.operation_id,
        stage=OperationStage.TRANSCRIBE,
    )
    task = FileTask(
        file_path=original,
        source_asset_path=operation.source_asset_path,
        operation_id=operation.operation_id,
        status=FileStatus.PROCESSING,
        progress=62,
    )

    processing = coordinator.sync_file_task(task)
    task.status = FileStatus.ERROR
    task.error_message = "provider unavailable"
    retryable = coordinator.sync_file_task(task)

    assert processing.stage is OperationStage.DIARIZE
    assert processing.progress == 62
    assert retryable.status is OperationStatus.RETRYABLE
    assert retryable.last_error_code == "PROCESSING_FAILED"
    assert retryable.source_asset_path.is_file()


def test_legacy_retry_is_upgraded_to_spool_and_canonical_route(
    tmp_path: Path,
) -> None:
    from app.cloud_jobs import CloudJobStore
    from app.operation_coordinator import OperationCoordinator
    from app.operation_models import OperationStatus
    from app.operation_store import OperationStore
    from app.spool import SpoolManager
    from app.transcription_models import FileTask

    original = tmp_path / "legacy.wav"
    original.write_bytes(b"legacy-audio")
    database = tmp_path / "cloud_jobs.sqlite3"
    legacy = CloudJobStore(database)
    legacy.create_or_get(
        idempotency_key="legacy-operation",
        source_path=original,
        operation="file_processing",
        route={"audio": "OpenRouter"},
    )
    coordinator = OperationCoordinator(
        store=OperationStore(database),
        spool=SpoolManager(tmp_path / "spool"),
    )
    task = FileTask(
        file_path=original,
        operation_id="legacy-operation",
    )
    canonical_route = {
        "transcription": {"provider": "local", "model": "tiny"}
    }

    prepared = coordinator.prepare_file_task(task, route=canonical_route)

    assert prepared.status is OperationStatus.RUNNING
    assert prepared.source_sha256 is not None
    assert prepared.source_asset_path.parent == (
        tmp_path / "spool" / "legacy-operation"
    )
    assert prepared.route == canonical_route
    assert prepared.retention_deadline is not None
    assert task.processing_path == prepared.source_asset_path
    assert original.is_file()


def test_shutdown_cancellation_stays_recoverable_until_next_start(
    tmp_path: Path,
) -> None:
    from app.operation_coordinator import OperationCoordinator
    from app.operation_models import OperationStatus
    from app.operation_store import OperationStore
    from app.spool import SpoolManager
    from app.transcription_models import FileStatus, FileTask

    original = tmp_path / "long-call.wav"
    original.write_bytes(b"audio")
    coordinator = OperationCoordinator(
        store=OperationStore(tmp_path / "operations.sqlite3"),
        spool=SpoolManager(tmp_path / "spool"),
    )
    task = FileTask(file_path=original, operation_id="shutdown-file")
    running = coordinator.prepare_file_task(
        task,
        route={"transcription": {"provider": "local", "model": "tiny"}},
    )
    task.status = FileStatus.CANCELLED

    preserved = coordinator.sync_file_task(task, preserve_inflight=True)
    restored = coordinator.restore_retryable_file_tasks()

    assert running.status is OperationStatus.RUNNING
    assert preserved.status is OperationStatus.RUNNING
    assert len(restored) == 1
    assert restored[0].operation_id == task.operation_id
    assert coordinator.store.get(task.operation_id).status is (
        OperationStatus.RETRYABLE
    )


def test_expired_retry_source_is_removed_and_operation_becomes_failed(
    tmp_path: Path,
) -> None:
    from datetime import timedelta

    from app.operation_coordinator import OperationCoordinator
    from app.operation_models import OperationStatus, utc_now
    from app.operation_store import OperationStore
    from app.spool import SpoolManager
    from app.transcription_models import FileTask

    original = tmp_path / "expired.wav"
    original.write_bytes(b"audio")
    coordinator = OperationCoordinator(
        store=OperationStore(tmp_path / "operations.sqlite3"),
        spool=SpoolManager(tmp_path / "spool"),
    )
    task = FileTask(file_path=original, operation_id="expired-operation")
    running = coordinator.prepare_file_task(
        task,
        route={"transcription": {"provider": "local", "model": "tiny"}},
    )
    retryable = coordinator.mark_retryable(
        running.operation_id,
        error_code="PROVIDER_UNAVAILABLE",
    )
    deadline = utc_now() - timedelta(seconds=1)
    coordinator.store.transition(
        retryable.operation_id,
        OperationStatus.RETRYABLE,
        retention_deadline=deadline,
    )
    coordinator.spool.write_operation_metadata(
        retryable.operation_id,
        retention_deadline=deadline,
        display_name=task.file_name,
    )

    removed = coordinator.cleanup_expired(now=utc_now())
    failed = coordinator.store.get(retryable.operation_id)

    assert removed == [retryable.operation_id]
    assert failed.status is OperationStatus.FAILED
    assert failed.last_error_code == "RETENTION_EXPIRED"
    assert not failed.source_asset_path.exists()
    assert original.is_file()
