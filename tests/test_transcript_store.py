from pathlib import Path

from app.transcription_models import TranscriptionResult, TranscriptionSegment


def make_result(source: Path) -> TranscriptionResult:
    return TranscriptionResult(
        file_path=source,
        segments=[
            TranscriptionSegment(
                start=0.0,
                end=2.5,
                text="Доброе утро",
                speaker="SPEAKER_00",
                words=[{"word": "Доброе", "start": 0.0, "end": 1.0}],
            ),
            TranscriptionSegment(
                start=2.5,
                end=5.0,
                text="Начинаем встречу",
                speaker="SPEAKER_01",
            ),
        ],
        detected_language="ru",
        language_probability=0.98,
        duration=5.0,
        model_used="cloud-whisper",
        processed_text="Доброе утро. Начинаем встречу.",
        speaker_names={
            "SPEAKER_00": "Анна",
            "SPEAKER_01": "Борис",
        },
        num_speakers=2,
    )


def test_saved_result_can_be_loaded_by_a_new_store(tmp_path):
    from app.transcript_store import TranscriptStore

    source = tmp_path / "moved-after-processing.mp3"
    store_path = tmp_path / "mindtype.db"
    saved = TranscriptStore(store_path).save_result(make_result(source))

    # The transcript is a durable artifact; its source may no longer exist.
    assert not source.exists()
    loaded = TranscriptStore(store_path).get_document(saved.id)

    assert loaded is not None
    assert loaded.id == saved.id
    assert loaded.source_path == source.resolve()
    assert loaded.detected_language == "ru"
    assert loaded.language_probability == 0.98
    assert loaded.duration == 5.0
    assert loaded.model_used == "cloud-whisper"
    assert loaded.current_revision.number == 1
    assert loaded.current_revision.processed_text == "Доброе утро. Начинаем встречу."
    assert loaded.current_revision.speaker_names == {
        "SPEAKER_00": "Анна",
        "SPEAKER_01": "Борис",
    }
    assert [segment.text for segment in loaded.current_revision.segments] == [
        "Доброе утро",
        "Начинаем встречу",
    ]
    assert loaded.current_revision.segments[0].words == [
        {"word": "Доброе", "start": 0.0, "end": 1.0}
    ]


def test_renaming_speakers_creates_an_immutable_revision(tmp_path):
    from app.transcript_store import TranscriptStore

    store = TranscriptStore(tmp_path / "mindtype.db")
    saved = store.save_result(make_result(tmp_path / "meeting.mp3"))

    renamed = store.rename_speakers(
        saved.id,
        {
            "SPEAKER_00": "Мария",
            "SPEAKER_01": "Дмитрий",
        },
    )

    assert [revision.number for revision in renamed.revisions] == [1, 2]
    assert renamed.revisions[0].speaker_names == {
        "SPEAKER_00": "Анна",
        "SPEAKER_01": "Борис",
    }
    assert renamed.current_revision.speaker_names == {
        "SPEAKER_00": "Мария",
        "SPEAKER_01": "Дмитрий",
    }
    assert renamed.revisions[0].segments == renamed.current_revision.segments

def test_two_summary_variants_share_one_transcript_revision(tmp_path):
    from app.transcript_store import TranscriptStore

    store = TranscriptStore(tmp_path / "mindtype.db")
    saved = store.save_result(make_result(tmp_path / "meeting.mp3"))
    revision_id = saved.current_revision.id

    store.add_summary_variant(
        document_id=saved.id,
        revision_id=revision_id,
        template_id="call",
        template_name="Созвон",
        template_version=1,
        template_prompts={"system": "system", "short": "short"},
        content="Первый вариант",
        provider="mindtype_cloud",
        model="cloud-default",
    )
    store.add_summary_variant(
        document_id=saved.id,
        revision_id=revision_id,
        template_id="user-1",
        template_name="Письмо клиенту",
        template_version=3,
        template_prompts={"system": "writer", "short": "letter"},
        content="Второй вариант",
        provider="mindtype_cloud",
        model="cloud-default",
    )

    loaded = store.get_document(saved.id)

    assert loaded is not None
    assert len(loaded.revisions) == 1
    assert [variant.content for variant in loaded.summary_variants] == [
        "Первый вариант",
        "Второй вариант",
    ]
    assert {
        variant.revision_id for variant in loaded.summary_variants
    } == {revision_id}

def test_existing_result_summary_is_imported_as_first_variant(tmp_path):
    from app.transcript_store import TranscriptStore

    result = make_result(tmp_path / "meeting.mp3")
    result.summary = "## Решения\n- Запустить пилот"
    result.summary_metrics = {"input_tokens": 120}
    result.summary_preset_name = "Созвон"

    saved = TranscriptStore(tmp_path / "mindtype.db").save_result(result)

    assert len(saved.summary_variants) == 1
    imported = saved.summary_variants[0]
    assert imported.content == result.summary
    assert imported.template_id == "legacy"
    assert imported.template_name == "Созвон"
    assert imported.metrics == {"input_tokens": 120}

