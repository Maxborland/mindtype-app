from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_speech_score_is_unicode_case_and_punctuation_aware() -> None:
    from benchmarks.ga_quality import score_text

    score = score_text(
        "Привет, Ёлка!",
        "привет ёлка",
        unit="word",
        profile="speech",
    )

    assert score.errors == 0
    assert score.reference_units == 2
    assert score.rate == 0.0


def test_verbatim_code_cer_preserves_case_and_symbols() -> None:
    from benchmarks.ga_quality import score_text

    exact = score_text(
        "--output src/MyFile.py",
        "--output src/MyFile.py",
        unit="character",
        profile="verbatim",
    )
    changed = score_text(
        "--output src/MyFile.py",
        "--output src/myfile.py",
        unit="character",
        profile="verbatim",
    )

    assert exact.rate == 0.0
    assert changed.errors == 2


def test_score_cases_uses_weighted_error_counts_and_runtime_observations() -> None:
    from benchmarks.ga_quality import BenchmarkCase, score_cases

    cases = [
        BenchmarkCase(
            case_id="clean-1",
            category="clean_ru",
            duration_ms=10_000,
            reference="один два",
            hypothesis="один",
            press_to_insert_ms=1_000,
        ),
        BenchmarkCase(
            case_id="clean-2",
            category="clean_ru",
            duration_ms=20_000,
            reference="три четыре пять шесть",
            hypothesis="три четыре пять шесть",
            press_to_insert_ms=3_000,
        ),
        BenchmarkCase(
            case_id="file-1",
            category="noisy_ru",
            duration_ms=20_000,
            reference="шумная запись",
            hypothesis="шумная запись",
            processing_ms=5_000,
        ),
    ]

    metrics = score_cases(cases)

    assert metrics["clean_ru_wer"].value == pytest.approx(1 / 6)
    assert metrics["clean_ru_wer"].sample_count == 2
    assert metrics["cloud_dictation_p50_seconds"].value == 1.0
    assert metrics["cloud_dictation_p95_seconds"].value == 3.0
    assert metrics["cloud_file_rtf"].value == 0.25
    assert metrics["corpus_duration_hours"].value == pytest.approx(50 / 3600)


def test_missing_ga_evidence_is_not_measured_never_passed() -> None:
    from benchmarks.ga_quality import GateStatus, evaluate_ga_gates

    report = evaluate_ga_gates({})

    assert report.ready is False
    assert all(gate.status is GateStatus.NOT_MEASURED for gate in report.gates)


def test_ga_gate_report_distinguishes_pass_and_failure() -> None:
    from benchmarks.ga_quality import (
        GATE_DEFINITIONS,
        GateStatus,
        MetricValue,
        evaluate_ga_gates,
    )

    metrics = {
        gate.metric: MetricValue(
            value=gate.threshold if gate.comparison == "max" else gate.threshold,
            sample_count=1,
        )
        for gate in GATE_DEFINITIONS
    }
    metrics["clean_ru_wer"] = MetricValue(0.13, 20)

    report = evaluate_ga_gates(metrics)
    statuses = {gate.metric: gate.status for gate in report.gates}

    assert report.ready is False
    assert statuses["clean_ru_wer"] is GateStatus.FAIL
    assert statuses["noisy_ru_wer"] is GateStatus.PASS


def test_cli_writes_not_measured_report_and_returns_nonzero(
    tmp_path: Path,
) -> None:
    from benchmarks.ga_quality import main

    source = tmp_path / "observations.json"
    target = tmp_path / "report.json"
    source.write_text(
        json.dumps({"schema_version": "1.0", "cases": []}),
        encoding="utf-8",
    )

    exit_code = main([str(source), "--output", str(target)])
    payload = json.loads(target.read_text(encoding="utf-8"))

    assert exit_code == 1
    assert payload["ready"] is False
    assert payload["gates"][0]["status"] == "not_measured"


def test_committed_observation_example_is_valid_and_fail_closed(
    tmp_path: Path,
) -> None:
    from benchmarks.ga_quality import main

    source = Path("benchmarks/observations.example.json")
    target = tmp_path / "report.json"

    assert main([str(source), "--output", str(target)]) == 1
    report = json.loads(target.read_text(encoding="utf-8"))
    assert report["ready"] is False
    assert {
        gate["status"] for gate in report["gates"]
    } == {"not_measured"}


def test_duplicate_cases_are_rejected_instead_of_inflating_evidence() -> None:
    from benchmarks.ga_quality import BenchmarkCase, score_cases

    case = BenchmarkCase(
        case_id="same",
        category="clean_ru",
        duration_ms=1_000,
        reference="текст",
        hypothesis="текст",
    )

    with pytest.raises(ValueError, match="unique"):
        score_cases([case, case])
