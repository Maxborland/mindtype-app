"""Тесты диаризации: VAD, сглаживание меток, присвоение спикеров, имена."""

import numpy as np
import pytest

from app.text_processor.diarization import (
    DiarizationResult,
    SpeakerDiarizer,
    SpeakerSegment,
    assign_speaker_by_overlap,
    default_speaker_names,
)


class TestDefaultSpeakerNames:
    def test_russian(self):
        names = default_speaker_names(["SPEAKER_00", "SPEAKER_01"], "ru")
        assert names == {"SPEAKER_00": "Спикер 1", "SPEAKER_01": "Спикер 2"}

    def test_english_fallback(self):
        names = default_speaker_names(["SPEAKER_00"], "en")
        assert names == {"SPEAKER_00": "Speaker 1"}

    def test_unknown_language_fallback(self):
        names = default_speaker_names(["SPEAKER_00"], "xx")
        assert names["SPEAKER_00"].startswith("Speaker")

    def test_numbering_follows_sorted_ids(self):
        names = default_speaker_names(["SPEAKER_02", "SPEAKER_00"], "ru")
        assert names["SPEAKER_00"] == "Спикер 1"
        assert names["SPEAKER_02"] == "Спикер 2"


class TestAssignSpeakerByOverlap:
    def test_sums_overlap_across_segments(self):
        """Несколько коротких сегментов одного спикера должны суммироваться."""
        diar = [
            SpeakerSegment("SPEAKER_00", 0.0, 3.0),   # перекрытие 3.0
            SpeakerSegment("SPEAKER_01", 3.0, 7.0),   # перекрытие 4.0 (макс. одиночное)
            SpeakerSegment("SPEAKER_00", 7.0, 10.0),  # перекрытие 3.0
        ]
        # SPEAKER_00 суммарно 6.0 > 4.0 у SPEAKER_01
        assert assign_speaker_by_overlap(0.0, 10.0, diar) == "SPEAKER_00"

    def test_no_overlap_picks_closest(self):
        diar = [
            SpeakerSegment("SPEAKER_00", 0.0, 1.0),
            SpeakerSegment("SPEAKER_01", 100.0, 101.0),
        ]
        assert assign_speaker_by_overlap(2.0, 3.0, diar) == "SPEAKER_00"

    def test_empty_segments(self):
        assert assign_speaker_by_overlap(0.0, 1.0, []) is None


class TestSmoothLabels:
    def test_removes_single_outlier(self):
        labels = np.array([0, 0, 1, 0, 0])
        smoothed = SpeakerDiarizer._smooth_labels(labels)
        assert smoothed.tolist() == [0, 0, 0, 0, 0]

    def test_keeps_real_speaker_change(self):
        labels = np.array([0, 0, 0, 1, 1, 1])
        smoothed = SpeakerDiarizer._smooth_labels(labels)
        assert smoothed.tolist() == [0, 0, 0, 1, 1, 1]

    def test_short_sequence_unchanged(self):
        labels = np.array([0, 1])
        smoothed = SpeakerDiarizer._smooth_labels(labels)
        assert smoothed.tolist() == [0, 1]

    def test_single_speaker_unchanged(self):
        labels = np.array([0, 0, 0, 0])
        smoothed = SpeakerDiarizer._smooth_labels(labels)
        assert smoothed.tolist() == [0, 0, 0, 0]


class TestAlignWithTranscription:
    def test_align_uses_summed_overlap(self):
        diarizer = SpeakerDiarizer()
        diar_result = DiarizationResult(
            segments=[
                SpeakerSegment("SPEAKER_00", 0.0, 3.0),
                SpeakerSegment("SPEAKER_01", 3.0, 7.0),
                SpeakerSegment("SPEAKER_00", 7.0, 10.0),
            ],
            num_speakers=2,
        )
        trans = [{"start": 0.0, "end": 10.0, "text": "длинная фраза"}]
        aligned = diarizer.align_with_transcription(diar_result, trans)
        assert aligned.segments[0].speaker == "SPEAKER_00"
        assert aligned.segments[0].text == "длинная фраза"

    def test_align_preserves_speaker_names(self):
        diarizer = SpeakerDiarizer()
        diar_result = DiarizationResult(
            segments=[SpeakerSegment("SPEAKER_00", 0.0, 5.0)],
            num_speakers=1,
            speaker_names={"SPEAKER_00": "Спикер 1"},
        )
        trans = [{"start": 0.0, "end": 5.0, "text": "привет"}]
        aligned = diarizer.align_with_transcription(diar_result, trans)
        assert aligned.speaker_names == {"SPEAKER_00": "Спикер 1"}

    def test_align_normalizes_reversed_transcript_bounds(self):
        diarizer = SpeakerDiarizer()
        diar_result = DiarizationResult(
            segments=[SpeakerSegment("SPEAKER_00", 0.0, 5.0)],
            num_speakers=1,
        )

        aligned = diarizer.align_with_transcription(
            diar_result,
            [{"start": 4.0, "end": 2.0, "text": "не потерять"}],
        )

        assert [(s.start, s.end, s.text) for s in aligned.segments] == [
            (2.0, 4.0, "не потерять")
        ]


