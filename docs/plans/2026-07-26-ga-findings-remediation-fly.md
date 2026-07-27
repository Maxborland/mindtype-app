# Windows GA findings remediation and Fly topology

## Goal

Close the independent repository-review findings through vertical, user-visible
flows while keeping the desktop contract intact:

> Capture or select media, persist it durably, process it locally or through
> MindType Cloud, save one canonical result, then export or insert without data
> loss or duplicate charging.

MindType Cloud will run on Fly.io. The Windows desktop, WASAPI capture,
insertion adapters, and the optional local fallback remain on the user's
computer.

## Non-goals

- Do not deploy or provision paid Fly resources from the desktop repository.
- Do not create a second production backend; extend the existing private
  `Maxborland/mindtype-site` service that owns `mindtype.space`.
- Do not host heavyweight STT or LLM model weights in the desktop installer.
- Do not add Redis, Kubernetes, collaboration, macOS, or mobile support.
- Do not enable the updater before the signed release-manifest gate is complete.

## Fly topology

- Every Fly resource name starts with `mindtype-`; existing non-MindType Fly
  applications are out of scope and must not be changed.
- The production application is `mindtype-cloud-api` with `web` and `worker`
  process groups.
- Managed Postgres is named `mindtype-cloud-db`.
- The private Tigris bucket is named `mindtype-cloud-artifacts`.
- Staging resources use the `mindtype-cloud-staging-` prefix.
- Fly Managed Postgres is the authority for accounts, jobs, idempotency,
  retention, pricing versions, reservations, and finalized usage.
- A private Tigris bucket stores upload parts, source media, canonical results,
  and temporary provider artifacts.
- The web and worker root filesystems are disposable.
- Initial job claiming uses PostgreSQL transactions and
  `FOR UPDATE SKIP LOCKED`; Redis is deferred until measured load requires it.
- The backend may change upstream STT, diarization, and LLM providers without
  changing the desktop canonical schema.

## Acceptance criteria

### Desktop production wiring

- **AC1:** MindType Cloud routes are executed through
  `CloudSessionManager -> MindTypeCloudClient -> MindTypeCloudExecutor`; the
  perpetual license key is sent only to `/api/license/session`.
- **AC2:** A cloud file retry or desktop restart polls the persisted server job
  ID and never creates a second remote job for the same operation.
- **AC3:** `OperationStore` is the only writable desktop lifecycle store.
  Legacy `cloud_jobs` is read only during migration and is not updated by UI
  callbacks.

### Recovery and data safety

- **AC4:** Startup recovery exposes retryable file and dictation operations.
- **AC5:** A canonical result saved before a crash is visible after restart,
  projections are generated idempotently, and ACK occurs only after the local
  result is durable.
- **AC6:** A system-audio capture cannot start while any thread from the
  previous capture still owns its queue or WAV path.
- **AC7:** A timed-out system-audio stop leaves a recoverable session that can
  be finalized without an orphaned or cross-wired recording.
- **AC8:** Clipboard insertion restores every supported Win32 clipboard format,
  not only Unicode text. A failed restore is surfaced and prevents fallback
  duplication.
- **AC9:** Imported media larger than 4 GiB or longer than 8 hours is rejected
  before processing or cloud usage.

### Licensing and release

- **AC10:** Server-issued Ed25519 leases are the entitlement authority; the
  client HMAC cache and local trial are compatibility-only and cannot grant
  cloud access.
- **AC11:** CI rejects undefined names and duplicate dictionary keys.
- **AC12:** A tagged release remains fail-closed until runtime/model manifests,
  Authenticode signatures, SBOM, provenance, and an Ed25519-signed update
  manifest are all present.

### Fly backend

- **AC13:** Upload parts and final objects are account-scoped, checksum
  verified, resumable, and stored outside Fly Machine filesystems.
- **AC14:** Reserve/finalize is transactional; one stage/job has at most one
  finalized usage record and repeated finalize is a no-op.
- **AC15:** Source audio is deleted after durable result plus client ACK;
  unfinished uploads expire after seven days and unacknowledged results after
  24 hours.
- **AC16:** Logs contain no filenames, audio, transcript, summary, access
  tokens, refresh tokens, or license keys.

## Failure behavior and edge cases

- Network, provider, or `402` errors retain the local source and enter
  `RETRYABLE`.
