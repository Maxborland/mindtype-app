# MindType Windows GA benchmarks

The benchmark runner converts versioned transcript observations and operational
metrics into one fail-closed GA report.

```powershell
python -m benchmarks.ga_quality `
  benchmarks\observations.example.json `
  --output artifacts\ga-quality-report.json
```

The committed example has no recordings and therefore exits with code `1`.
That is intentional: missing evidence is `not_measured`, never a pass.

## Adding a corpus

Keep recordings, human references, and model weights in a separately versioned
corpus. Give every case a stable `case_id`, one of the required categories, its
actual duration, reference, hypothesis, and route. `code_path` is scored
case-sensitively; speech categories use Unicode-normalized, case-folded,
punctuation-insensitive scoring.

Operational metrics use:

```json
{
  "insertion_success": {"value": 0.99, "sample_count": 100}
}
```

Do not report a metric with `sample_count: 0`; it remains `not_measured`.

