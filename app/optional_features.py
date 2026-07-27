from __future__ import annotations

from importlib.util import find_spec
from typing import Optional


def local_diarization_available() -> bool:
    """Return whether the separately installed MFCC diarization pack exists."""
    return all(find_spec(module) is not None for module in ("librosa", "sklearn"))


def effective_diarization_backend(
    requested: str,
    *,
    api_key: str = "",
    local_available: Optional[bool] = None,
) -> str:
    """Resolve the configured backend to one that this installation can run."""
    if local_available is None:
        local_available = local_diarization_available()
    if requested == "auto":
        if api_key.strip():
            return "openrouter"
        return "local" if local_available else "disabled"
    if requested == "local" and not local_available:
        return "disabled"
    return requested


__all__ = [
    "effective_diarization_backend",
    "local_diarization_available",
]
