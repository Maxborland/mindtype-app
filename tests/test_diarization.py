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

    def test_silence_only_gives_single_speaker(self, tmp_path):
        sr = 16000
        wav = np.zeros(sr * 6, dtype=np.float32)
        path = self._write_wav(tmp_path, wav, sr)

        result = SpeakerDiarizer().diarize(path)
        assert result.num_speakers <= 1

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
