# P0 Release Safety

## Behavior spec

Goal: prevent MindType from executing untrusted update artifacts and ensure
generated reports cannot execute user-controlled markup, load remote code, or
silently overwrite an earlier report.

Non-goals:

- Do not re-enable automatic updates until a signed manifest, mandatory SHA-256,
  redirect validation, and platform signature verification exist.
- Do not redesign the report or replace its current Markdown-like formatting.
- Do not add the cloud job lifecycle in this slice.

Assumptions:

- Version checks may remain available because they do not execute downloaded code.
- A disabled updater must fail closed even if internal worker methods are called
  directly.
- Inline CSS is retained for browser and `QTextDocument` compatibility; scripts,
  frames, network requests, forms, and plugins are forbidden by CSP.

Acceptance criteria:

- AC1: `download_update()` returns a stable disabled error before reading a
  manifest URL, touching the filesystem, or starting a network request.
- AC2: `install_update()` always returns `False` and never launches a process or
  exits the application.
- AC3: when an update is found, the UI reports the version but does not offer or
  connect an install action.
- AC4: generated HTML contains no script or remote asset and declares a CSP that
  blocks scripts and network access.
- AC5: every result-derived text value is escaped, including LaTeX-looking
  summary text, filenames, model names, speaker names, segments, and processed
  text, while supported headings, lists, tables, and bold formatting still work.
- AC6: `generate()` never overwrites an existing report; a colliding export gets
  a deterministic unique stem, shared by HTML and PDF in `both` mode, and the
  generated paths are stored on the file task for UI consumers.

Failure behavior:

- Disabled updates report an explicit maintenance message rather than a generic
  download error.
- Existing report files remain byte-for-byte unchanged after a colliding export.
- If PDF generation fails, the HTML fallback still uses the reserved unique stem.

Likely interfaces/files:

- `app/updater.py`
- `app/main.py`
- `app/report_generator.py`
- `tests/test_updater.py`
- `tests/test_report_generator.py`

## Traceable test plan

- AC1 → `test_download_is_disabled_before_any_network_or_file_access`
- AC2 → `test_install_is_disabled_without_process_or_exit`
- AC3 → UI handler test where practical, plus direct inspection of the signal
  connection branch.
- AC4 → `test_generated_report_has_strict_csp_and_no_scripts`
- AC5 → `test_generated_report_escapes_all_untrusted_fields` and
  `test_latex_like_summary_is_plain_escaped_text`
- AC6 → `test_generate_preserves_existing_report_with_unique_name` and
  `test_both_formats_share_unique_stem`, plus worker path handoff verification

# Lead Architect Report

## Review Context

- Mode: Planning
- Scope reviewed: update execution and report export boundaries
- Evidence scope: updater service, update UI handlers, report generator, workers,
  and existing unit tests
- Main business capability: safe desktop release and durable user exports
- Soft gate status: Required Follow-Up

## Findings

### F1. Update checking and code execution share one enabled service

Severity: Required

Area: Module boundary / Security / Lifecycle

Evidence:

- `Updater` owns version checks, artifact download, integrity checks, process
  launch, and application exit.
- Hash validation is optional and the UI connects an available update directly
  to download and execution.

Risk:

- Any weakness in the manifest or transport path crosses directly into native
  code execution.

Business impact:

- A compromised update path compromises every installed desktop client.

Required improvement:

- Keep version discovery available but introduce a fail-closed boundary that
  disables artifact download and execution until the complete trust chain ships.

Acceptance criteria:

- AC1–AC3 pass, and no subprocess/network side effect occurs through the disabled
  public methods.

### F2. Report rendering mixes trusted template markup with untrusted content

Severity: Required

Area: Module boundary / Export / Security

Evidence:

- User-controlled summary text can be restored as raw LaTeX after escaping.
- The generated report loads MathJax from a CDN and is opened as an active HTML
  document.
- Export paths are derived from the source filename and reused.

Risk:

- A transcription or summary can inject active markup, trigger remote requests,
  or overwrite an existing export.

Business impact:

- Opening a report can disclose data or execute attacker-controlled browser
  behavior; repeated processing can destroy a prior user artifact.

Required improvement:

- Render a static, offline document, escape all result-derived values, and reserve
  a non-colliding output stem before writing any format.

Acceptance criteria:

- AC4–AC6 pass without regressing current report structure.

## Architecture Notes

- Accepted risk: inline CSS remains necessary for the current HTML/PDF rendering
  stack and is explicitly allowed by CSP.
- Missing decision: the future signed update manifest and platform verification
  design belongs to a separate architecture decision.
- Suggested next review point: before re-enabling updater downloads or adding a
  cloud-backed durable job model.
