from __future__ import annotations

from importlib.util import find_spec


def local_diarization_available() -> bool:
    """Return whether the separately installed MFCC diarization pack exists."""
    return all(find_spec(module) is not None for module in ("librosa", "sklearn"))


__all__ = ["local_diarization_available"]