def test_summary_variant_keeps_its_template_snapshot(tmp_path):
    from app.transcript_store import TranscriptStore

    store_path = tmp_path / "mindtype.db"
    store = TranscriptStore(store_path)
    saved = store.save_result(make_result(tmp_path / "meeting.mp3"))
    prompts = {
        "system": "Пиши только факты",
        "short": "Сделай протокол",
    }

    store.add_summary_variant(
        document_id=saved.id,
        revision_id=saved.current_revision.id,
        template_id="user-1",
        template_name="Мой протокол",
        template_version=4,
        template_prompts=prompts,
        content="Сохранённый результат",
        provider="mindtype_cloud",
        model="cloud-default",
    )
    prompts["system"] = "Новая инструкция"

    loaded = TranscriptStore(store_path).get_document(saved.id)

    assert loaded is not None
    assert loaded.summary_variants[0].template_version == 4
    assert loaded.summary_variants[0].template_prompts == {
        "system": "Пиши только факты",
        "short": "Сделай протокол",
    }

def test_unknown_schema_version_is_rejected(tmp_path):
    import sqlite3

    import pytest

    from app.transcript_store import TranscriptStore, UnsupportedSchemaVersion

    store_path = tmp_path / "future.db"
    with sqlite3.connect(store_path) as connection:
        connection.execute("CREATE TABLE schema_info (version INTEGER NOT NULL)")
        connection.execute("INSERT INTO schema_info (version) VALUES (999)")

    with pytest.raises(UnsupportedSchemaVersion, match="999"):
        TranscriptStore(store_path)

def test_corrupt_revision_data_reports_the_document(tmp_path):
    import sqlite3

    import pytest

    from app.transcript_store import CorruptTranscriptData, TranscriptStore

    store_path = tmp_path / "mindtype.db"
    store = TranscriptStore(store_path)
    saved = store.save_result(make_result(tmp_path / "meeting.mp3"))

    with sqlite3.connect(store_path) as connection:
        connection.execute(
            "UPDATE transcript_revisions SET segments_json = ? WHERE document_id = ?",
            ("{broken", saved.id),
        )

    with pytest.raises(CorruptTranscriptData, match=saved.id):
        store.get_document(saved.id)

def test_documents_are_listed_newest_first(tmp_path):
    from datetime import datetime

    from app.transcript_store import TranscriptStore

    store = TranscriptStore(tmp_path / "mindtype.db")
    older = make_result(tmp_path / "older.mp3")
    older.transcription_date = datetime(2026, 1, 1, 10, 0)
    newer = make_result(tmp_path / "newer.mp3")
    newer.transcription_date = datetime(2026, 1, 2, 10, 0)

    older_document = store.save_result(older)
    newer_document = store.save_result(newer)

    assert [document.id for document in store.list_documents()] == [
        newer_document.id,
        older_document.id,
    ]

def test_completed_task_is_saved_to_the_transcript_library(tmp_path):
    from app.transcript_store import TranscriptStore, persist_completed_task
    from app.transcription_models import FileStatus, FileTask

    store = TranscriptStore(tmp_path / "mindtype.db")
    task = FileTask(
        file_path=tmp_path / "meeting.mp3",
        status=FileStatus.COMPLETED,
        result=make_result(tmp_path / "meeting.mp3"),
    )

    saved = persist_completed_task(store, task)

    assert saved is not None
    assert task.library_document_id == saved.id
    assert [document.id for document in store.list_documents()] == [saved.id]

def test_store_failure_does_not_change_completed_task_status(tmp_path):
    from app.transcript_store import persist_completed_task
    from app.transcription_models import FileStatus, FileTask

    class FailingStore:
        def save_result(self, result):
            raise OSError("disk full")

    task = FileTask(
        file_path=tmp_path / "meeting.mp3",
        status=FileStatus.COMPLETED,
        result=make_result(tmp_path / "meeting.mp3"),
    )

    saved = persist_completed_task(FailingStore(), task)

    assert saved is None
    assert task.status == FileStatus.COMPLETED
    assert task.library_document_id is None
    assert "библиотек" in task.warning.lower()


def test_store_releases_database_file_after_operations_on_windows(tmp_path):
    import sys

    import pytest

    from app.transcript_store import TranscriptStore

    if sys.platform != "win32":
        pytest.skip("Windows verifies SQLite file handles by moving the database")

    store_path = tmp_path / "mindtype.db"
    store = TranscriptStore(store_path)
    store.save_result(make_result(tmp_path / "meeting.mp3"))
    store.list_documents()

    moved_path = tmp_path / "mindtype-moved.db"
    store_path.replace(moved_path)

    assert moved_path.exists()
