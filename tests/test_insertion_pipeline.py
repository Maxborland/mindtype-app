from unittest.mock import Mock

from app.insertion import (
    AdapterAttempt,
    ClipboardPasteAdapter,
    InsertionFailure,
    InsertionMethod,
    InsertionPipeline,
    UnicodeInputAdapter,
)


class StubAdapter:
    def __init__(self, method, attempt):
        self.method = method
        self.attempt_result = attempt
        self.calls = []

    def attempt(self, text, target, delay):
        self.calls.append((text, target, delay))
        return self.attempt_result


def test_pipeline_uses_fallback_order_until_one_method_succeeds():
    clipboard = StubAdapter(
        InsertionMethod.CLIPBOARD,
        AdapterAttempt.failed("clipboard unavailable"),
    )
    unicode_input = StubAdapter(
        InsertionMethod.UNICODE,
        AdapterAttempt.succeeded(),
    )
    uia = StubAdapter(
        InsertionMethod.UI_AUTOMATION,
        AdapterAttempt.succeeded(),
    )

    result = InsertionPipeline([clipboard, unicode_input, uia]).insert(
        "текст", target=42, delay=0
    )

    assert result.success is True
    assert result.method is InsertionMethod.UNICODE
    assert result.attempted == (
        InsertionMethod.CLIPBOARD,
        InsertionMethod.UNICODE,
    )
    assert not uia.calls


def test_pipeline_does_not_duplicate_after_a_committed_failure():
    clipboard = StubAdapter(
        InsertionMethod.CLIPBOARD,
        AdapterAttempt.failed(
            "clipboard restore failed",
            committed=True,
            failure=InsertionFailure.CLIPBOARD_RESTORE_FAILED,
        ),
    )
    unicode_input = StubAdapter(
        InsertionMethod.UNICODE,
        AdapterAttempt.succeeded(),
    )

    result = InsertionPipeline([clipboard, unicode_input]).insert(
        "text", target=42, delay=0
    )

    assert result.success is False
    assert result.failure is InsertionFailure.CLIPBOARD_RESTORE_FAILED
    assert result.attempted == (InsertionMethod.CLIPBOARD,)
    assert not unicode_input.calls


def test_pipeline_revalidates_target_before_each_fallback():
    clipboard = StubAdapter(
        InsertionMethod.CLIPBOARD,
        AdapterAttempt.failed("clipboard unavailable"),
    )
    unicode_input = StubAdapter(
        InsertionMethod.UNICODE,
        AdapterAttempt.succeeded(),
    )
    validations = iter([True, False])

    result = InsertionPipeline(
        [clipboard, unicode_input],
        validate_target=lambda _target: next(validations),
    ).insert("text", target=42, delay=0)

    assert result.success is False
    assert result.failure is InsertionFailure.TARGET_NOT_FOCUSED
    assert result.attempted == (InsertionMethod.CLIPBOARD,)
    assert not unicode_input.calls


def test_clipboard_adapter_restores_snapshot_when_paste_raises():
    writes = []
    adapter = ClipboardPasteAdapter(
        read_clipboard=lambda: "previous",
        write_clipboard=writes.append,
        send_paste=Mock(side_effect=RuntimeError("paste failed")),
        release_modifiers=Mock(),
        sleep=lambda _delay: None,
    )

    result = adapter.attempt("new text", target=42, delay=0)

    assert result.success is False
    assert result.committed is False
    assert writes == ["new text", "previous"]


def test_clipboard_adapter_restores_opaque_multiformat_snapshot():
    snapshot = object()
    restored = []
    adapter = ClipboardPasteAdapter(
        read_clipboard=lambda: snapshot,
        write_clipboard=Mock(),
        restore_clipboard=restored.append,
        send_paste=Mock(),
        release_modifiers=Mock(),
        sleep=lambda _delay: None,
    )

    result = adapter.attempt("new text", target=42, delay=0)

    assert result.success is True
    assert restored == [snapshot]


def test_clipboard_adapter_rechecks_target_immediately_before_paste():
    snapshot = object()
    restored = []
    send_paste = Mock()
    adapter = ClipboardPasteAdapter(
        read_clipboard=lambda: snapshot,
        write_clipboard=Mock(),
        restore_clipboard=restored.append,
        send_paste=send_paste,
        release_modifiers=Mock(),
        sleep=lambda _delay: None,
        validate_target=lambda target: target == 7 and False,
    )

    result = adapter.attempt("secret", target=7, delay=0)

    assert result.success is False
    assert result.failure is InsertionFailure.TARGET_NOT_FOCUSED
    send_paste.assert_not_called()
    assert restored == [snapshot]


def test_clipboard_adapter_never_mutates_when_snapshot_fails():
    write = Mock()
    adapter = ClipboardPasteAdapter(
        read_clipboard=Mock(side_effect=RuntimeError("clipboard locked")),
        write_clipboard=write,
        send_paste=Mock(),
        release_modifiers=Mock(),
        sleep=lambda _delay: None,
    )

    result = adapter.attempt("new text", target=42, delay=0)

    assert result.success is False
    write.assert_not_called()


def test_clipboard_restore_failure_is_terminal_even_if_paste_failed():
    writes = 0

    def write(_text):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise RuntimeError("clipboard locked during restore")

    adapter = ClipboardPasteAdapter(
        read_clipboard=lambda: "previous",
        write_clipboard=write,
        send_paste=Mock(side_effect=RuntimeError("paste failed")),
        release_modifiers=Mock(),
        sleep=lambda _delay: None,
    )

    result = adapter.attempt("new text", target=42, delay=0)

    assert result.success is False
    assert result.committed is True
    assert result.failure is InsertionFailure.CLIPBOARD_RESTORE_FAILED


def test_unicode_adapter_emits_utf16_surrogate_pairs():
    emitted = []
    adapter = UnicodeInputAdapter(
        send_code_unit=lambda code_unit, key_up: (
            emitted.append((code_unit, key_up)) or True
        )
    )

    result = adapter.attempt("A😀", target=42, delay=0)

    assert result.success is True
    assert emitted == [
        (0x0041, False),
        (0x0041, True),
        (0xD83D, False),
        (0xD83D, True),
        (0xDE00, False),
        (0xDE00, True),
    ]


def test_unicode_adapter_marks_partial_input_committed():
    calls = 0

    def send(_code_unit, _key_up):
        nonlocal calls
        calls += 1
        return calls < 3

    result = UnicodeInputAdapter(send_code_unit=send).attempt(
        "AB", target=42, delay=0
    )

    assert result.success is False
    assert result.committed is True
    assert result.failure is InsertionFailure.PARTIAL_INSERT
