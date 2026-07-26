# Local diarization correctness contract

## Scope

Keep the existing lightweight MFCC pipeline as an optional local fallback.
Cloud diarization remains the default for laptop users. This change fixes
deterministic correctness defects; it does not claim production speaker
recognition quality without a corpus.

## Acceptance criteria

- Every emitted segment has finite, non-negative timestamps and `start <= end`.
- Silence produces no fabricated speech segment.
- The final audio tail participates in feature extraction.
- Requested `min_speakers` is respected whenever enough voiced windows exist.
- The configured maximum and the hard safety maximum are respected.
- Agglomerative clustering works with both `metric=` and legacy `affinity=`
  scikit-learn constructors.
- Smoothing cannot collapse a caller-required speaker count.
- Speaker IDs are stable by first chronological appearance.
- Short-speaker cleanup never removes the configured minimum and only merges a
  speaker when both duration and evidence count are weak.
- Transcription alignment normalizes invalid input bounds and preserves every
  non-empty transcript segment.
- Sentence-only formatting preserves the remainder instead of dropping it.
- DER and JER scoring are available as deterministic, versioned benchmark
  utilities with synthetic reference tests.

## Honest gate

The code can enforce timestamp, determinism and scoring correctness locally.
The product thresholds `DER <= 18%` and `JER <= 28%` remain unproven until a
fixed, human-annotated audio corpus is supplied.