- A late callback cannot move a terminal operation.
- If a system-audio driver blocks beyond the stop timeout, the session remains
  owned and a new recording is rejected until finalization.
- Rich clipboard content is either fully restored or reported as a clipboard
  restoration failure.
- Unsupported canonical major versions fail closed.
- Missing backend source or deployment credentials block only the Fly backend
  workstream, not the local desktop remediations.

## Traceable test plan

- AC1 -> production composition test rejects license-key cloud bearer.
- AC2 -> restart/retry HTTP integration test observes one POST and repeated GET.
- AC3 -> UI file lifecycle test observes writes only in `operations`.
- AC4 -> startup recovery test returns file and dictation work.
- AC5 -> saved-before-transition recovery returns a visible completed item.
- AC6/AC7 -> blocked WASAPI recorder test rejects restart until both threads
  finalize, then starts with a new immutable session.
- AC8 -> Win32 clipboard test round-trips text plus a non-text format.
- AC9 -> import validation tests reject 4 GiB+ and 8 hour+ media.
- AC10 -> cloud composition requires a verified lease and fresh access token.
- AC11 -> CI/static-policy test requires Ruff `F821,F601`.
- AC12 -> release-workflow tests require the signed update-manifest artifact.
- AC13-AC16 -> backend integration tests against Postgres and S3-compatible
  storage in the backend repository.

## Connected backend worktree

- The existing private backend was identified as
  `Maxborland/mindtype-site` and cloned separately to
  `C:\Users\butma\.t3\worktrees\mindtype-site\mindtype-cloud-fly`.
- Backend changes stay on local branch `codex/mindtype-cloud-fly-local`;
  the desktop repository does not contain a nested backend checkout.
- Fly resources are still unprovisioned. Local descriptors use
  `mindtype-cloud-api`; the future database and object bucket remain
  `mindtype-cloud-db` and `mindtype-cloud-artifacts`.

## Local implementation status — 2026-07-27

All acceptance criteria in this document that can be proven locally are
implemented. Verification evidence:

- 741 desktop tests pass on the Python 3.11 release interpreter, including
  operation recovery, billing idempotency, updater trust, insertion, audio,
  exporters, licensing, VAD, and local diarization tests.
- Ruff `F821,F601`, `compileall`, and release-ready model/runtime manifest
  verification pass.
- A clean PyInstaller onedir build succeeds from the global Python 3.11
  launcher while installing hashed build dependencies only into
  `.venv-build`.
- `MindType.exe --smoke-test` exits with code 0, creates no per-user state,
  verifies all packaged native hashes, discovers Windows Credential Manager,
  and imports the critical cloud/audio/insertion/coordinator boundaries.
- The frozen runtime contains the official pinned whisper.cpp CPU files and
  both manifests. The unverified legacy Vulkan and generic CPU DLLs are absent.
- Inno Setup 6.6.1 produces the local 45,013,593-byte installer
  `MindType-0.0.0-Setup.exe` with SHA-256
  `f85ea02d4fdb9fdca563e2ed48f8a90b74b702ca0851a039879b4918ade47af8`.
  Its `NotSigned` status is expected for a local artifact and blocks release.
- The connected backend passes 187 tests, ESLint, TypeScript, Next.js
  production build, and `npm audit --omit=dev` with zero reported
  vulnerabilities.
- `flyctl config validate -c fly.toml` passes for `mindtype-cloud-api`.

The Windows release workflow now runs the frozen smoke test before signing.
No Fly application, release tag, installer signature, commit, push, or pull
request was created by this local pass.

## Remaining GA gates requiring external or manual evidence

These items are intentionally not marked complete by automated local tests:

- provision `mindtype-cloud-api`, `mindtype-cloud-db`, and
  `mindtype-cloud-artifacts`, then configure production secrets;
- exercise real Deepgram and OpenRouter accounts without logging content;
- obtain the Windows Authenticode certificate and produce a signed RC
  installer plus signed update manifest;
- run the real Windows application compatibility insertion matrix and reach
  the 98% gate;
- complete the Narrator, keyboard-only, high-contrast, and permissions
  walkthrough;
- run the versioned five-hour RU/RU-EN corpus and meet WER/CER/DER/JER and
  latency thresholds;
- perform the staged 10%/50%/100% production rollout.

Before running more than one Fly web machine, replace the current in-process
public rate limiter with a shared store. Before removing the remaining
`unsafe-inline` CSP allowance, migrate Next.js rendering to request nonces.
