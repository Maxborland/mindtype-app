# MindType Cloud desktop client contract

## Local outcome

The desktop owns a provider-neutral, testable HTTP boundary for resumable
uploads and asynchronous transcription/summary jobs. It can be integrated once
the backend repository and session endpoint are available.

## Acceptance criteria

- HTTPS-only base URL outside loopback development.
- Bearer access token; no perpetual license key in `/v1` calls.
- One token refresh after HTTP 401.
- Provider-neutral typed errors including retryability and retry-after.
- Eight MiB default parts, per-part and whole-file SHA-256.
- Already uploaded parts are skipped after resume.
- An existing upload ID is recovered with `GET`, not a duplicate `POST`.
- A retried part keeps the same number and bytes.
- Local paths and filenames are not sent when an upload is created.
- Job creation carries `Idempotency-Key`.
- Recovery with an existing server job ID performs `GET`, never a new `POST`.
- Result is validated as canonical JSON before being returned.
- ACK is a separate call made only by the coordinator after local atomic save.
- Cancellation addresses the existing server job.
- `/api/license/session` adopts a 15-minute in-memory access token.
- Refresh tokens are stored only through the Windows keyring backend.
- The entitlement lease is Ed25519-verified before the session is adopted.
- Authoritative license denial clears the local session; network errors do not
  destroy a still-valid offline lease.

## Not implemented here

- Backend endpoints, storage, billing, reserve/finalize, and retention workers.
- Backend session issuance and refresh-token exchange. The desktop session
  response and secure persistence boundary exist, but no refresh endpoint was
  specified or supplied by the backend.
- UI activation of the client before an end-to-end backend exists.
