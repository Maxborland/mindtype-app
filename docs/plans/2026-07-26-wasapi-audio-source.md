# Windows audio-source contract

## Goal

MindType records microphone and Windows system audio as independent durable
tracks, with a typed lifecycle that preserves already captured media when an
audio device disappears.

## Acceptance criteria

- AC1: capture sources are explicit `microphone`, `system`, or
  `microphone_system` values; invalid source strings are rejected.
- AC2: every recorded track contains its source kind, sample rate, channel
  count, and monotonic start/end timestamps.
- AC3: Windows system devices are discovered through WASAPI loopback and never
  confused with physical microphones.
- AC4: system-audio capture uses a bounded queue and reports overflow instead
  of growing memory without limit.
- AC5: a disconnect or backend read failure stops capture, closes the WAV, and
  returns an interrupted result that still points to the partial recording.
- AC6: microphone + system mode starts and stops independent tracks; failure of
  one track does not delete the other.
- AC7: canonical result source channels validate track kind, timestamps, sample
  rate, channels, and optional SHA-256.
- AC8: SoundCard is Windows-only, hash-locked, and included in the frozen build.

## Constraints

- Do not mix or resample original tracks in the capture layer.
- Do not keep stale SoundCard device objects; rediscover by stable backend ID
  when each operation starts.
- Do not claim hardware compatibility from mocked unit tests. A supervised
  laptop/device matrix remains a Windows GA gate.
- Existing microphone-only callers keep their `AudioRecorder.start()/stop()`
  compatibility API until the UI is migrated to the typed session API.
