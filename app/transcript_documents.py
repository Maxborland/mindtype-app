"""Create document variants from durable transcript revisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Tuple, Union

from .transcript_store import SummaryVariant, TranscriptDocument, TranscriptStore


@dataclass(frozen=True)
class GeneratedSummary:
    """Summary content plus the provider/model that actually generated it."""

    content: str
    metrics: Optional[dict]
    provider: Optional[str] = None
    model: Optional[str] = None


SummaryGeneration = Union[GeneratedSummary, Tuple[str, Optional[dict]]]

SummaryGenerator = Callable[
    [str, dict[str, str]],
    SummaryGeneration,
]


@dataclass(frozen=True)
class SummaryTemplate:
    id: str
    name: str
    version: int
    prompts: dict[str, str]
    provider: str
    model: str


def transcript_text(document: TranscriptDocument) -> str:
    """Render the current revision with stable speaker names for generation."""
    revision = document.current_revision
    lines = []
    for segment in revision.segments:
        speaker_id = segment.speaker or ""
        speaker = revision.speaker_names.get(speaker_id, speaker_id)
        prefix = f"{speaker}: " if speaker else ""
        lines.append(f"{prefix}{segment.text}".strip())
    return "\n".join(line for line in lines if line)


def create_summary_document(
    store: TranscriptStore,
    document_id: str,
    template: SummaryTemplate,
    generate: SummaryGenerator,
) -> SummaryVariant:
    """Generate and persist one immutable document variant."""
    document = store.get_document(document_id)
    if document is None:
        raise KeyError(f"Расшифровка {document_id} не найдена")

    source_text = transcript_text(document)
    if not source_text:
        raise ValueError("В расшифровке нет текста для создания документа")

    generated = generate(source_text, dict(template.prompts))
    if isinstance(generated, GeneratedSummary):
        content = generated.content
        metrics = generated.metrics
        provider = generated.provider or template.provider
        model = generated.model or template.model
    else:
        content, metrics = generated
        provider = template.provider
        model = template.model
    if not content.strip():
        raise ValueError("Генерация вернула пустой документ")

    return store.add_summary_variant(
        document_id=document.id,
        revision_id=document.current_revision.id,
        template_id=template.id,
        template_name=template.name,
        template_version=template.version,
        template_prompts=template.prompts,
        content=content,
        provider=provider,
        model=model,
        metrics=metrics,
    )
