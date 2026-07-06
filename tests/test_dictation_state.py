"""Тесты машины состояний диктовки."""

from datetime import datetime

from app.dictation_state import DictationState


def test_initial_state():
    s = DictationState()
    assert s.transcribing is False
    assert s.auto_insert_pending is False
    assert s.recording_start_time is None


def test_begin_transcription_with_autoinsert():
    s = DictationState()
    s.begin_transcription(auto_insert=True)
    assert s.transcribing is True
    assert s.auto_insert_pending is True


def test_begin_transcription_without_autoinsert():
    s = DictationState()
    s.begin_transcription(auto_insert=False)
    assert s.transcribing is True
    assert s.auto_insert_pending is False


def test_finish_transcription_keeps_autoinsert_flag():
    s = DictationState()
    s.begin_transcription(auto_insert=True)
    s.finish_transcription()
    assert s.transcribing is False
    # finish не трогает автовставку (её сбрасывают отдельно после вставки)
    assert s.auto_insert_pending is True


def test_cancel_resets_both():
    s = DictationState()
    s.begin_transcription(auto_insert=True)
    s.recording_start_time = datetime.now()
    s.cancel()
    assert s.transcribing is False
    assert s.auto_insert_pending is False
