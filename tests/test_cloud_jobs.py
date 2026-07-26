from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest


def test_create_or_get_persists_one_job_per_idempotency_key(tmp_path: Path) -> None:
    from app.cloud_jobs import CloudJobState, CloudJobStore

    source = tmp_path / "interview.wav"
    source.write_bytes(b"audio")
    database = tmp_path / "cloud-jobs.sqlite3"
    route = {
        "audio": "OpenRouter",
        "diarization": "OpenRouter",
        "summary": "MindType Cloud",
    }

    first_store = CloudJobStore(database)
    created = first_store.create_or_get(
        idempotency_key="operation-123",
        source_path=source,
        operation="file_processing",
        route=route,
    )

    reopened_store = CloudJobStore(database)
    duplicate = reopened_store.create_or_get(
        idempotency_key="operation-123",
        source_path=source,
        operation="file_processing",
        route=route,
    )

    assert duplicate.job_id == created.job_id
    assert duplicate.state is CloudJobState.CREATED
    assert duplicate.source_path == source.resolve()
    assert duplicate.route == route
    assert reopened_store.get(created.job_id) == duplicate
    assert reopened_store.count() == 1


def test_transition_enforces_declared_lifecycle_and_terminal_states(
    tmp_path: Path,
) -> None:
    from app.cloud_jobs import (
        CloudJobState,
        CloudJobStore,
        InvalidCloudJobTransition,
    )

    source = tmp_path / "meeting.wav"
    source.write_bytes(b"audio")
    store = CloudJobStore(tmp_path / "jobs.sqlite3")
    job = store.create_or_get(
        idempotency_key="operation-456",
        source_path=source,
        operation="file_processing",
        route={"audio": "OpenRouter"},
    )

    processing = store.transition(
        job.job_id,
        CloudJobState.PROCESSING,
        progress=30,
    )
    completed = store.transition(
        job.job_id,
        CloudJobState.COMPLETED,
        progress=100,
        result={"outputs": ["meeting.html"]},
    )

    assert processing.state is CloudJobState.PROCESSING
    assert processing.progress == 30
    assert completed.state is CloudJobState.COMPLETED
    assert completed.completed_at is not None
    assert completed.result == {"outputs": ["meeting.html"]}

    with pytest.raises(InvalidCloudJobTransition):
        store.transition(completed.job_id, CloudJobState.PROCESSING)


def test_recover_incomplete_moves_only_inflight_jobs_to_retryable(
    tmp_path: Path,
) -> None:
    from app.cloud_jobs import CloudJobState, CloudJobStore

    source = tmp_path / "recording.wav"
    source.write_bytes(b"audio")
    store = CloudJobStore(tmp_path / "jobs.sqlite3")

    def create(key: str):
        return store.create_or_get(
            idempotency_key=key,
            source_path=source,
            operation="file_processing",
            route={"audio": "OpenRouter"},
        )

    created = create("created")
    uploading = create("uploading")
    processing = create("processing")
    completed = create("completed")
    store.transition(uploading.job_id, CloudJobState.UPLOADING)
    store.transition(processing.job_id, CloudJobState.PROCESSING)
    store.transition(completed.job_id, CloudJobState.PROCESSING)
    store.transition(completed.job_id, CloudJobState.COMPLETED, progress=100)

    recovered = store.recover_incomplete()

    assert {job.job_id for job in recovered} == {
        created.job_id,
        uploading.job_id,
        processing.job_id,
    }
    assert all(job.state is CloudJobState.RETRYABLE for job in recovered)
    assert store.get(completed.job_id).state is CloudJobState.COMPLETED


def test_recover_incomplete_fails_job_when_source_file_is_missing(
    tmp_path: Path,
) -> None:
    from app.cloud_jobs import CloudJobState, CloudJobStore

    source = tmp_path / "deleted.wav"
    source.write_bytes(b"audio")
    store = CloudJobStore(tmp_path / "jobs.sqlite3")
    job = store.create_or_get(
        idempotency_key="missing-source",
        source_path=source,
        operation="file_processing",
        route={"audio": "OpenRouter"},
    )
    source.unlink()

    recovered = store.recover_incomplete()
    failed = store.get(job.job_id)

    assert recovered == []
    assert failed.state is CloudJobState.FAILED
    assert failed.last_error == "Source file is missing; retry is impossible."


