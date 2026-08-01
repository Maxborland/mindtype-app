"""End-to-end QA for product scenarios claimed by the landing page.

The external STT/LLM provider is represented by a deterministic boundary fake.
Everything owned by MindType—revision handling, prompts, multiple outputs, and
durable reopening—uses the production implementation.
"""

from pathlib import Path

from app.transcript_documents import SummaryTemplate, create_summary_document
from app.transcript_store import TranscriptStore
from app.transcription_models import TranscriptionResult, TranscriptionSegment


def test_transcript_to_speakers_templates_and_multiple_documents(tmp_path):
    source = tmp_path / "multilingual-meeting.mp4"
    source.write_bytes(b"fixture-media")
    database = tmp_path / "mindtype.db"
    store = TranscriptStore(database)

    saved = store.save_result(
        TranscriptionResult(
            file_path=source,
            segments=[
                TranscriptionSegment(
                    start=0.0,
                    end=2.5,
                    text="Начинаем встречу",
                    speaker="SPEAKER_00",
                ),
                TranscriptionSegment(
                    start=2.5,
                    end=5.0,
                    text="Let us confirm the next step",
                    speaker="SPEAKER_01",
                ),
            ],
            detected_language="multilingual",
            language_probability=0.93,
            duration=5.0,
            model_used="provider-boundary-fixture",
            speaker_names={
                "SPEAKER_00": "Спикер 1",
                "SPEAKER_01": "Speaker 2",
            },
            num_speakers=2,
        )
    )

    renamed = store.rename_speakers(
        saved.id,
        {
            "SPEAKER_00": "Анна",
            "SPEAKER_01": "Ben",
        },
    )
    assert [revision.number for revision in renamed.revisions] == [1, 2]
    assert renamed.revisions[0].speaker_names["SPEAKER_00"] == "Спикер 1"
    assert renamed.current_revision.speaker_names["SPEAKER_00"] == "Анна"

    generation_calls = []

    def generate(text: str, prompts: dict[str, str]):
        generation_calls.append((text, prompts))
        return f"{prompts['format']}\n{text}", {"fixture": True}

    for template in (
        SummaryTemplate(
            id="meeting-notes",
            name="Протокол",
            version=1,
            prompts={"format": "Решения и следующие шаги"},
            provider="mindtype_cloud",
            model="provider-boundary-fixture",
        ),
        SummaryTemplate(
            id="customer-follow-up",
            name="Follow-up",
            version=3,
            prompts={"format": "Письмо клиенту"},
            provider="mindtype_cloud",
            model="provider-boundary-fixture",
        ),
    ):
        create_summary_document(store, saved.id, template, generate)

    source.unlink()
    reopened = TranscriptStore(database).get_document(saved.id)

    assert reopened is not None
    assert not reopened.source_path.exists()
    assert len(reopened.revisions) == 2
    assert [variant.template_name for variant in reopened.summary_variants] == [
        "Протокол",
        "Follow-up",
    ]
    assert reopened.summary_variants[1].template_version == 3
    assert reopened.summary_variants[1].template_prompts == {
        "format": "Письмо клиенту"
    }
    assert "Анна: Начинаем встречу" in reopened.summary_variants[0].content
    assert "Ben: Let us confirm the next step" in reopened.summary_variants[1].content
    assert len(generation_calls) == 2
