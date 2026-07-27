from pathlib import Path


def test_operation_store_persists_provider_neutral_record(tmp_path: Path) -> None:
    from app.operation_models import OperationKind, OperationStage, OperationStatus
    from app.operation_store import OperationStore

    database = tmp_path / "operations.sqlite3"
    source = tmp_path / "source.wav"
    source.write_bytes(b"audio")
    store = OperationStore(database)

    created = store.create(
        operation_id="operation-1",
        kind=OperationKind.FILE,
        source_asset_path=source,
        source_sha256="a" * 64,
        route={"transcription": {"provider": "mindtype_cloud", "model": "auto"}},
        stage=OperationStage.PERSIST,
    )
    reopened = OperationStore(database).get("operation-1")

    assert reopened == created
    assert reopened.status is OperationStatus.CREATED
    assert reopened.source_asset_path == source.resolve()
    assert store.schema_version == 2


def test_operation_store_releases_windows_database_handle(
    tmp_path: Path,
) -> None:
    from app.operation_store import OperationStore

    database = tmp_path / "operations.sqlite3"
    store = OperationStore(database)
    assert store.schema_version == 2

    moved = tmp_path / "operations-moved.sqlite3"
    database.replace(moved)
    moved.unlink()

    assert not moved.exists()


def test_operation_store_transition_persists_attempt_and_recovery_metadata(
    tmp_path: Path,
) -> None:
    from datetime import datetime, timedelta, timezone

    from app.operation_models import OperationKind, OperationStage, OperationStatus
    from app.operation_store import OperationStore

    source = tmp_path / "source.wav"
    source.write_bytes(b"audio")
    database = tmp_path / "operations.sqlite3"
    store = OperationStore(database)
    store.create(
        operation_id="operation-2",
        kind=OperationKind.DICTATION,
        source_asset_path=source,
        route={"transcription": {"provider": "mindtype_cloud", "model": "auto"}},
        stage=OperationStage.PERSIST,
    )
    retry_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    deadline = datetime.now(timezone.utc) + timedelta(days=7)

    running = store.transition(
        "operation-2",
        OperationStatus.RUNNING,
        stage=OperationStage.UPLOAD,
        new_attempt=True,
        progress=20,
        server_job_ids={"transcription": "server-job-1"},
    )
    store.transition(
        "operation-2",
        OperationStatus.RETRYABLE,
        last_error_code="RATE_LIMITED",
        retry_after=retry_at,
        retention_deadline=deadline,
    )
    reopened = OperationStore(database).get("operation-2")

    assert running.attempt_count == 1
    assert reopened.status is OperationStatus.RETRYABLE
    assert reopened.stage is OperationStage.UPLOAD
    assert reopened.progress == 20
    assert reopened.server_job_ids == {"transcription": "server-job-1"}
    assert reopened.last_error_code == "RATE_LIMITED"
    assert reopened.retry_after == retry_at
    assert reopened.retention_deadline == deadline


def test_guarded_transition_ignores_stale_callback(tmp_path: Path) -> None:
    from app.operation_models import OperationKind, OperationStage, OperationStatus
    from app.operation_store import OperationStore

    source = tmp_path / "source.wav"
    source.write_bytes(b"audio")
    store = OperationStore(tmp_path / "operations.sqlite3")
    store.create(
        operation_id="current-operation",
        kind=OperationKind.DICTATION,
        source_asset_path=source,
        route={"transcription": {"provider": "local", "model": "tiny"}},
        stage=OperationStage.TRANSCRIBE,
    )

    result = store.guarded_transition(
        callback_operation_id="stale-operation",
        active_operation_id="current-operation",
        status=OperationStatus.COMPLETED,
        stage=OperationStage.INSERT,
    )

    assert result is None
    assert store.get("current-operation").status is OperationStatus.CREATED


def test_legacy_cloud_jobs_migrate_once_with_backup_and_state_mapping(
    tmp_path: Path,
) -> None:
    from app.cloud_jobs import CloudJobState, CloudJobStore
    from app.operation_models import OperationStatus
    from app.operation_store import OperationStore

    source = tmp_path / "meeting.wav"
    source.write_bytes(b"audio")
    database = tmp_path / "cloud_jobs.sqlite3"
    legacy = CloudJobStore(database)
    inflight = legacy.create_or_get(
        idempotency_key="operation-inflight",
        source_path=source,
        operation="file_processing",
        route={"audio": "MindType Cloud", "summary": "OpenRouter"},
    )
    legacy.transition(
        inflight.job_id,
        CloudJobState.PROCESSING,
        progress=45,
        remote_job_id="remote-transcription-1",
    )
    completed = legacy.create_or_get(
        idempotency_key="operation-completed",
        source_path=source,
        operation="file_processing",
        route={"audio": "MindType Cloud"},
    )
    legacy.transition(completed.job_id, CloudJobState.PROCESSING)
    legacy.transition(
        completed.job_id,
        CloudJobState.COMPLETED,
        progress=100,
        result={"outputs": {"json": "legacy-result.json"}},
    )

    migrated = OperationStore(database)
    reopened = OperationStore(database)

    assert migrated.get("operation-inflight").status is OperationStatus.RETRYABLE
    assert migrated.get("operation-inflight").progress == 45
    assert migrated.get("operation-inflight").server_job_ids == {
        "legacy": "remote-transcription-1"
    }
    recovered_completed = migrated.get("operation-completed")
    assert recovered_completed.status is OperationStatus.RETRYABLE
    assert (
        recovered_completed.last_error_code
        == "LEGACY_RESULT_REQUIRES_RECOVERY"
    )
    assert reopened.count() == 2
    assert len(list(tmp_path.glob("cloud_jobs.v1-backup-*.sqlite3"))) == 1