def test_attempt_error_remote_id_progress_and_result_survive_reopen(
    tmp_path: Path,
) -> None:
    from app.cloud_jobs import CloudJobState, CloudJobStore

    source = tmp_path / "call.wav"
    source.write_bytes(b"audio")
    database = tmp_path / "jobs.sqlite3"
    store = CloudJobStore(database)
    job = store.create_or_get(
        idempotency_key="persisted-metadata",
        source_path=source,
        operation="file_processing",
        route={"audio": "MindType Cloud"},
    )

    started = store.begin_attempt(
        job.job_id,
        state=CloudJobState.UPLOADING,
        remote_job_id="remote-789",
    )
    store.transition(
        job.job_id,
        CloudJobState.RETRYABLE,
        progress=40,
        last_error="HTTP 429",
    )

    reopened = CloudJobStore(database)
    retryable = reopened.get(job.job_id)
    assert started.attempt_count == 1
    assert retryable.attempt_count == 1
    assert retryable.remote_job_id == "remote-789"
    assert retryable.progress == 40
    assert retryable.last_error == "HTTP 429"

    second_attempt = reopened.begin_attempt(
        job.job_id,
        state=CloudJobState.PROCESSING,
    )
    reopened.transition(
        job.job_id,
        CloudJobState.COMPLETED,
        progress=100,
        result={"outputs": {"json": "call.json"}},
    )
    completed = CloudJobStore(database).get(job.job_id)

    assert second_attempt.attempt_count == 2
    assert completed.result == {"outputs": {"json": "call.json"}}


def test_list_retryable_returns_existing_and_recovered_jobs(tmp_path: Path) -> None:
    from app.cloud_jobs import CloudJobState, CloudJobStore

    source = tmp_path / "lecture.wav"
    source.write_bytes(b"audio")
    store = CloudJobStore(tmp_path / "jobs.sqlite3")

    first = store.create_or_get(
        idempotency_key="first",
        source_path=source,
        operation="file_processing",
        route={"summary": "OpenRouter"},
    )
    store.transition(first.job_id, CloudJobState.RETRYABLE, last_error="HTTP 500")
    second = store.create_or_get(
        idempotency_key="second",
        source_path=source,
        operation="file_processing",
        route={"summary": "OpenRouter"},
    )

    store.recover_incomplete()

    assert [job.job_id for job in store.list_retryable()] == [
        first.job_id,
        second.job_id,
    ]


def test_progress_updates_are_safe_across_worker_threads(tmp_path: Path) -> None:
    from app.cloud_jobs import CloudJobState, CloudJobStore

    source = tmp_path / "panel.wav"
    source.write_bytes(b"audio")
    store = CloudJobStore(tmp_path / "jobs.sqlite3")
    job = store.create_or_get(
        idempotency_key="threaded-progress",
        source_path=source,
        operation="file_processing",
        route={"audio": "OpenRouter"},
    )
    store.begin_attempt(job.job_id, state=CloudJobState.PROCESSING)

    with ThreadPoolExecutor(max_workers=4) as executor:
        updates = list(
            executor.map(
                lambda progress: store.transition(
                    job.job_id,
                    CloudJobState.PROCESSING,
                    progress=progress,
                ),
                range(1, 21),
            )
        )

    persisted = store.get(job.job_id)
    assert len(updates) == 20
    assert persisted.state is CloudJobState.PROCESSING
    assert 1 <= persisted.progress <= 20


def test_result_metadata_rejects_transcript_sized_payloads(tmp_path: Path) -> None:
    from app.cloud_jobs import (
        CloudJobPayloadTooLarge,
        CloudJobState,
        CloudJobStore,
    )

    source = tmp_path / "private.wav"
    source.write_bytes(b"audio")
    store = CloudJobStore(tmp_path / "jobs.sqlite3")
    job = store.create_or_get(
        idempotency_key="bounded-result",
        source_path=source,
        operation="file_processing",
        route={"audio": "MindType Cloud"},
    )
    store.begin_attempt(job.job_id, state=CloudJobState.PROCESSING)

    with pytest.raises(CloudJobPayloadTooLarge):
        store.transition(
            job.job_id,
            CloudJobState.COMPLETED,
            result={"transcript": "sensitive text " * 30_000},
        )

    assert store.get(job.job_id).state is CloudJobState.PROCESSING


