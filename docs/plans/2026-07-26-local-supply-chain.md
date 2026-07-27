# Local supply-chain and GA artifact contract

## Goal

Every Windows GA artifact is built from reviewable dependency inputs, exact
Python dependency locks with hashes, and emits a validated CycloneDX SBOM.
Optional local ML packs remain separate from the laptop-friendly base install.

## Non-goals

- Do not publish a release or tag.
- Do not invent whisper.cpp source commits, model URLs, or licenses.
- Do not add optional ONNX, Torch, or assistant dependencies to the base app.
- Do not claim provenance for the currently bundled native binaries until their
  upstream build identity is known.

## Acceptance criteria

- AC1: runtime, development, local ONNX, and assistant dependencies have
  separate `.in` source files.
- AC2: each dependency set has a Python 3.11 Windows lock containing exact
  versions and SHA-256 hashes.
- AC3: the canonical Windows workflow installs base and development
  dependencies with `pip --require-hashes`.
- AC4: release dependency inputs and locks are uploaded with the installer.
- AC5: the workflow generates and validates a CycloneDX JSON SBOM and refuses
  a tag release if the SBOM is absent or invalid.
- AC6: static tests reject unhashed release installation or missing SBOM
  publication.
- AC7: optional ML dependencies remain absent from the base lock.
- AC8: a native runtime/model manifest schema and verifier fail closed on
  missing hashes, size mismatches, non-HTTPS URLs, or unknown license metadata.
- AC9: the current native runtime is not marked release-ready until its exact
  whisper.cpp commit/build provenance is supplied.

## Assumptions

- Windows GA uses CPython 3.11 x64.
- Lockfiles are regenerated deliberately, not during normal application startup.
- Repository variables and signing credentials are configured outside this
  local worktree.

## Test and verification map

- AC1/AC2/AC7 -> dependency layout and lock-content tests.
- AC3/AC4/AC5/AC6 -> static workflow contract tests plus local SBOM validation.
- AC8/AC9 -> manifest verifier behavior tests using temporary artifacts.
- Full regression -> Python 3.11 and current Python test suites.
