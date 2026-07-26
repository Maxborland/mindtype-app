"""Guarded lifecycle for one push-to-talk dictation at a time."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class DictationPhase(Enum):
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

    @property
    def terminal(self) -> bool:
        return self in {
            DictationPhase.CANCELLED,
            DictationPhase.SUCCEEDED,
            DictationPhase.FAILED,
        }


@dataclass
class DictationState:
    """State transitions are accepted only for the current operation token."""

    phase: DictationPhase = DictationPhase.IDLE
    operation_token: int = 0
    auto_insert_pending: bool = False
    recording_started_at: Optional[float] = None
    recording_quota_deadline: Optional[float] = None

    @property
    def transcribing(self) -> bool:
        return self.phase in {
            DictationPhase.TRANSCRIBING,
            DictationPhase.CANCEL_REQUESTED,
        }

    def begin_recording(
        self,
        *,
        started_at: float,
        max_duration_seconds: Optional[float] = None,
    ) -> int:
        self.operation_token += 1
        self.phase = DictationPhase.RECORDING
        self.auto_insert_pending = False
        self.recording_started_at = started_at
        self.recording_quota_deadline = (
            started_at + max(0.0, max_duration_seconds)
            if max_duration_seconds is not None
            else None
        )
        return self.operation_token

    def recording_quota_reached(self, token: int, *, now: float) -> bool:
        return (
            token == self.operation_token
            and self.phase is DictationPhase.RECORDING
            and self.recording_quota_deadline is not None
            and now >= self.recording_quota_deadline
        )

    def begin_transcription(self, token: int, *, auto_insert: bool) -> bool:
        if token != self.operation_token or self.phase is not DictationPhase.RECORDING:
            return False
        self.phase = DictationPhase.TRANSCRIBING
        self.auto_insert_pending = auto_insert
        return True

    def request_cancel(self, token: int) -> bool:
        if token != self.operation_token:
            return False
        if self.phase in {DictationPhase.IDLE} or self.phase.terminal:
            return False
        self.phase = DictationPhase.CANCEL_REQUESTED
        self.auto_insert_pending = False
        return True

    def mark_cancelled(self, token: int) -> bool:
        if token != self.operation_token or self.phase is not DictationPhase.CANCEL_REQUESTED:
            return False
        self.phase = DictationPhase.CANCELLED
        self.recording_started_at = None
        self.recording_quota_deadline = None
        return True

    def finish_transcription(self, token: int, *, succeeded: bool) -> bool:
        if token != self.operation_token or self.phase is not DictationPhase.TRANSCRIBING:
            return False
        self.phase = DictationPhase.SUCCEEDED if succeeded else DictationPhase.FAILED
        self.recording_started_at = None
        self.recording_quota_deadline = None
        if not succeeded:
            self.auto_insert_pending = False
        return True

    def claim_auto_insert(self, token: int) -> bool:
        if (
            token != self.operation_token
            or self.phase is not DictationPhase.SUCCEEDED
            or not self.auto_insert_pending
        ):
            return False
        self.auto_insert_pending = False
        return True
