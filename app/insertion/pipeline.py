"""Platform-neutral insertion result and adapter orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, Protocol, Sequence


class InsertionMethod(str, Enum):
    CLIPBOARD = "clipboard"
    UNICODE = "unicode"
    UI_AUTOMATION = "ui_automation"


class InsertionFailure(str, Enum):
    EMPTY_TEXT = "empty_text"
    TARGET_INVALID = "target_invalid"
    TARGET_NOT_FOCUSED = "target_not_focused"
    ALL_METHODS_FAILED = "all_methods_failed"
    PARTIAL_INSERT = "partial_insert"
    CLIPBOARD_RESTORE_FAILED = "clipboard_restore_failed"


@dataclass(frozen=True)
class AdapterAttempt:
    success: bool
    committed: bool
    error: Optional[str] = None
    failure: Optional[InsertionFailure] = None

    @classmethod
    def succeeded(cls) -> "AdapterAttempt":
        return cls(success=True, committed=True)

    @classmethod
    def failed(
        cls,
        error: str,
        *,
        committed: bool = False,
        failure: Optional[InsertionFailure] = None,
    ) -> "AdapterAttempt":
        return cls(
            success=False,
            committed=committed,
            error=error,
            failure=failure,
        )


@dataclass(frozen=True)
class InsertionResult:
    success: bool
    method: Optional[InsertionMethod]
    failure: Optional[InsertionFailure]
    attempted: tuple[InsertionMethod, ...]
    error: Optional[str] = None

    @classmethod
    def ok(
        cls,
        method: InsertionMethod,
        *,
        attempted: tuple[InsertionMethod, ...],
    ) -> "InsertionResult":
        return cls(
            success=True,
            method=method,
            failure=None,
            attempted=attempted,
        )

    @classmethod
    def failed(
        cls,
        failure: InsertionFailure,
        *,
        attempted: tuple[InsertionMethod, ...] = (),
        method: Optional[InsertionMethod] = None,
        error: Optional[str] = None,
    ) -> "InsertionResult":
        return cls(
            success=False,
            method=method,
            failure=failure,
            attempted=attempted,
            error=error,
        )


class InsertionAdapter(Protocol):
    method: InsertionMethod

    def attempt(self, text: str, target: object, delay: float) -> AdapterAttempt:
        ...


class InsertionPipeline:
    """Try technical fallbacks without duplicating partially committed text."""

    def __init__(
        self,
        adapters: Sequence[InsertionAdapter],
        *,
        validate_target: Optional[Callable[[object], bool]] = None,
    ) -> None:
        self._adapters = tuple(adapters)
        self._validate_target = validate_target

    def insert(self, text: str, *, target: object, delay: float) -> InsertionResult:
        attempted: list[InsertionMethod] = []
        errors: list[str] = []

        for adapter in self._adapters:
            if (
                self._validate_target is not None
                and not self._validate_target(target)
            ):
                return InsertionResult.failed(
                    InsertionFailure.TARGET_NOT_FOCUSED,
                    attempted=tuple(attempted),
                    error="Target focus changed during insertion",
                )
            attempted.append(adapter.method)
            try:
                result = adapter.attempt(text, target, delay)
            except Exception as exc:
                result = AdapterAttempt.failed(str(exc))

            if result.success:
                return InsertionResult.ok(
                    adapter.method,
                    attempted=tuple(attempted),
                )
            if result.error:
                errors.append(f"{adapter.method.value}: {result.error}")
            if result.committed:
                return InsertionResult.failed(
                    result.failure or InsertionFailure.PARTIAL_INSERT,
                    attempted=tuple(attempted),
                    method=adapter.method,
                    error=result.error,
                )

        return InsertionResult.failed(
            InsertionFailure.ALL_METHODS_FAILED,
            attempted=tuple(attempted),
            error="; ".join(errors) or None,
        )


class ClipboardPasteAdapter:
    method = InsertionMethod.CLIPBOARD

    def __init__(
        self,
        *,
        read_clipboard: Callable[[], object],
        write_clipboard: Callable[[str], None],
        restore_clipboard: Optional[Callable[[object], None]] = None,
        send_paste: Callable[[], None],
        release_modifiers: Callable[[], None],
        sleep: Callable[[float], None],
    ) -> None:
        self._read_clipboard = read_clipboard
        self._write_clipboard = write_clipboard
        self._restore_clipboard = restore_clipboard or write_clipboard
        self._send_paste = send_paste
        self._release_modifiers = release_modifiers
        self._sleep = sleep

    def attempt(self, text: str, target: object, delay: float) -> AdapterAttempt:
        del target
        try:
            previous = self._read_clipboard()
        except Exception as exc:
            return AdapterAttempt.failed(f"clipboard snapshot failed: {exc}")

        mutated = False
        committed = False
        operation_error: Optional[Exception] = None
        restore_error: Optional[Exception] = None
        try:
            self._write_clipboard(text)
            mutated = True
            self._sleep(0.05)
            self._release_modifiers()
            self._sleep(0.05)
            self._send_paste()
            committed = True
            self._sleep(delay)
        except Exception as exc:
            operation_error = exc
        finally:
            if mutated:
                try:
                    self._restore_clipboard(previous)
                except Exception as exc:
                    restore_error = exc

        if restore_error is not None:
            return AdapterAttempt.failed(
                f"clipboard restore failed: {restore_error}",
                # Stop the pipeline even when paste itself failed: continuing
                # would hide a known clipboard-loss condition.
                committed=True,
                failure=InsertionFailure.CLIPBOARD_RESTORE_FAILED,
            )
        if operation_error is not None:
            return AdapterAttempt.failed(
                str(operation_error),
                committed=committed,
                failure=(
                    InsertionFailure.PARTIAL_INSERT if committed else None
                ),
            )
        return AdapterAttempt.succeeded()


class UnicodeInputAdapter:
    method = InsertionMethod.UNICODE

    def __init__(
        self,
        *,
        send_code_unit: Callable[[int, bool], bool],
    ) -> None:
        self._send_code_unit = send_code_unit

    def attempt(self, text: str, target: object, delay: float) -> AdapterAttempt:
        del target, delay
        sent_units = 0
        encoded = text.encode("utf-16-le")
        for index in range(0, len(encoded), 2):
            code_unit = int.from_bytes(encoded[index:index + 2], "little")
            if not self._send_code_unit(code_unit, False):
                return AdapterAttempt.failed(
                    "SendInput key-down failed",
                    committed=sent_units > 0,
                    failure=InsertionFailure.PARTIAL_INSERT,
                )
            if not self._send_code_unit(code_unit, True):
                return AdapterAttempt.failed(
                    "SendInput key-up failed",
                    committed=True,
                    failure=InsertionFailure.PARTIAL_INSERT,
                )
            sent_units += 1
        return AdapterAttempt.succeeded()


class UIAutomationValueAdapter:
    """Optional ValuePattern adapter; unavailable until a backend is supplied."""

    method = InsertionMethod.UI_AUTOMATION

    def __init__(
        self,
        *,
        set_value: Optional[Callable[[object, str], bool]] = None,
    ) -> None:
        self._set_value = set_value

    def attempt(self, text: str, target: object, delay: float) -> AdapterAttempt:
        del delay
        if self._set_value is None:
            return AdapterAttempt.failed("UI Automation backend unavailable")
        try:
            if self._set_value(target, text):
                return AdapterAttempt.succeeded()
            return AdapterAttempt.failed("ValuePattern rejected the text")
        except Exception as exc:
            return AdapterAttempt.failed(str(exc))
