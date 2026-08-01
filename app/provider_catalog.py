"""Product-facing provider choices with legacy-config compatibility."""

from __future__ import annotations

from typing import Final


ProviderOption = tuple[str, str]

CLOUD_PROVIDER: Final[ProviderOption] = ("MindType Cloud", "mindtype_cloud")

LEGACY_PROVIDERS: Final[dict[str, ProviderOption]] = {
    "openai": ("OpenAI (Legacy)", "openai"),
    "anthropic": ("Claude (Legacy)", "anthropic"),
    "gemini": ("Gemini (Legacy)", "gemini"),
    "ollama": ("Ollama (Legacy)", "ollama"),
    "openrouter": ("OpenRouter (Legacy)", "openrouter"),
}


def visible_summary_providers(saved_provider: str) -> tuple[ProviderOption, ...]:
    """Return the ordinary Cloud route plus an explicitly selected legacy route."""
    legacy = LEGACY_PROVIDERS.get(saved_provider)
    if legacy is None:
        return (CLOUD_PROVIDER,)
    return (CLOUD_PROVIDER, legacy)
