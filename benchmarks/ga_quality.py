from __future__ import annotations

import argparse
import json
import math
import sys
import unicodedata
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Optional, Sequence


ScoringUnit = Literal["word", "character"]
ScoringProfile = Literal["speech", "verbatim"]


@dataclass(frozen=True)
class TextScore:
    errors: int
    reference_units: int
    rate: float


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    category: str
    duration_ms: int
    reference: str
    hypothesis: str
    route: str = "cloud"
    press_to_insert_ms: Optional[int] = None
    processing_ms: Optional[int] = None

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("case_id must not be empty")
        if self.duration_ms <= 0:
            raise ValueError("duration_ms must be positive")
        if not self.reference.strip():
            raise ValueError("reference must not be empty")
        if self.category not in _CATEGORIES:
            raise ValueError(f"unsupported category: {self.category}")
        if self.route not in {"cloud", "local", "openrouter"}:
            raise ValueError(f"unsupported route: {self.route}")
        for name in ("press_to_insert_ms", "processing_ms"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must not be negative")


@dataclass(frozen=True)
class MetricValue:
    value: float
    sample_count: int

    def __post_init__(self) -> None:
        if not math.isfinite(self.value):
            raise ValueError("metric value must be finite")
        if self.sample_count < 0:
            raise ValueError("sample_count must not be negative")


@dataclass(frozen=True)
class GateDefinition:
    metric: str
    comparison: Literal["max", "min"]
    threshold: float
    unit: str


class GateStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    NOT_MEASURED = "not_measured"


@dataclass(frozen=True)
class GateResult:
    metric: str
    status: GateStatus
    comparison: str
    threshold: float
    unit: str
    value: Optional[float]
    sample_count: int


@dataclass(frozen=True)
class GateReport:
    ready: bool
    gates: tuple[GateResult, ...]


GATE_DEFINITIONS = (
    GateDefinition("corpus_duration_hours", "min", 5.0, "hours"),
    GateDefinition("clean_ru_wer", "max", 0.12, "ratio"),
    GateDefinition("noisy_ru_wer", "max", 0.22, "ratio"),
    GateDefinition("ru_en_wer", "max", 0.18, "ratio"),
    GateDefinition("code_path_cer", "max", 0.18, "ratio"),
    GateDefinition("diarization_der", "max", 0.18, "ratio"),
    GateDefinition("diarization_jer", "max", 0.28, "ratio"),
    GateDefinition("cloud_dictation_p50_seconds", "max", 1.8, "seconds"),
    GateDefinition("cloud_dictation_p95_seconds", "max", 4.0, "seconds"),
    GateDefinition("cloud_file_rtf", "max", 0.5, "ratio"),
    GateDefinition("insertion_success", "min", 0.98, "ratio"),
    GateDefinition("recovery_success", "min", 1.0, "ratio"),
    GateDefinition("double_charge_incidents", "max", 0.0, "count"),
    GateDefinition("terminal_state_resurrections", "max", 0.0, "count"),
    GateDefinition("horizontal_ui_overflow", "max", 0.0, "count"),
    GateDefinition("accessibility_walkthrough_pass", "min", 1.0, "boolean"),
)

_CATEGORIES = {
    "clean_ru": ("clean_ru_wer", "word", "speech"),
    "noisy_ru": ("noisy_ru_wer", "word", "speech"),
    "ru_en": ("ru_en_wer", "word", "speech"),
    "code_path": ("code_path_cer", "character", "verbatim"),
}


def _normalize(text: str, profile: ScoringProfile) -> str:
    normalized = unicodedata.normalize("NFC", text)
    if profile == "speech":
        normalized = normalized.casefold()
        normalized = "".join(
            " " if unicodedata.category(character).startswith("P") else character
            for character in normalized
        )
    return " ".join(normalized.split())


def _edit_distance(reference: Sequence[str], hypothesis: Sequence[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for ref_index, ref_item in enumerate(reference, start=1):
        current = [ref_index]
        for hyp_index, hyp_item in enumerate(hypothesis, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[hyp_index] + 1,
                    previous[hyp_index - 1] + (ref_item != hyp_item),
                )
            )
        previous = current
    return previous[-1]


def score_text(
    reference: str,
    hypothesis: str,
    *,
    unit: ScoringUnit,
    profile: ScoringProfile,
) -> TextScore:
    normalized_reference = _normalize(reference, profile)
    normalized_hypothesis = _normalize(hypothesis, profile)
    if unit == "word":
        reference_units = normalized_reference.split()
        hypothesis_units = normalized_hypothesis.split()
    elif unit == "character":
        reference_units = list(normalized_reference)
        hypothesis_units = list(normalized_hypothesis)
    else:
        raise ValueError(f"unsupported scoring unit: {unit}")
    errors = _edit_distance(reference_units, hypothesis_units)
    denominator = len(reference_units)
    rate = errors / denominator if denominator else (0.0 if not errors else 1.0)
    return TextScore(errors, denominator, rate)


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def score_cases(cases: Iterable[BenchmarkCase]) -> dict[str, MetricValue]:
    all_cases = tuple(cases)
    identifiers = [case.case_id for case in all_cases]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("case_id values must be unique")
    totals: dict[str, list[int]] = {}
    for case in all_cases:
        category = _CATEGORIES.get(case.category)
        if category is None:
            continue
        metric, unit, profile = category
        score = score_text(
            case.reference,
            case.hypothesis,
            unit=unit,
            profile=profile,
        )
        aggregate = totals.setdefault(metric, [0, 0, 0])
        aggregate[0] += score.errors
        aggregate[1] += score.reference_units
        aggregate[2] += 1

    metrics = {
        name: MetricValue(
            value=errors / units if units else 0.0,
            sample_count=count,
        )
        for name, (errors, units, count) in totals.items()
    }
    metrics["corpus_duration_hours"] = MetricValue(
        value=sum(case.duration_ms for case in all_cases) / 3_600_000,
        sample_count=len(all_cases),
    )

    cloud_latency = [
        case.press_to_insert_ms / 1000
        for case in all_cases
        if case.route == "cloud" and case.press_to_insert_ms is not None
    ]
    if cloud_latency:
        metrics["cloud_dictation_p50_seconds"] = MetricValue(
            _percentile(cloud_latency, 0.50),
            len(cloud_latency),
        )
        metrics["cloud_dictation_p95_seconds"] = MetricValue(
            _percentile(cloud_latency, 0.95),
            len(cloud_latency),
        )

    cloud_files = [
        case
        for case in all_cases
        if case.route == "cloud" and case.processing_ms is not None
    ]
    if cloud_files:
        total_processing = sum(case.processing_ms or 0 for case in cloud_files)
        total_audio = sum(case.duration_ms for case in cloud_files)
        metrics["cloud_file_rtf"] = MetricValue(
            total_processing / total_audio,
            len(cloud_files),
        )
    return metrics


def evaluate_ga_gates(
    metrics: Mapping[str, MetricValue],
) -> GateReport:
    results = []
    for gate in GATE_DEFINITIONS:
        observation = metrics.get(gate.metric)
        if observation is None or observation.sample_count == 0:
            status = GateStatus.NOT_MEASURED
            value = None if observation is None else observation.value
            sample_count = 0 if observation is None else observation.sample_count
        else:
            passed = (
                observation.value <= gate.threshold
                if gate.comparison == "max"
                else observation.value >= gate.threshold
            )
            status = GateStatus.PASS if passed else GateStatus.FAIL
            value = observation.value
            sample_count = observation.sample_count
        results.append(
            GateResult(
                metric=gate.metric,
                status=status,
                comparison=gate.comparison,
                threshold=gate.threshold,
                unit=gate.unit,
                value=value,
                sample_count=sample_count,
            )
        )
    frozen = tuple(results)
    return GateReport(
        ready=all(item.status is GateStatus.PASS for item in frozen),
        gates=frozen,
    )


def _case_from_json(item: Mapping[str, Any]) -> BenchmarkCase:
    return BenchmarkCase(
        case_id=str(item["case_id"]),
        category=str(item["category"]),
        duration_ms=int(item["duration_ms"]),
        reference=str(item["reference"]),
        hypothesis=str(item["hypothesis"]),
        route=str(item.get("route", "cloud")),
        press_to_insert_ms=(
            int(item["press_to_insert_ms"])
            if item.get("press_to_insert_ms") is not None
            else None
        ),
        processing_ms=(
            int(item["processing_ms"])
            if item.get("processing_ms") is not None
            else None
        ),
    )


def _metric_from_json(value: Any) -> MetricValue:
    if not isinstance(value, Mapping):
        raise ValueError("operational metrics require value and sample_count")
    return MetricValue(
        value=float(value["value"]),
        sample_count=int(value["sample_count"]),
    )


def _report_json(
    metrics: Mapping[str, MetricValue],
    report: GateReport,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "ready": report.ready,
        "metrics": {
            name: asdict(value)
            for name, value in sorted(metrics.items())
        },
        "gates": [
            {
                **asdict(gate),
                "status": gate.status.value,
            }
            for gate in report.gates
        ],
    }


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Score versioned MindType Windows GA observations."
    )
    parser.add_argument("observations", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.observations.read_text(encoding="utf-8"))
        if payload.get("schema_version") != "1.0":
            raise ValueError("unsupported observations schema_version")
        raw_cases = payload.get("cases", [])
        if not isinstance(raw_cases, list):
            raise ValueError("cases must be an array")
        if any(not isinstance(item, Mapping) for item in raw_cases):
            raise ValueError("every case must be an object")
        metrics = score_cases(
            _case_from_json(item)
            for item in raw_cases
        )
        raw_metrics = payload.get("metrics", {})
        if not isinstance(raw_metrics, Mapping):
            raise ValueError("metrics must be an object")
        metrics.update(
            {
                str(name): _metric_from_json(value)
                for name, value in raw_metrics.items()
            }
        )
        report = evaluate_ga_gates(metrics)
        output = _report_json(metrics, report)
        if args.output:
            _write_json_atomic(args.output, output)
        else:
            print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0 if report.ready else 1
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"Invalid benchmark input: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
