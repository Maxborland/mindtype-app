# Windows accessibility contract

## Outcome

The primary recording and file-processing workflows remain usable with
Narrator and keyboard-only navigation. Accessibility metadata follows the
current UI language and status is communicated as text, not only through
colour or animation.

## Acceptance criteria

- Form labels are associated with the first focusable control in their row.
- Interactive controls have a non-empty accessible name derived from visible
  text, the form label, or an explicit tooltip.
- Glyph-only buttons are keyboard focusable and have a readable name.
- Recording, processing, success, and error overlays expose a textual state.
- Reduced motion disables overlay fades and continuous waveform animation.
- The main window has a textual status surface for operational updates.
- Reapplying accessibility after a language change refreshes derived names.
- Tests exercise composite form rows, glyph buttons, status text, and reduced
  motion without depending on a screen reader installation.

