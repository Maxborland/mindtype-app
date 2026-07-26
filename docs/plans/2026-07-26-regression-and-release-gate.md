# Regression and Windows release gate

## Goal

Restore one trustworthy automated gate for the current provider/backend
architecture, then make the Windows release workflow deterministic and
non-competing.

## Non-goals

- Do not restore removed legacy `Transcriber` internals only to satisfy stale
  tests.
- Do not publish a release, create a tag, or upload artifacts.
- Do not claim installer signing until a real certificate and CI secret exist.
- Do not add Linux/macOS packaging to the Windows-first release gate.

## Acceptance criteria

### AC1. Current transcriber contract

- `tests/test_transcriber.py` tests the public backend factory/facade contract.
- The default and explicit backend selection remain covered.
- Cancellation forwarding and optional download-source forwarding remain
  observable without requiring old `_pick_device` or model repository globals.

### AC2. Public crash-report contract

- Breadcrumb tests use `add_breadcrumb()` and `get_breadcrumbs()`, not deleted
  module globals.
- Reports are checked against their current stable section names.
- The bounded breadcrumb history remains verified through its public API.

### AC3. Cross-platform hotkey tests

- Windows and POSIX admin checks are testable on a Windows CI host.
- Tests mock the platform dependency at its import boundary instead of assuming
  `os.getuid` exists on Windows.

### AC4. Provider registry and cache

- The registry test includes MindType Cloud as the sixth provider.
- An empty model list is cached for the normal TTL and does not trigger repeated
  network calls.
- Forced refresh still performs a new request.

### AC5. Full regression gate

- `python -m pytest -q` collects and runs without ignores.
- `python -m compileall -q app` and `git diff --check` pass.
- Runtime and build requirements resolve together on the workflow's Python 3.11.

### AC6. Canonical Windows release workflow

- A single tag-triggered workflow owns the GitHub Release.
- Actions are pinned to immutable commit SHAs.
- Workflow runs the full regression gate before packaging.
- The artifact published by the workflow exists at the path the workflow names.
- Signing is an explicit gated step and unsigned artifacts are not presented as
  signed.
- Uninstall preserves user recordings, history, models, and configuration.

## Test plan

- AC1 → replace legacy transcriber tests with facade/factory behavior tests.
- AC2 → crash-report section, public breadcrumb history, bounded history tests.
- AC3 → Windows admin and POSIX root/non-root tests with import-boundary mocks.
- AC4 → provider registry includes cloud; empty-list cache test becomes green.
- AC5 → full pytest, compileall, diff check.
- AC5 → clean Python 3.11 dependency resolution and `pip check`.
- AC6 → parse workflow YAML, verify one release trigger/owner, referenced scripts
  and artifact paths, immutable `uses:` references, and preservation of user
  data during uninstall.

## Lead Architect Report

### Review context

- Mode: Recovery.
- Scope: test contracts, provider facade, release workflows.
- Soft gate: Required follow-up before release.

### F1. Tests encode a removed backend implementation

Severity: Required  
Area: Module boundary / Testing

Evidence:
- `tests/test_transcriber.py` imports private Faster Whisper helpers from the
  provider-neutral facade.
- The production facade now delegates to whisper.cpp, ONNX, OpenRouter, or
  Faster Whisper backends.

Risk:
- Reintroducing those names would reverse the dependency boundary and make the
  facade vendor-specific again.

Required improvement:
- Test backend selection and delegation through the public facade.

### F2. Two workflows own the same tag release

Severity: Required  
Area: Release lifecycle

Evidence:
- `.github/workflows/build-release.yml` and `.github/workflows/release.yml` both
  react to `v*` tags and call a GitHub Release action.

Risk:
- Concurrent jobs can publish inconsistent assets or race on the same release.

Required improvement:
- Keep one Windows-first canonical workflow and remove the competing tag owner.

### F3. Empty provider results bypass the cache

Severity: Required  
Area: Provider boundary / Performance

Evidence:
- `BaseLLMProvider.fetch_models()` tests cache truthiness instead of whether the
  cache exists.

Risk:
- A valid empty response causes repeated cloud requests and unnecessary latency.

Required improvement:
- Treat an empty list as a valid cached result until TTL expiry.