def test_file_task_tracker_restores_retryable_cloud_work(tmp_path: Path) -> None:
    from app.cloud_jobs import (
        CloudJobState,
        CloudJobStore,
        FileCloudJobTracker,
    )
    from app.transcription_models import FileStatus, FileTask

    source = tmp_path / "research-call.wav"
    source.write_bytes(b"audio")
    database = tmp_path / "jobs.sqlite3"
    tracker = FileCloudJobTracker(CloudJobStore(database))
    task = FileTask(file_path=source)

    registered = tracker.register(
        task,
        route={
            "audio": "OpenRouter",
            "diarization": "OpenRouter",
            "summary": "Off",
        },
    )
    tracker.begin(task)
    task.status = FileStatus.TRANSCRIBING
    task.progress = 35
    tracker.sync(task)
    task.status = FileStatus.ERROR
    task.error_message = "HTTP 500"
    retryable = tracker.sync(task)

    restored = FileCloudJobTracker(
        CloudJobStore(database)
    ).restore_retryable_tasks()

    assert registered.idempotency_key == task.operation_id
    assert registered.job_id == task.cloud_job_id
    assert retryable.state is CloudJobState.RETRYABLE
    assert retryable.progress == 35
    assert len(restored) == 1
    assert restored[0].file_path == source.resolve()
    assert restored[0].status is FileStatus.PENDING
    assert restored[0].operation_id == task.operation_id
    assert restored[0].cloud_job_id == task.cloud_job_id


def test_file_task_tracker_persists_completed_output_metadata(tmp_path: Path) -> None:
    from app.cloud_jobs import CloudJobState, CloudJobStore, FileCloudJobTracker
    from app.transcription_models import FileStatus, FileTask

    source = tmp_path / "demo.wav"
    source.write_bytes(b"audio")
    output = tmp_path / "demo.json"
    output.write_text("{}", encoding="utf-8")
    tracker = FileCloudJobTracker(
        CloudJobStore(tmp_path / "jobs.sqlite3")
    )
    task = FileTask(file_path=source)
    tracker.register(task, route={"audio": "OpenRouter"})
    tracker.begin(task)
    task.status = FileStatus.COMPLETED
    task.progress = 100
    task.output_files = {"json": output}

    completed = tracker.sync(task)

    assert completed.state is CloudJobState.COMPLETED
    assert completed.result == {
        "outputs": {"json": str(output)},
        "warning": None,
    }


def test_idempotency_key_cannot_be_reused_for_different_input(
    tmp_path: Path,
) -> None:
    from app.cloud_jobs import CloudJobStore, IdempotencyConflictError

    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    store = CloudJobStore(tmp_path / "jobs.sqlite3")
    store.create_or_get(
        idempotency_key="same-key",
        source_path=first,
        operation="file_processing",
        route={"audio": "OpenRouter"},
    )

    with pytest.raises(IdempotencyConflictError):
        store.create_or_get(
            idempotency_key="same-key",
            source_path=second,
            operation="file_processing",
            route={"audio": "MindType Cloud"},
        )


def test_compatibility_tracker_uses_durable_processing_path(tmp_path: Path) -> None:
    from app.cloud_jobs import CloudJobStore, FileCloudJobTracker
    from app.transcription_models import FileTask

    original = tmp_path / "original.wav"
    original.write_bytes(b"original")
    durable = tmp_path / "spool" / "operation" / "source.wav"
    durable.parent.mkdir(parents=True)
    durable.write_bytes(b"durable")
    tracker = FileCloudJobTracker(
        CloudJobStore(tmp_path / "jobs.sqlite3")
    )
    task = FileTask(
        file_path=original,
        source_asset_path=durable,
    )

    registered = tracker.register(task, route={"audio": "OpenRouter"})

    assert registered.source_path == durable.resolve()
