from __future__ import annotations

import argparse
import itertools
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence


@dataclass(frozen=True)
class DiarizationInterval:
    speaker: str
    start: float
    end: float

    def __post_init__(self) -> None:
        if not self.speaker.strip():
            raise ValueError("speaker must not be empty")
        if not math.isfinite(self.start) or not math.isfinite(self.end):
            raise ValueError("timestamps must be finite")
        if self.start < 0 or self.end <= self.start:
            raise ValueError("interval must satisfy 0 <= start < end")


@dataclass(frozen=True)
class DiarizationScore:
    der: float
    jer: float
    missed_speech: float
    false_alarm: float
    confusion: float
    reference_speaker_time: float


def _active(
    intervals: Sequence[DiarizationInterval], start: float, end: float
) -> set[str]:
    midpoint = (start + end) / 2.0
    return {
        interval.speaker
        for interval in intervals
        if interval.start <= midpoint < interval.end
    }


def _speaker_durations(
    intervals: Sequence[DiarizationInterval],
) -> dict[str, float]:
    durations: dict[str, float] = {}
    for interval in intervals:
        durations[interval.speaker] = (
            durations.get(interval.speaker, 0.0)
            + interval.end
            - interval.start
        )
    return durations


def _overlap_matrix(
    reference: Sequence[DiarizationInterval],
    hypothesis: Sequence[DiarizationInterval],
) -> dict[tuple[str, str], float]:
    overlap: dict[tuple[str, str], float] = {}
    for ref in reference:
        for hyp in hypothesis:
            duration = min(ref.end, hyp.end) - max(ref.start, hyp.start)
            if duration > 0:
                key = (ref.speaker, hyp.speaker)
                overlap[key] = overlap.get(key, 0.0) + duration
    return overlap


def _best_mapping(
    reference_speakers: Sequence[str],
    hypothesis_speakers: Sequence[str],
    weights: Mapping[tuple[str, str], float],
) -> dict[str, str]:
    refs = tuple(sorted(reference_speakers))
    hyps = tuple(sorted(hypothesis_speakers))
    if not refs or not hyps:
        return {}

    best_score = float("-inf")
    best_pairs: tuple[tuple[str, str], ...] = ()
    pair_count = min(len(refs), len(hyps))
    for selected_hyps in itertools.combinations(hyps, pair_count):
        for selected_refs in itertools.permutations(refs, pair_count):
            pairs = tuple(zip(selected_hyps, selected_refs))
            score = sum(weights.get((ref, hyp), 0.0) for hyp, ref in pairs)
            if score > best_score or (
                score == best_score and pairs < best_pairs
            ):
                best_score = score
                best_pairs = pairs
    return dict(best_pairs)


def score_diarization(
    reference: Iterable[DiarizationInterval],
    hypothesis: Iterable[DiarizationInterval],
) -> DiarizationScore:
    ref = tuple(reference)
    hyp = tuple(hypothesis)
    boundaries = sorted(
        {
            point
            for interval in (*ref, *hyp)
            for point in (interval.start, interval.end)
        }
    )
    ref_speakers = sorted({interval.speaker for interval in ref})
    hyp_speakers = sorted({interval.speaker for interval in hyp})
    overlap = _overlap_matrix(ref, hyp)
    mapping = _best_mapping(ref_speakers, hyp_speakers, overlap)

    missed = 0.0
    false_alarm = 0.0
    confusion = 0.0
    reference_time = 0.0
    for start, end in zip(boundaries, boundaries[1:]):
        duration = end - start
        if duration <= 0:
            continue
        active_ref = _active(ref, start, end)
        active_hyp = _active(hyp, start, end)
        reference_time += len(active_ref) * duration
        missed += max(0, len(active_ref) - len(active_hyp)) * duration
        false_alarm += max(0, len(active_hyp) - len(active_ref)) * duration
        correct = sum(
            1
            for hyp_speaker in active_hyp
            if mapping.get(hyp_speaker) in active_ref
        )
        confusion += (
            min(len(active_ref), len(active_hyp)) - correct
        ) * duration

    if reference_time:
        der = (missed + false_alarm + confusion) / reference_time
    else:
        der = 0.0 if not hyp else 1.0

    ref_durations = _speaker_durations(ref)
    hyp_durations = _speaker_durations(hyp)
    jaccard_weights: dict[tuple[str, str], float] = {}
    for ref_speaker in ref_speakers:
        for hyp_speaker in hyp_speakers:
            intersection = overlap.get((ref_speaker, hyp_speaker), 0.0)
            union = (
                ref_durations[ref_speaker]
                + hyp_durations[hyp_speaker]
                - intersection
            )
            jaccard_weights[(ref_speaker, hyp_speaker)] = (
                intersection / union if union else 0.0
            )
    jer_mapping = _best_mapping(
        ref_speakers, hyp_speakers, jaccard_weights
    )
    mapped_by_ref = {ref_id: hyp_id for hyp_id, ref_id in jer_mapping.items()}
    speaker_errors = []
    for ref_speaker in ref_speakers:
        hyp_speaker = mapped_by_ref.get(ref_speaker)
        similarity = (
            jaccard_weights.get((ref_speaker, hyp_speaker), 0.0)
            if hyp_speaker is not None
            else 0.0
        )
        speaker_errors.append(1.0 - similarity)
    jer = sum(speaker_errors) / len(speaker_errors) if speaker_errors else 0.0

    return DiarizationScore(
        der=der,
        jer=jer,
        missed_speech=missed,
        false_alarm=false_alarm,
        confusion=confusion,
        reference_speaker_time=reference_time,
    )


def _read_intervals(path: Path) -> list[DiarizationInterval]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON array")
    return [
        DiarizationInterval(
            speaker=str(item["speaker"]),
            start=float(item["start"]),
            end=float(item["end"]),
        )
        for item in data
        if isinstance(item, dict)
    ]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Score diarization JSON intervals without model weights."
    )
    parser.add_argument("reference", type=Path)
    parser.add_argument("hypothesis", type=Path)
    args = parser.parse_args(argv)
    score = score_diarization(
        _read_intervals(args.reference),
        _read_intervals(args.hypothesis),
    )
    print(json.dumps(asdict(score), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
