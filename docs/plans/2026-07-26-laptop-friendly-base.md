# Laptop-friendly Windows base installer

## Outcome

The cloud-first Windows installer does not ship the optional MFCC speaker
diarization stack. The source distribution defines a separate, hash-locked
capability pack; a user-facing frozen-pack installer is a later deliverable.

## Acceptance criteria

- `librosa`, `scikit-learn`, `scipy`, `numba`, and `llvmlite` are absent from
  the base dependency lock and PyInstaller bundle.
- The optional diarization input and lock are published alongside other
  dependency manifests for source/development installations.
- Auto-routing selects local diarization only when the pack is installed.
- An unavailable explicit local route becomes `disabled`, not a silent heavy
  download.
- UI labels the unavailable local route and prevents selecting it.
- Post-processing records `LOCAL_DIARIZATION_PACK_REQUIRED` when disabled.
- The base frozen executable starts without the optional stack.

## Verified local artifact

On the same Python 3.11 build environment, the installer changed from
110,650,103 bytes to 53,573,407 bytes. The new frozen bundle contained zero
paths belonging to the five excluded packages and remained alive after a
five-second startup smoke.

This is a local unsigned development artifact, not a GA release.
The current frozen application intentionally disables local diarization; the
optional Python lock by itself does not make packages importable inside an
already frozen installation.
