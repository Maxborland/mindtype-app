# Reliable Windows insertion contract

## Goal

Recognition success is durable independently of insertion success, while
automatic insertion never targets MindType or a stale window and never loses
known clipboard text.

## Acceptance criteria

- AC1: the target HWND captured before recording must still exist and must not
  belong to MindType before insertion begins.
- AC2: failure to restore the exact target focus aborts insertion instead of
  typing into another application.
- AC3: insertion methods run through an explicit clipboard paste -> Unicode
  input -> UI Automation ValuePattern pipeline with a typed result.
- AC4: a clipboard snapshot failure skips clipboard mutation; after any later
  clipboard-path failure, the known previous text is restored in `finally`.
- AC5: Unicode input handles UTF-16 surrogate pairs and verifies every
  `SendInput` call.
- AC6: failed insertion leaves the canonical transcript and history untouched.
- AC7: modifier-only and unknown hotkeys are rejected.
- AC8: `RegisterHotKey` IDs use a Windows global atom and release it on stop,
  rather than Python's process-randomized `hash()`.
- AC9: focused unit tests cover stale targets, clipboard restoration, fallback
  order, surrogate pairs, invalid hotkeys, and atom cleanup.

## Constraints

- Keep the existing boolean `insert_text()` API as a compatibility wrapper
  while exposing the typed result for UI diagnostics.
- Do not add a heavy UI Automation dependency to the laptop-friendly base
  installer without proving its frozen-build behavior.
- Do not claim the GA 98% application matrix from unit tests; that remains a
  supervised Windows compatibility gate.
