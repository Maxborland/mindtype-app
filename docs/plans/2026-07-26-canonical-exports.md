# Canonical export contract

## User outcome

Every completed file operation leaves portable artifacts that can be opened
without MindType. Exporters read validated canonical JSON only; HTML is never
scraped to recover data.

## Acceptance criteria

- One bundle produces TXT, Markdown, JSON, SRT, VTT, DOCX, HTML and PDF.
- The raw transcript is the default and is never replaced with summary or
  processed text.
- Timestamps and speaker display names are retained where the format supports
  them.
- Summary is explicitly labelled AI-generated and lists its canonical source
  segment IDs.
- JSON is a validated, byte-independent projection of the canonical result.
- HTML is static, escaped, has a strict CSP and contains no remote assets or
  JavaScript.
- Subtitle payloads escape markup-like hostile content.
- DOCX is valid OOXML and stores user text as XML text, not markup.
- Every output is written through a temporary file and atomically published.
- Windows filenames are sanitized, reserved device names are rejected, and an
  existing bundle is never overwritten.
- Export failure does not delete or invalidate the already-saved canonical
  result.