def test_desktop_runtime_uses_only_operation_store_for_lifecycle() -> None:
    """Legacy cloud_jobs may be read by migrations, but never written by the UI."""
    main_source = (
        Path(__file__).resolve().parents[1] / "app" / "main.py"
    ).read_text(encoding="utf-8")

    assert "CloudJobStore" not in main_source
    assert "FileCloudJobTracker" not in main_source
    assert "_cloud_job_tracker" not in main_source


def test_completed_requires_matching_persisted_canonical_result(
    tmp_path: Path,
) -> None:
    import json

    import pytest

    from app.operation_models import OperationKind, OperationStage, OperationStatus
    from app.operation_store import IncompleteOperationError, OperationStore
    from app.result_schema import write_canonical_result
    from tests.test_result_schema import canonical_result

    source = tmp_path / "source.wav"
    source.write_bytes(b"audio")
    store = OperationStore(tmp_path / "operations.sqlite3")
    store.create(
        operation_id="operation-result",
        kind=OperationKind.FILE,
        source_asset_path=source,
        route={"transcription": {"provider": "mindtype_cloud", "model": "auto"}},
        stage=OperationStage.PERSIST,
    )
    store.transition(
        "operation-result",
        OperationStatus.RUNNING,
        stage=OperationStage.TRANSCRIBE,
        new_attempt=True,
    )

    with pytest.raises(IncompleteOperationError):
        store.transition(
            "operation-result",
            OperationStatus.COMPLETED,
            stage=OperationStage.EXPORT,
        )

    result_path = write_canonical_result(
        tmp_path / "result.json",
        canonical_result("operation-result"),
        expected_operation_id="operation-result",
    )
    completed = store.transition(
        "operation-result",
        OperationStatus.COMPLETED,
        stage=OperationStage.EXPORT,
        canonical_result_path=result_path,
        progress=100,
    )

    assert completed.canonical_result_path == result_path.resolve()
    assert json.loads(result_path.read_text(encoding="utf-8"))["operation_id"] == (
        "operation-result"
    )


def test_restart_recovery_preserves_source_and_exposes_manual_retry(
    tmp_path: Path,
) -> None:
    from app.operation_models import OperationKind, OperationStage, OperationStatus
    from app.operation_store import OperationStore

    source = tmp_path / "source.wav"
    source.write_bytes(b"audio")
    missing_source = tmp_path / "missing.wav"
    store = OperationStore(tmp_path / "operations.sqlite3")
    for operation_id, path in (
        ("running-operation", source),
        ("missing-operation", missing_source),
    ):
        store.create(
            operation_id=operation_id,
            kind=OperationKind.FILE,
            source_asset_path=path,
            route={"transcription": {"provider": "mindtype_cloud", "model": "auto"}},
            stage=OperationStage.PERSIST,
        )
        store.transition(
            operation_id,
            OperationStatus.RUNNING,
            stage=OperationStage.UPLOAD,
            new_attempt=True,
        )

    recovered = store.recover_incomplete()

    assert [operation.operation_id for operation in recovered] == [
        "running-operation"
    ]
    assert recovered[0].status is OperationStatus.RETRYABLE
    assert recovered[0].retention_deadline is not None
    assert store.get("missing-operation").status is OperationStatus.FAILED
    assert [operation.operation_id for operation in store.list_retryable()] == [
        "running-operation"
    ]


def test_restart_does_not_adopt_result_for_a_different_source(
    tmp_path: Path,
) -> None:
    from app.operation_models import OperationKind, OperationStage, OperationStatus
    from app.operation_store import OperationStore
    from app.result_schema import write_canonical_result
    from tests.test_result_schema import canonical_result

    operation_dir = tmp_path / "operation-source-mismatch"
    operation_dir.mkdir()
    source = operation_dir / "source.wav"
    source.write_bytes(b"audio")
    store = OperationStore(tmp_path / "operations.sqlite3")
    store.create(
        operation_id="operation-source-mismatch",
        kind=OperationKind.FILE,
        source_asset_path=source,
        source_sha256="a" * 64,
        route={"transcription": {"provider": "local", "model": "tiny"}},
        stage=OperationStage.PERSIST,
    )
    store.transition(
        "operation-source-mismatch",
        OperationStatus.RUNNING,
        stage=OperationStage.TRANSCRIBE,
        new_attempt=True,
    )
    payload = canonical_result("operation-source-mismatch")
    payload["source"]["sha256"] = "b" * 64
    write_canonical_result(
        operation_dir / "result.json",
        payload,
        expected_operation_id="operation-source-mismatch",
    )

    recovered = store.recover_incomplete()

    assert [item.operation_id for item in recovered] == [
        "operation-source-mismatch"
    ]
    assert recovered[0].status is OperationStatus.RETRYABLE
    assert recovered[0].canonical_result_path is None


def test_retry_route_can_be_replaced_before_user_starts_new_attempt(
    tmp_path: Path,
) -> None:
    from app.operation_models import OperationKind, OperationStage, OperationStatus
    from app.operation_store import OperationStore

    source = tmp_path / "source.wav"
    source.write_bytes(b"audio")
    store = OperationStore(tmp_path / "operations.sqlite3")
    store.create(
        operation_id="route-retry",
        kind=OperationKind.FILE,
        source_asset_path=source,
        route={"audio": "OpenRouter"},
        stage=OperationStage.PERSIST,
    )
    store.transition("route-retry", OperationStatus.RETRYABLE)

    updated = store.update_route(
        "route-retry",
        {"transcription": {"provider": "local", "model": "tiny"}},
    )

    assert updated.route == {
        "transcription": {"provider": "local", "model": "tiny"}
    }
