# Lightweight base installer

## Goal

Ship a Windows base installer suitable for ordinary laptops while preserving
OpenRouter STT and bundled whisper.cpp. Heavy ONNX/Torch support becomes an
explicit optional runtime instead of an unconditional dependency.

## Non-goals

- Do not build an in-app downloader for optional Python runtimes in this slice.
- Do not remove whisper.cpp or local transcription.
- Do not silently leave unavailable backends selectable.
- Do not split local MFCC diarization yet; measure the base after removing
  ONNX/Torch first.

## Acceptance criteria

### AC1. Honest backend availability

- The transcriber module exposes the available backend IDs.
- ONNX appears only when `transformers`, `optimum.onnxruntime`, and
  `onnxruntime` are importable.
- Faster Whisper appears only when its runtime imports successfully.
- OpenRouter remains available without local ML dependencies.

### AC2. Safe config fallback

- A saved backend that is unavailable in the installed build falls back to
  whisper.cpp.
- The corrected backend is persisted so the app does not fail on every launch.
- The UI lists only available backends.

### AC3. Dependency split

- `requirements.txt` contains the base desktop/runtime dependencies.
- `requirements-local-onnx.txt` owns ONNX Runtime, Optimum, Transformers and
  their compatible constraints.
- `requirements-assistant.txt` owns the disabled assistant dependencies.

### AC4. Base packaging

- PyInstaller explicitly excludes ONNX, Transformers, Torch and openWakeWord
  from the base artifact even when they exist in the build environment.
- The Python 3.11 base build and Inno installer complete successfully.
- The resulting base onedir and installer sizes are measured and reported.

## Test plan

- AC1 → backend availability tests with import-spec mocks.
- AC2 → pure backend selection fallback test; UI consumes that result.
- AC3 → static requirements ownership test.
- AC4 → static spec exclusion test, Python 3.11 build, smoke-start, Inno compile.

## Lead Architect Report

### F1. Optional backend determines the entire distribution graph

Severity: Required  
Area: Module boundary / Release architecture

Evidence:
- ONNX support pulls Transformers and Torch into every build.
- The measured onedir is 966.3 MiB; `torch_cpu.dll` alone is 290.9 MiB.
- Inno Setup fails on deep Torch license paths.

Required improvement:
- Make backend capability explicit and keep optional runtime dependencies out of
  the base distribution.

### Accepted risk

The optional requirements are install-time artifacts, not yet a polished
in-app component downloader. The UI must therefore hide an unavailable backend
rather than advertise a flow that does not exist.