class TestDiarizationCorrectness:
    def test_speaker_segment_normalizes_bounds(self):
        segment = SpeakerSegment("SPEAKER_00", 3.0, -1.0)
        assert (segment.start, segment.end) == (0.0, 3.0)

    def test_speaker_segment_rejects_non_finite_bounds(self):
        with pytest.raises(ValueError):
            SpeakerSegment("SPEAKER_00", 0.0, float("nan"))

    def test_window_starts_cover_final_audio_sample(self):
        starts = SpeakerDiarizer._window_starts(
            total_samples=81_601,
            segment_samples=32_000,
            hop_samples=16_000,
        )
        assert starts[-1] + 32_000 == 81_601
        assert starts == sorted(set(starts))

    def test_speaker_ids_are_canonical_by_first_appearance(self):
        labels = np.array([7, 7, 3, 3, 7, 9])
        assert SpeakerDiarizer._canonicalize_labels(labels).tolist() == [
            0,
            0,
            1,
            1,
            0,
            2,
        ]

    def test_minimum_speaker_count_survives_smoothing(self):
        features = np.array(
            [
                [-10.0, -10.0],
                [-9.0, -9.0],
                [0.0, 0.0],
                [1.0, 1.0],
                [10.0, 10.0],
                [11.0, 11.0],
            ]
        )
        labels = SpeakerDiarizer._cluster_features(
            features, min_speakers=3, max_speakers=3
        )
        assert len(set(labels.tolist())) == 3

    def test_legacy_sklearn_affinity_fallback(self):
        calls = []

        class LegacyClustering:
            def __init__(self, **kwargs):
                calls.append(kwargs)
                if "metric" in kwargs:
                    raise TypeError("metric is unsupported")

            def fit_predict(self, features):
                return np.array([0, 0, 1, 1])

        labels = SpeakerDiarizer._fit_clusters(
            np.array([[0.0], [0.1], [2.0], [2.1]]),
            2,
            clustering_type=LegacyClustering,
        )
        assert labels.tolist() == [0, 0, 1, 1]
        assert "metric" in calls[0]
        assert calls[1]["affinity"] == "euclidean"

    def test_short_cleanup_preserves_configured_minimum(self):
        diarizer = SpeakerDiarizer()
        diarizer.config.diarization_min_speakers = 2
        result = DiarizationResult(
            segments=[
                SpeakerSegment("SPEAKER_00", 0.0, 9.8),
                SpeakerSegment("SPEAKER_01", 9.8, 10.0),
            ],
            num_speakers=2,
        )

        cleaned = diarizer.merge_short_speakers(result)

        assert cleaned.num_speakers == 2
        assert {segment.speaker for segment in cleaned.segments} == {
            "SPEAKER_00",
            "SPEAKER_01",
        }

    def test_sentence_formatting_preserves_remainder(self):
        diarizer = SpeakerDiarizer()
        result = DiarizationResult(
            segments=[
                SpeakerSegment("SPEAKER_00", 0.0, 1.0),
                SpeakerSegment("SPEAKER_01", 1.0, 2.0),
            ],
            num_speakers=2,
        )
        text = "Один. Два. Три. Четыре. Пять."

        formatted = diarizer.format_with_speakers(text, result)

        for sentence in ["Один.", "Два.", "Три.", "Четыре.", "Пять."]:
            assert formatted.count(sentence) == 1


@pytest.mark.skipif(
    not SpeakerDiarizer().is_available,
    reason="librosa/sklearn недоступны",
)
class TestDiarizeVAD:
    """Диаризация на синтетическом аудио: тишина не должна давать спикеров."""

    def _write_wav(self, tmp_path, wav, sr=16000):
        import soundfile as sf
        path = tmp_path / "test.wav"
        sf.write(str(path), wav, sr)
        return path

    def test_silence_only_does_not_fabricate_speaker(self, tmp_path):
        sr = 16000
        wav = np.zeros(sr * 6, dtype=np.float32)
        path = self._write_wav(tmp_path, wav, sr)

        result = SpeakerDiarizer().diarize(path)
        assert result.num_speakers == 0
        assert result.segments == []

    def test_speech_then_silence_excludes_silence(self, tmp_path):
        """Сегменты не должны покрывать длинную тишину в конце."""
        sr = 16000
        rng = np.random.default_rng(42)
        speech = (rng.standard_normal(sr * 4) * 0.3).astype(np.float32)
        silence = np.zeros(sr * 6, dtype=np.float32)
        wav = np.concatenate([speech, silence])
        path = self._write_wav(tmp_path, wav, sr)

        result = SpeakerDiarizer().diarize(path)
        if result.segments and result.segments[-1].end > 0:
            # Последний сегмент не должен уходить глубоко в тишину
            assert result.segments[-1].end <= 5.5

    def test_fixed_audio_has_repeatable_labels_and_valid_timestamps(self, tmp_path):
        sr = 16000
        timeline = np.arange(sr * 6, dtype=np.float32) / sr
        first = 0.3 * np.sin(2 * np.pi * 180 * timeline[: sr * 3])
        second = 0.3 * np.sin(2 * np.pi * 420 * timeline[: sr * 3])
        path = self._write_wav(
            tmp_path, np.concatenate([first, second]).astype(np.float32), sr
        )
        diarizer = SpeakerDiarizer()

        first_result = diarizer.diarize(path, min_speakers=2, max_speakers=2)
        second_result = diarizer.diarize(path, min_speakers=2, max_speakers=2)

        first_view = [
            (segment.speaker, segment.start, segment.end)
            for segment in first_result.segments
        ]
        second_view = [
            (segment.speaker, segment.start, segment.end)
            for segment in second_result.segments
        ]
        assert first_result.num_speakers == 2
        assert first_view == second_view
        assert all(start <= end for _speaker, start, end in first_view)
