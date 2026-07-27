# Windows GA benchmark harness

## Outcome

GA quality claims are produced from versioned evidence. A missing corpus,
prediction set, or runtime observation is reported as `not_measured`; it never
silently passes.

## Local scope

- Deterministic Unicode-aware WER and CER scoring.
- Weighted aggregation by required corpus category.
- Nearest-rank p50/p95 latency and real-time-factor aggregation.
- Explicit pass/fail/not-measured evaluation for every GA gate.
- Machine-readable JSON input and report output.
- Failure-recovery tests for the durable desktop lifecycle.

## Evidence that is intentionally absent

- No synthetic corpus is counted toward the five-hour minimum.
- No cloud latency, provider quality, insertion compatibility, Narrator, or
  horizontal-overflow number is invented.
- Model weights and private recordings are not committed with this harness.

## Input format

The scorer accepts a JSON object containing `cases` and optional operational
`metrics`. Every case contains a stable ID, category, duration, reference, and
hypothesis. Speech categories use punctuation-insensitive case-folded scoring;
`code_path` uses case-sensitive verbatim CER.

## Exit contract

- Exit `0`: every required GA gate is measured and passing.
- Exit `1`: at least one measured gate fails or required evidence is missing.
- Exit `2`: invalid input.

