"""Тесты машины состояний диктовки."""

from app.dictation_state import DictationPhase, DictationState


def test_recordings_get_monotonic_operation_tokens():
    state = DictationState()

    first = state.begin_recording(started_at=10.0)
    state.request_cancel(first)
    state.mark_cancelled(first)
    second = state.begin_recording(started_at=20.0)

    assert second > first
    assert state.operation_token == second
    assert state.phase is DictationPhase.RECORDING


def test_cancelled_operation_cannot_return_to_success():
    state = DictationState()
    token = state.begin_recording(started_at=10.0)
    assert state.begin_transcription(token, auto_insert=True)

    assert state.request_cancel(token)
    assert state.phase is DictationPhase.CANCEL_REQUESTED
    assert state.auto_insert_pending is False
    assert state.mark_cancelled(token)
    assert state.phase is DictationPhase.CANCELLED

    assert state.finish_transcription(token, succeeded=True) is False
    assert state.phase is DictationPhase.CANCELLED


def test_stale_completion_cannot_finish_current_operation():
    state = DictationState()
    stale_token = state.begin_recording(started_at=10.0)
    state.begin_transcription(stale_token, auto_insert=True)
    state.request_cancel(stale_token)
    state.mark_cancelled(stale_token)

    current_token = state.begin_recording(started_at=20.0)
    state.begin_transcription(current_token, auto_insert=True)

    assert state.finish_transcription(stale_token, succeeded=True) is False
    assert state.claim_auto_insert(stale_token) is False
    assert state.phase is DictationPhase.TRANSCRIBING
    assert state.operation_token == current_token


def test_initial_state():
    s = DictationState()
    assert s.phase is DictationPhase.IDLE
    assert s.transcribing is False
    assert s.auto_insert_pending is False
    assert s.recording_started_at is None


def test_begin_transcription_with_autoinsert():
    s = DictationState()
    token = s.begin_recording(started_at=1.0)
    assert s.begin_transcription(token, auto_insert=True)
    assert s.transcribing is True
    assert s.auto_insert_pending is True


def test_begin_transcription_without_autoinsert():
    s = DictationState()
    token = s.begin_recording(started_at=1.0)
    assert s.begin_transcription(token, auto_insert=False)
    assert s.transcribing is True
    assert s.auto_insert_pending is False


def test_recovered_dictation_gets_a_fresh_transcription_token():
    s = DictationState()

    token = s.begin_recovery(auto_insert=False)

    assert token == 1
    assert s.phase is DictationPhase.TRANSCRIBING
    assert s.auto_insert_pending is False


def test_finish_transcription_keeps_autoinsert_flag():
    s = DictationState()
    token = s.begin_recording(started_at=1.0)
    s.begin_transcription(token, auto_insert=True)
    assert s.finish_transcription(token, succeeded=True)
    assert s.transcribing is False
    assert s.auto_insert_pending is True
    assert s.claim_auto_insert(token)
    assert s.auto_insert_pending is False


def test_cancel_resets_both():
    s = DictationState()
    token = s.begin_recording(started_at=1.0)
    s.begin_transcription(token, auto_insert=True)
    assert s.request_cancel(token)
    assert s.mark_cancelled(token)
    assert s.transcribing is False
    assert s.auto_insert_pending is False


def test_trial_quota_deadline_is_bound_to_current_recording():
    s = DictationState()
    stale = s.begin_recording(started_at=10.0, max_duration_seconds=5.0)

    assert s.recording_quota_reached(stale, now=14.9) is False
    assert s.recording_quota_reached(stale, now=15.0) is True

    s.request_cancel(stale)
    s.mark_cancelled(stale)
    current = s.begin_recording(started_at=20.0, max_duration_seconds=10.0)

    assert s.recording_quota_reached(stale, now=30.0) is False
    assert s.recording_quota_reached(current, now=30.0) is True
