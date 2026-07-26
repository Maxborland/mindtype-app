from __future__ import annotations

from pathlib import Path

import pytest


class FakeCloudClient:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.upload = {
            "id": "upload-1",
            "upload_token": "upload-token",
            "uploaded_parts": [],
        }
        self.job = {"id": "job-1", "state": "queued"}
        self.result = None
        self.ack_error = None
        self.on_ack = None

    def create_upload(self, source_path, *, operation_id):
        self.calls.append(("create_upload", operation_id))
        return self.upload

    def upload_file(
        self,
        source_path,
        *,
        operation_id,
        remote_upload_id=None,
    ):
        self.calls.append(
            ("upload_file", operation_id, remote_upload_id)
        )
        return {"id": remote_upload_id, "state": "complete"}

    def create_transcription(
        self,
        *,
        upload_id,
        operation_id,
        options,
    ):
        self.calls.append(
            ("create_transcription", upload_id, operation_id, dict(options))
        )
        return self.job

    def get_transcription(self, job_id):
        self.calls.append(("get_transcription", job_id))
        return self.job

    def get_transcription_result(self, job_id, *, expected_operation_id=None):
        self.calls.append(
            ("get_transcription_result", job_id, expected_operation_id)
        )
        return self.result

    def acknowledge_transcription(self, job_id):
        self.calls.append(("acknowledge_transcription", job_id))
        if self.on_ack is not None:
            self.on_ack()
        if self.ack_error is not None:
            error = self.ack_error
            self.ack_error = None
            raise error

    def cancel_transcription(self, job_id):
        self.calls.append(("cancel_transcription", job_id))
        return {"id": job_id, "state": "cancelled"}


def operation_fixture(tmp_path: Path):
    from app.operation_coordinator import OperationCoordinator
    from app.operation_store import OperationStore
    from app.spool import SpoolManager

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
            }
        },
        operation_id="operation-cloud",
    )
    return coordinator, operation


def test_executor_persists_upload_and_job_before_polling(tmp_path: Path) -> None:
    from app.operation_models import OperationStage, OperationStatus
    from app.providers.mindtype_cloud import MindTypeCloudExecutor

    coordinator, operation = operation_fixture(tmp_path)
    client = FakeCloudClient()
    executor = MindTypeCloudExecutor(
        client=client,
        coordinator=coordinator,
    )

    updated = executor.advance_transcription(
        operation.operation_id,
        options={"language": "ru"},
    )

    assert updated.status is OperationStatus.RUNNING
    assert updated.stage is OperationStage.TRANSCRIBE
    assert updated.server_job_ids == {
        "upload": "upload-1",
        "transcription": "job-1",
    }
    assert client.calls == [
        ("create_upload", "operation-cloud"),
        ("upload_file", "operation-cloud", "upload-1"),
        (
            "create_transcription",
            "upload-1",
            "operation-cloud",
            {"language": "ru"},
        ),
    ]


def test_executor_restart_polls_existing_job_without_upload_or_post(
    tmp_path: Path,
) -> None:
    from app.operation_models import OperationStage, OperationStatus
    from app.providers.mindtype_cloud import MindTypeCloudExecutor

    coordinator, operation = operation_fixture(tmp_path)
    running = coordinator.begin_attempt(
        operation.operation_id,
        stage=OperationStage.TRANSCRIBE,
    )
    coordinator.store.transition(
        running.operation_id,
        OperationStatus.RUNNING,
        server_job_ids={
            "upload": "upload-existing",
            "transcription": "job-existing",
        },
    )
    client = FakeCloudClient()
    client.job = {"id": "job-existing", "state": "running"}
    executor = MindTypeCloudExecutor(
        client=client,
        coordinator=coordinator,
    )

    updated = executor.advance_transcription(
        operation.operation_id,
        options={},
    )

    assert updated.status is OperationStatus.RUNNING
    assert client.calls == [("get_transcription", "job-existing")]


def test_success_is_saved_before_ack_and_then_source_is_cleaned(
    tmp_path: Path,
) -> None:
    from app.operation_models import OperationStatus
    from app.providers.mindtype_cloud import MindTypeCloudExecutor
    from tests.test_result_schema import canonical_result

    coordinator, operation = operation_fixture(tmp_path)
    client = FakeCloudClient()
    client.job = {"id": "job-1", "state": "succeeded"}
    client.result = canonical_result(operation.operation_id)
    client.result["source"]["sha256"] = operation.source_sha256

    def assert_saved_before_ack() -> None:
        saved = coordinator.store.get(operation.operation_id)
        assert saved.canonical_result_path.is_file()

    client.on_ack = assert_saved_before_ack
    executor = MindTypeCloudExecutor(
        client=client,
        coordinator=coordinator,
    )

    completed = executor.advance_transcription(
        operation.operation_id,
        options={},
    )

    assert completed.status is OperationStatus.COMPLETED
    assert completed.canonical_result_path.is_file()
    assert operation.source_asset_path.exists() is False
    assert client.calls[-2:] == [
        (
            "get_transcription_result",
            "job-1",
            operation.operation_id,
        ),
        ("acknowledge_transcription", "job-1"),
    ]


