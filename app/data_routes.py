"""Provider-neutral description of where each processing stage runs."""

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ProcessingRoute:
    audio: str
    diarization: str
    summary: str

    @property
    def uses_cloud(self) -> bool:
        return any(
            destination not in {"Local", "Off"}
            for destination in (self.audio, self.diarization, self.summary)
        )


def resolve_processing_route(
    config: Mapping[str, Any],
    *,
    summary_enabled: bool,
    diarization_backend: str,
) -> ProcessingRoute:
    """Resolve destinations from the effective settings shown to the user."""
    audio = (
        "OpenRouter"
        if config.get("transcriber_backend") == "openrouter"
        else "Local"
    )

    if not config.get("postprocessing_diarization", True):
        diarization = "Off"
    elif diarization_backend == "openrouter":
        diarization = "OpenRouter"
    elif diarization_backend == "auto" and config.get("openrouter_api_key"):
        diarization = "OpenRouter"
    else:
        diarization = "Local"

    if not summary_enabled:
        summary = "Off"
    else:
        summary_provider = config.get("llm_provider", "openrouter")
        summary = {
            "mindtype_cloud": "MindType Cloud",
            "ollama": "Local",
            "openrouter": "OpenRouter",
            "openai": "OpenAI",
            "anthropic": "Anthropic",
            "gemini": "Google Gemini",
        }.get(summary_provider, str(summary_provider))

    return ProcessingRoute(
        audio=audio,
        diarization=diarization,
        summary=summary,
    )
