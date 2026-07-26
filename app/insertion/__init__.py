"""Typed, duplicate-safe text insertion pipeline."""

from .pipeline import (
    AdapterAttempt,
    ClipboardPasteAdapter,
    InsertionFailure,
    InsertionMethod,
    InsertionPipeline,
    InsertionResult,
    UIAutomationValueAdapter,
    UnicodeInputAdapter,
)

__all__ = [
    "AdapterAttempt",
    "ClipboardPasteAdapter",
    "InsertionFailure",
    "InsertionMethod",
    "InsertionPipeline",
    "InsertionResult",
    "UIAutomationValueAdapter",
    "UnicodeInputAdapter",
]