def test_failed_ack_keeps_completed_result_and_source_for_retry(
    tmp_path: Path,
) -> None:
    from app.operation_models import OperationStatus
    from app.providers.mindtype_cloud import (
        CloudAPIError,
        CloudErrorCode,
        MindTypeCloudExecutor,
    )
    from tests.test_result_schema import canonical_result

    coordinator, operation = operation_fixture(tmp_path)
    client = FakeCloudClient()
    client.job = {"id": "job-1", "state": "succeeded"}
    client.result = canonical_result(operation.operation_id)
    client.result["source"]["sha256"] = operation.source_sha256
    client.ack_error = CloudAPIError(
        CloudErrorCode.PROVIDER_UNAVAILABLE,
        "offline",
        retryable=True,
    )
    executor = MindTypeCloudExecutor(
        client=client,
        coordinator=coordinator,
    )

    with pytest.raises(CloudAPIError):
        executor.advance_transcription(operation.operation_id, options={})

    saved = coordinator.store.get(operation.operation_id)
    assert saved.status is OperationStatus.COMPLETED
    assert saved.canonical_result_path.is_file()
    assert saved.source_asset_path.is_file()

    retried = executor.acknowledge_completed(operation.operation_id)

    assert retried.status is OperationStatus.COMPLETED
    assert retried.source_asset_path.exists() is False
    assert [
        call for call in client.calls if call[0] == "acknowledge_transcription"
    ] == [
        ("acknowledge_transcription", "job-1"),
        ("acknowledge_transcription", "job-1"),
    ]


def test_result_for_different_source_is_failed_without_ack(
    tmp_path: Path,
) -> None:
    from app.operation_models import OperationStatus
    from app.providers.mindtype_cloud import MindTypeCloudExecutor
    from tests.test_result_schema import canonical_result

    coordinator, operation = operation_fixture(tmp_path)
    client = FakeCloudClient()
    client.job = {"id": "job-1", "state": "succeeded"}
    client.result = canonical_result(operation.operation_id)
    client.result["source"]["sha256"] = "a" * 64
    executor = MindTypeCloudExecutor(
        client=client,
        coordinator=coordinator,
    )

    failed = executor.advance_transcription(
        operation.operation_id,
        options={},
    )

    assert failed.status is OperationStatus.FAILED
    assert failed.last_error_code == "SCHEMA_UNSUPPORTED"
    assert operation.source_asset_path.is_file()
    assert not any(
        call[0] == "acknowledge_transcription" for call in client.calls
    )


def test_insufficient_credits_moves_operation_to_retryable(
    tmp_path: Path,
) -> None:
    from app.operation_models import OperationStatus
    from app.providers.mindtype_cloud import (
        CloudAPIError,
        CloudErrorCode,
        MindTypeCloudExecutor,
    )

    coordinator, operation = operation_fixture(tmp_path)
    client = FakeCloudClient()
    client.create_upload = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        CloudAPIError(
            CloudErrorCode.INSUFFICIENT_CREDITS,
            "top up",
            retryable=False,
        )
    )
    executor = MindTypeCloudExecutor(
        client=client,
        coordinator=coordinator,
    )

    updated = executor.advance_transcription(
        operation.operation_id,
        options={},
    )

    assert updated.status is OperationStatus.RETRYABLE
    assert updated.last_error_code == "INSUFFICIENT_CREDITS"


def test_cancel_uses_existing_job_and_finishes_only_after_response(
    tmp_path: Path,
) -> None:
    from app.operation_models import OperationStage, OperationStatus
    from app.providers.mindtype_cloud import MindTypeCloudExecutor

    coordinator, operation = operation_fixture(tmp_path)
    running = coordinator.begin_attempt(
        operation.operation_id,
        stage=OperationStage.TRANSCRIBE,
    )
    coordinator.store.transition(
        running.operation_id,
        OperationStatus.RUNNING,
        server_job_ids={"transcription": "job-1"},
    )
    client = FakeCloudClient()
    executor = MindTypeCloudExecutor(
        client=client,
        coordinator=coordinator,
    )

    cancelled = executor.cancel(operation.operation_id)

    assert cancelled.status is OperationStatus.CANCELLED
    assert client.calls == [("cancel_transcription", "job-1")]
