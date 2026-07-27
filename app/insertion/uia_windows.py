"""Windows UI Automation ValuePattern fallback."""

from __future__ import annotations

import importlib
from typing import Any

try:
    from comtypes import CoInitialize, CoUninitialize
except ImportError:
    def CoInitialize() -> None:
        raise RuntimeError("comtypes is not installed")

    def CoUninitialize() -> None:
        return None


UIA_VALUE_PATTERN_ID = 10002


def _create_automation() -> tuple[Any, Any]:
    from comtypes.client import CreateObject, GetModule

    GetModule("UIAutomationCore.dll")
    client = importlib.import_module("comtypes.gen.UIAutomationClient")
    automation = CreateObject(
        client.CUIAutomation,
        interface=client.IUIAutomation,
    )
    return automation, client.IUIAutomationValuePattern


def set_value_via_uia(target: object, text: str) -> bool:
    """Set the focused editable control through UIA after HWND focus validation."""

    if not target or not text:
        return False

    initialized = False
    try:
        CoInitialize()
        initialized = True
        automation, value_pattern_interface = _create_automation()
        element = automation.GetFocusedElement()
        if element is None:
            return False
        unknown_pattern = element.GetCurrentPattern(UIA_VALUE_PATTERN_ID)
        if unknown_pattern is None:
            return False
        pattern = unknown_pattern.QueryInterface(value_pattern_interface)
        if bool(pattern.CurrentIsReadOnly):
            return False
        # ValuePattern.SetValue replaces the whole control; it is only a safe
        # insertion fallback when the control is empty.
        if str(pattern.CurrentValue or ""):
            return False
        pattern.SetValue(text)
        return True
    finally:
        if initialized:
            CoUninitialize()
