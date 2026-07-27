# Durable cloud jobs: desktop foundation

## Goal

Persist every cloud-backed file operation before network work starts so that
MindType can recover it after a crash or restart without losing the source
file, route, result metadata, or stable idempotency key.

## Non-goals

- No MindType Cloud upload API or server implementation in this slice.
- No automatic retry that could duplicate third-party OpenRouter charges.
- No resumable upload until a provider exposes an idempotent asynchronous job API.
- No persistence of API keys, transcript text, or audio bytes in the database.

## Acceptance criteria

- **AC1:** Creating a job stores a stable job ID, caller-supplied idempotency
  key, source path, operation, provider-neutral route, timestamps, and state.
  Reusing an idempotency key for the same operation returns the original job;
  reusing it for different source or route is rejected as a conflict.
- **AC2:** Only declared lifecycle transitions are accepted. `COMPLETED`,
  `FAILED`, and `CANCELLED` are terminal and cannot return to a successful state.
- **AC3:** On startup, jobs left in `CREATED`, `UPLOADING`, or `PROCESSING`
  become `RETRYABLE`; terminal jobs remain unchanged.
- **AC4:** Errors, attempt count, remote job ID, progress, and bounded JSON result
  metadata survive closing and reopening the store.
- **AC5:** A recoverable job whose source file no longer exists becomes `FAILED`
  with an explicit missing-source error instead of being retried.
- **AC6:** The store is safe to call from the UI and worker threads by using
  short SQLite transactions and a separate connection per operation.
- **AC7:** A cloud-backed `FileTask` is registered before its worker starts,
  mirrors progress and terminal status into the ledger, and is restored as
  `PENDING` after restart when its durable job is `RETRYABLE`.

## Assumptions

- The input file selected by the user is the durable source for this slice.
- Recorded temporary WAV files need a later spool/copy step before they can use
  the same lifecycle safely.
- Retry is user-initiated until MindType Cloud supports server-side idempotency.

## Likely interfaces

- `CloudJobState`
- `CloudJob`
- `CloudJobStore.create_or_get(...)`
- `CloudJobStore.begin_attempt(...)`
- `CloudJobStore.transition(...)`
- `CloudJobStore.recover_incomplete()`
- `CloudJobStore.list_retryable()`
- `FileCloudJobTracker`

## Test plan

- AC1 → creating and reopening a job; duplicate idempotency key returns one row.
- AC2 → valid transition succeeds; invalid and terminal transitions raise.
- AC3 → recovery converts only in-flight states to `RETRYABLE`.
- AC4 → persisted error, attempt, remote ID, progress, and result metadata round-trip.
- AC5 → recovery marks a missing source as terminal `FAILED`.
- AC6 → concurrent progress updates complete without connection/thread errors.
- AC7 → file task register/sync/reopen/restore round-trip.
