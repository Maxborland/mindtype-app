import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from app.transcript_store import TranscriptStore
from app.transcription_models import TranscriptionResult, TranscriptionSegment


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app



def save_sample_document(store, source):
    return store.save_result(
        TranscriptionResult(
            file_path=source,
            segments=[
                TranscriptionSegment(
                    start=0.0,
                    end=2.0,
                    text="Доброе утро",
                    speaker="SPEAKER_00",
                ),
                TranscriptionSegment(
                    start=62.0,
                    end=65.0,
                    text="Начинаем встречу",
                    speaker="SPEAKER_01",
                ),
            ],
            detected_language="ru",
            language_probability=0.97,
            duration=65.0,
            model_used="mindtype-cloud",
            speaker_names={
                "SPEAKER_00": "Анна",
                "SPEAKER_01": "Борис",
            },
            num_speakers=2,
        )
    )
def test_empty_library_offers_new_transcription_action(tmp_path, qapp):
    from app.ui.transcript_library import TranscriptLibraryWidget

    requested = []
    widget = TranscriptLibraryWidget(
        TranscriptStore(tmp_path / "mindtype.db"),
        translate_func=lambda key: key,
    )
    widget.new_transcription_requested.connect(lambda: requested.append(True))
    widget.show()
    qapp.processEvents()

    assert widget.document_list.count() == 0
    assert widget.empty_state.isVisible()

    widget.new_transcription_button.click()

    assert requested == [True]
    widget.close()


def test_selected_document_renders_saved_segments_without_source_file(tmp_path, qapp):
    from app.ui.transcript_library import TranscriptLibraryWidget

    store = TranscriptStore(tmp_path / "mindtype.db")
    source = tmp_path / "already-moved.mp3"
    save_sample_document(store, source)
    assert not source.exists()

    widget = TranscriptLibraryWidget(store, translate_func=lambda key: key)
    widget.show()
    widget.document_list.setCurrentRow(0)
    qapp.processEvents()

    assert "already-moved.mp3" in widget.metadata_label.text()
    assert "ru" in widget.metadata_label.text()
    assert "1" in widget.metadata_label.text()
    assert widget.transcript_output.toPlainText() == (
        "[00:00] Анна: Доброе утро\n"
        "[01:02] Борис: Начинаем встречу"
    )
    widget.close()


def test_saving_speaker_names_creates_and_renders_new_revision(tmp_path, qapp):
    from app.ui.transcript_library import TranscriptLibraryWidget

    store = TranscriptStore(tmp_path / "mindtype.db")
    saved = save_sample_document(store, tmp_path / "meeting.mp3")
    widget = TranscriptLibraryWidget(store, translate_func=lambda key: key)
    widget.show()
    qapp.processEvents()

    widget.speaker_name_edits["SPEAKER_00"].setText("Мария")
    widget.speaker_name_edits["SPEAKER_01"].setText("Дмитрий")
    widget.save_speaker_names_button.click()
    qapp.processEvents()

    updated = store.get_document(saved.id)
    assert updated is not None
    assert [revision.number for revision in updated.revisions] == [1, 2]
    assert "[00:00] Мария: Доброе утро" in widget.transcript_output.toPlainText()
    assert "[01:02] Дмитрий: Начинаем встречу" in (
        widget.transcript_output.toPlainText()
    )
    assert "2" in widget.metadata_label.text()
    widget.close()


def test_summary_variants_can_be_selected(tmp_path, qapp):
    from app.ui.transcript_library import TranscriptLibraryWidget

    store = TranscriptStore(tmp_path / "mindtype.db")
    saved = save_sample_document(store, tmp_path / "meeting.mp3")
    for template_id, template_name, version, content in (
        ("call", "Созвон", 1, "Первый протокол"),
        ("user-1", "Письмо клиенту", 3, "Второй документ"),
    ):
        store.add_summary_variant(
            document_id=saved.id,
            revision_id=saved.current_revision.id,
            template_id=template_id,
            template_name=template_name,
            template_version=version,
            template_prompts={"system": template_name},
            content=content,
            provider="mindtype_cloud",
            model="cloud-default",
        )

    widget = TranscriptLibraryWidget(store, translate_func=lambda key: key)
    widget.show()
    qapp.processEvents()

    assert widget.summary_variant_list.count() == 2
    assert widget.summary_variant_list.item(0).text() == "Созвон"
    assert widget.summary_output.toPlainText() == "Первый протокол"

    widget.summary_variant_list.setCurrentRow(1)
    qapp.processEvents()

    assert widget.summary_output.toPlainText() == "Второй документ"
    assert "Письмо клиенту" in widget.summary_metadata_label.text()
    assert "3" in widget.summary_metadata_label.text()
    widget.close()


def test_create_document_action_targets_selected_transcript(tmp_path, qapp):
    from app.ui.transcript_library import TranscriptLibraryWidget

    store = TranscriptStore(tmp_path / "mindtype.db")
    saved = save_sample_document(store, tmp_path / "meeting.mp3")
    widget = TranscriptLibraryWidget(store, translate_func=lambda key: key)
    requested = []
    widget.document_generation_requested.connect(requested.append)
    widget.show()
    qapp.processEvents()

    widget.detail_tabs.setCurrentIndex(2)
    widget.create_document_button.click()

    assert requested == [saved.id]
    widget.set_document_generation_busy(True)
    assert not widget.create_document_button.isEnabled()
    assert widget.create_document_button.text() == "library_creating_document"
    widget.set_document_generation_busy(False)
    assert widget.create_document_button.isEnabled()
    widget.close()
