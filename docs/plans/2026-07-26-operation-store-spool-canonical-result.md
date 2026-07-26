# Operation store, durable spool, and canonical result

## Goal

Create the desktop persistence boundary required by the Windows GA contract:
an operation is recorded before processing, its source survives interruption,
and `COMPLETED` is impossible until a validated canonical JSON result has been
atomically saved.

## Non-goals

- Do not implement the MindType Cloud backend in the desktop repository.
- Do not replace all existing UI lifecycle code in one change.
- Do not add automatic OpenRouter retries or any behavior that can duplicate
  third-party charges.
- Do not delete a user's imported original; MindType owns only its spool copy.
- Do not implement exporters, WASAPI, or the persistent local engine in this
  slice.

## Acceptance criteria

- **AC1:** One provider-neutral `OperationRecord` represents dictation and file
  work with the declared statuses and stages. Terminal states cannot be left,
  cancellation has separate requested and terminal states, and a stage cannot
  move backwards inside one attempt.
- **AC2:** `OperationStore` persists operation identity, source, route, server
  job IDs, progress, attempts, errors, retry and retention timestamps. A
  callback carrying an unexpected `operation_id` cannot update another
  operation.
- **AC3:** Initializing schema v2 over a legacy `cloud_jobs` database creates a
  SQLite backup before migration. In-flight legacy jobs become `RETRYABLE`,
  terminal states remain terminal, and rerunning migration creates no duplicate
  operations.
- **AC4:** A recording is first written as `source.part` and becomes available
  for processing only through an atomic rename after the writer has closed it.
  Imported files use a hardlink when possible and otherwise an atomic copy after
  capacity checks. Source size is limited to 4 GiB.
- **AC5:** Spool paths are confined below the configured spool root. Expired
  retryable assets can be cleaned without touching paths outside that root, and
  an imported original is never removed by spool cleanup.
- **AC6:** Canonical schema `1.0` validates operation identity, source metadata,
  route, transcript segments, summary references, warnings, and provenance.
  Segment timestamps cannot be inverted, unknown major versions fail, and
  additive fields on version 1 are ignored.
- **AC7:** Canonical JSON is written through a temporary file, flushed, and
  atomically renamed. `OperationStore` accepts `COMPLETED` only when the
  referenced canonical result exists and validates for the same operation.
- **AC8:** The existing `FileCloudJobTracker` remains usable for one
  compatibility release while migrated v2 operations are available for the new
  coordinator.
- **AC9:** The current push-to-talk flow adopts the finalized recorder WAV into
  the durable spool before starting `TranscribeWorker`. A successful callback
  saves canonical JSON before history or insertion and removes the spool source
  only after that save succeeds.
- **AC10:** A dictation transcription error becomes `RETRYABLE` and keeps its
  source. Cancellation moves through `CANCEL_REQUESTED` to `CANCELLED`; a late
  successful callback cannot save a result or insert text.

## Failure behavior and assumptions

- Corrupt legacy rows fail migration transactionally; the original database and
  its backup remain available.
- A stale callback is a no-op when using the guarded update API, not a mutation
  followed by rollback.
- Hardlink support is an optimization only; copy is the portable fallback.
- Free-space preflight is conservative and applies to the copy path.
- Source hashes use SHA-256 and are calculated from the durable spool asset.
- Retention cleanup requires an explicit deadline recorded by the coordinator;
  it does not infer deletion from file age alone.
- The current cloud ledger remains the source for the compatibility wrapper in
  this slice. New coordinator integration will switch new work to
  `OperationStore` before the wrapper is removed.

## Likely interfaces

- `OperationKind`, `OperationStatus`, `OperationStage`, `OperationRecord`
- `OperationStore.create(...)`, `transition(...)`, `guarded_transition(...)`
- `OperationStore.list_retryable()`
- `SpoolManager.prepare_recording(...)`, `finalize_recording(...)`
- `SpoolManager.import_source(...)`, `cleanup_expired(...)`
- `validate_canonical_result(...)`, `write_canonical_result(...)`

## Traceable test plan

- AC1 → valid forward transitions; stage regression; requested cancellation;
  terminal resurrection rejection.
- AC2 → persistence round-trip; progress and retry metadata; stale-operation
  guarded update.
- AC3 → representative v1 migration; backup existence; idempotent reopen;
  terminal-state preservation.
- AC4 → recording part/final handoff; hardlink or copy import; size rejection.
- AC5 → cleanup removes only expired spool operations and preserves originals.
- AC6 → valid result; inverted timestamp; unsupported major version; additive
  field compatibility; invalid summary reference.
- AC7 → atomic result round-trip; completion before result rejected; mismatched
  operation result rejected.
- AC8 → existing `tests/test_cloud_jobs.py` remains green.
- AC9 → recorded-file adoption and canonical dictation completion; main-window
  wiring verification plus the full desktop regression suite.
- AC10 → coordinator cancellation test and existing stale-token worker tests.
