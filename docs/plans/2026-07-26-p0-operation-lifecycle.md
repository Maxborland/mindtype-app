# P0 Operation Lifecycle

## Behavior spec

Goal: make every dictation or file-transcription operation end exactly once,
prevent stale results from being inserted, and never hand an unfinished WAV to a
transcriber.

Non-goals:

- Do not introduce the persistent cloud job journal in this local lifecycle slice.
- Do not replace Qt workers or rewrite the application around a new framework.
- Do not add preliminary text insertion; partial text remains overlay-only.

Assumptions:

- Only one local transcription process may use the shared transcriber at a time.
- Cancellation is cooperative first, then forceful for a native subprocess that
  does not exit within a short grace period.
- A cancelled or superseded operation may finish internally, but its result must
  never mutate history, UI success state, or the target application.

Acceptance criteria:

- AC1: every dictation gets a monotonically increasing operation token; only the
  current token may transition from transcribing to success or failure.
- AC2: cancellation has separate `CANCEL_REQUESTED` and terminal `CANCELLED`
  states, clears pending insertion, and no terminal state can later become
  successful.
- AC3: `TranscribeWorker` checks cancellation after every blocking stage and
  emits exactly one terminal outcome.
- AC4: main-window callbacks capture the operation token, ignore stale progress
  and completion, and delete the recording after either finish or cancellation.
- AC5: if audio stream startup fails, recorder state, stream, writer, queue, and
  temporary file are cleaned; `stop()` returns a path only after the writer has
  closed the WAV.
- AC6: cancellation reaches the active whisper.cpp process, calls `terminate()`,
  waits for a grace period, then calls `kill()` only if still running.
- AC7: file cancellation is checked between extraction, transcription,
  post-processing, summarization, and report generation; cancelled tasks cannot
  return to `COMPLETED`, and temporary files are cleaned in `finally`.

## Failure behavior

- Writer failure or writer timeout is surfaced as an operation error; an
  unfinished WAV is not transcribed.
- Native-process cancellation is reported as cancellation, not as a successful
  empty transcript.
- A second local transcription attempt while another native process owns the
  backend fails explicitly instead of overwriting process ownership.

## Traceable test plan

- AC1–AC2 → state-machine tests for stale token, cancellation request, terminal
  cancellation, and forbidden terminal-to-success transitions.
- AC3 → worker tests for cancellation after model load, after final stream item,
  and single terminal signal.
- AC4 → callback/token tests where practical plus direct worker signal wiring
  verification.
- AC5 → audio tests for `stream.start()` rollback, writer error, writer timeout,
  and finalized path handoff.
- AC6 → whisper.cpp process ownership and terminate/kill tests.
- AC7 → queue tests that cancel after each blocking stage and assert final status
  plus temporary-file cleanup.

# Lead Architect Report

## Review Context

- Mode: Recovery
- Scope reviewed: dictation state, audio writer, Qt transcription worker,
  whisper.cpp subprocesses, file queue, and main-window callbacks
- Main business capability: record → transcribe → save → insert without data loss
- Soft gate status: Escalate

## Findings

### F1. Boolean dictation flags cannot identify stale work

Severity: Required

Area: Lifecycle / Domain model

Evidence:

- `DictationState` stores `transcribing` and `auto_insert_pending` booleans.
- Qt completion callbacks carry no operation identity.
- cancellation clears booleans while the worker or native process may continue.

Risk:

- A late callback from cancelled work can mark success, enter history, or insert
  text into the foreground application.

Required improvement:

- Introduce operation tokens and explicit phases with guarded terminal
  transitions.

Acceptance criteria:

- AC1–AC4 pass.

### F2. Recorder activation precedes successful stream startup

Severity: Required

Area: Audio lifecycle

Evidence:

- the running flag and writer thread start before `RawInputStream.start()`;
- startup failure after construction has no rollback path;
- `stop()` can return the WAV path while the writer is still alive.

Risk:

- the next operation sees a false active state or reads a WAV whose header and
  frames are not finalized.

Required improvement:

- centralize rollback and make writer completion a precondition for path handoff.

Acceptance criteria:

- AC5 passes.

### F3. Worker cancellation does not stop native work

Severity: Required

Area: Process ownership / Cancellation

Evidence:

- `TranscribeWorker.cancel()` only flips a Python boolean;
- whisper.cpp waits inside a subprocess for up to 30 minutes;
- `cancelled` is not wired to recording cleanup in the main flow.

Risk:

- cancelled operations consume CPU, keep files open, and can produce stale
  callbacks long after the user moved on.

Required improvement:

- give the backend explicit process ownership and cooperative-to-forceful
  cancellation, then connect every terminal worker signal to cleanup.

Acceptance criteria:

- AC3, AC4, and AC6 pass.

### F4. File queue terminal states are mutable assignments

Severity: Required

Area: File lifecycle

Evidence:

- the queue checks cancellation at some stages but status assignments remain
  unconstrained;
- report generation runs in a separate callback after queue completion;
- cleanup is reached only through the normal worker tail.

Risk:

- cancellation or an exception can leak temporary media or let a cancelled task
  return to `COMPLETED`.

Required improvement:

- check cancellation after every blocking stage, guard terminal transitions, and
  move cleanup into guaranteed `finally` paths.

Acceptance criteria:

- AC7 passes.
