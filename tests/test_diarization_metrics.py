from __future__ import annotations

import pytest

from benchmarks.diarization_metrics import DiarizationInterval, score_diarization


def test_perfect_score_is_label_permutation_invariant() -> None:
    reference = [
        DiarizationInterval("alice", 0.0, 2.0),
        DiarizationInterval("bob", 2.0, 4.0),
    ]
    hypothesis = [
        DiarizationInterval("SPEAKER_09", 0.0, 2.0),
        DiarizationInterval("SPEAKER_02", 2.0, 4.0),
    ]

    score = score_diarization(reference, hypothesis)

    assert score.der == 0.0
    assert score.jer == 0.0


def test_missing_half_of_reference_is_counted() -> None:
    score = score_diarization(
        [DiarizationInterval("alice", 0.0, 2.0)],
        [DiarizationInterval("speaker", 0.0, 1.0)],
    )

    assert score.missed_speech == pytest.approx(1.0)
    assert score.der == pytest.approx(0.5)
    assert score.jer == pytest.approx(0.5)


def test_false_alarm_is_separate_from_confusion() -> None:
    score = score_diarization(
        [DiarizationInterval("alice", 0.0, 1.0)],
        [DiarizationInterval("speaker", 0.0, 2.0)],
    )

    assert score.false_alarm == pytest.approx(1.0)
    assert score.confusion == 0.0
    assert score.der == pytest.approx(1.0)
