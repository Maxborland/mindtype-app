"""Provider-neutral description of where each processing stage runs."""

from dataclasses import dataclass
from typing import Any, Mapping

from .optional_features import effective_diarization_backend


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


_PROVIDER_IDS = {
    "MindType Cloud": "mindtype_cloud",
    "OpenRouter": "openrouter",
    "OpenAI": "openai",
    "Anthropic": "anthropic",
    "Google Gemini": "gemini",
    "Local": "local",
}


def canonical_processing_route(
    route: ProcessingRoute,
    config: Mapping[str, Any],
) -> dict[str, dict[str, str]]:
    """Convert user-facing destinations into stable canonical provenance."""
    transcription_provider = _PROVIDER_IDS.get(
        route.audio,
        route.audio.lower().replace(" ", "_"),
    )
    if transcription_provider == "openrouter":
        transcription_model = (
            config.get("openrouter_transcribe_model") or "auto"
        )
    elif transcription_provider == "local":
        transcription_model = config.get("model_size") or "auto"
    else:
        transcription_model = "auto"

    canonical = {
        "transcription": {
            "provider": transcription_provider,
            "model": str(transcription_model),
        }
    }
    if route.diarization != "Off":
        diarization_provider = _PROVIDER_IDS.get(
            route.diarization,
            route.diarization.lower().replace(" ", "_"),
        )
        if diarization_provider == "local":
            diarization_model = "mfcc"
        elif diarization_provider == "openrouter":
            diarization_model = (
                config.get("openrouter_diarization_model")
                or config.get("openrouter_model")
                or "auto"
            )
        else:
            diarization_model = "auto"
        canonical["diarization"] = {
            "provider": diarization_provider,
            "model": str(diarization_model),
        }
    if route.summary != "Off":
        summary_provider = _PROVIDER_IDS.get(
            route.summary,
            route.summary.lower().replace(" ", "_"),
        )
        if summary_provider == "local":
            summary_model = config.get("ollama_model") or "auto"
        elif summary_provider == "mindtype_cloud":
            summary_model = "auto"
        else:
            summary_model = (
                config.get(f"{summary_provider}_model")
                or "auto"
            )
        canonical["summary"] = {
            "provider": summary_provider,
            "model": str(summary_model),
        }
    return canonical


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

    effective_backend = effective_diarization_backend(
        diarization_backend,
        api_key=str(config.get("openrouter_api_key") or ""),
    )
    if not config.get("postprocessing_diarization", True):
        diarization = "Off"
    elif effective_backend == "openrouter":
        diarization = "OpenRouter"
    elif effective_backend == "local":
        diarization = "Local"
    else:
        diarization = "Off"

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
