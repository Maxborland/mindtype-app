"""Тесты LLM-диаризации через OpenRouter: парсинг, батчинг, fallback в пайплайне."""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.text_processor.llm_diarization import (
    LLMDiarizer,
    MAX_SEGMENTS_PER_BATCH,
    _parse_llm_json,
)


def make_segments(n, text="реплика", dur=5.0):
    return [
        {"start": i * dur, "end": (i + 1) * dur, "text": f"{text} {i}"}
        for i in range(n)
    ]


class TestParseLLMJson:
    def test_plain_json(self):
        data = _parse_llm_json('{"labels": [1, 2]}')
        assert data["labels"] == [1, 2]

    def test_code_fence(self):
        data = _parse_llm_json('```json\n{"labels": [1]}\n```')
        assert data["labels"] == [1]

    def test_prose_around_json(self):
        data = _parse_llm_json('Вот результат: {"labels": [1, 1]} — готово.')
        assert data["labels"] == [1, 1]

    def test_invalid_raises(self):
        with pytest.raises(Exception):
            _parse_llm_json("не json вообще")


class TestLLMDiarizerAvailability:
    def test_available_with_key_and_model(self):
        assert LLMDiarizer("sk-key", "openai/gpt-4o-mini").is_available

    def test_unavailable_without_key(self):
        assert not LLMDiarizer("", "openai/gpt-4o-mini").is_available

    def test_unavailable_without_model(self):
        assert not LLMDiarizer("sk-key", "").is_available


class TestDiarizeSegments:
    def _diarizer_with_response(self, responses):
        """LLMDiarizer с мок-провайдером, отдающим заданные ответы по очереди."""
        d = LLMDiarizer("sk-key", "test/model")
        provider = MagicMock()
        provider.complete.side_effect = (
            responses if isinstance(responses, list) else [responses]
        )
        d._provider = provider
        return d, provider

    def test_basic_labeling(self):
        d, provider = self._diarizer_with_response(json.dumps({
            "num_speakers": 2,
            "labels": [1, 1, 2, 1],
            "names": {"2": "Иван"},
        }))
        result = d.diarize_segments(make_segments(4))

        assert result.num_speakers == 2
        assert [s.speaker for s in result.segments] == [
            "SPEAKER_00", "SPEAKER_00", "SPEAKER_01", "SPEAKER_00",
        ]
        # Текст и таймкоды сегментов транскрипции сохранены
        assert result.segments[2].text == "реплика 2"
        assert result.segments[2].start == 10.0
        # Имя от LLM
        assert result.speaker_names == {"SPEAKER_01": "Иван"}
        assert provider.complete.call_count == 1

    def test_monologue(self):
        d, _ = self._diarizer_with_response('{"num_speakers": 1, "labels": [1, 1]}')
        result = d.diarize_segments(make_segments(2))
        assert result.num_speakers == 1

    def test_wrong_label_count_raises(self):
        d, _ = self._diarizer_with_response('{"labels": [1]}')
        with pytest.raises(ValueError):
            d.diarize_segments(make_segments(3))

    def test_skips_empty_segments(self):
        d, _ = self._diarizer_with_response('{"labels": [1, 2]}')
        segments = [
            {"start": 0, "end": 5, "text": "привет"},
            {"start": 5, "end": 10, "text": "   "},
            {"start": 10, "end": 15, "text": "ответ"},
        ]
        result = d.diarize_segments(segments)
        assert len(result.segments) == 2
        assert result.segments[1].speaker == "SPEAKER_01"

    def test_batching_long_transcript(self):
        n = MAX_SEGMENTS_PER_BATCH + 10
        first = json.dumps({"labels": [1] * MAX_SEGMENTS_PER_BATCH, "names": {"1": "Анна"}})
        second = json.dumps({"labels": [2] * 10})
        d, provider = self._diarizer_with_response([first, second])

        result = d.diarize_segments(make_segments(n))

        assert provider.complete.call_count == 2
        assert len(result.segments) == n
        assert result.num_speakers == 2
        # Контекст известных спикеров передан во второй запрос
        second_prompt = provider.complete.call_args_list[1].kwargs["messages"][1]["content"]
        assert "Speaker 1 (Анна)" in second_prompt
        assert "KEEP the same numbering" in second_prompt

    def test_empty_transcript(self):
        d, provider = self._diarizer_with_response("{}")
        result = d.diarize_segments([])
        assert result.num_speakers == 0
        provider.complete.assert_not_called()


class TestPipelineBackendSelection:
    """Выбор бэкенда диаризации в пайплайне и fallback."""

    def _pipeline(self, **config_kwargs):
        from app.text_processor import TextProcessingPipeline, ProcessingConfig
        config = ProcessingConfig(
            enable_diarization=True,
            enable_punctuation=False,
            enable_fillers=False,
            enable_normalize=False,
            enable_correct=False,
            **config_kwargs,
        )
        return TextProcessingPipeline(config)

    def test_openrouter_backend_used(self):
        pipeline = self._pipeline(
            diarization_backend="openrouter",
            diarization_api_key="sk-key",
            diarization_model="test/model",
        )
        response = json.dumps({"labels": [1, 2], "names": {}})
        with patch(
            "app.llm.openrouter.OpenRouterProvider"
        ) as provider_cls:
            provider_cls.return_value.complete.return_value = response
            result = pipeline.process(
                text="привет. ответ.",
                transcription_segments=[
                    {"start": 0, "end": 5, "text": "привет."},
                    {"start": 5, "end": 10, "text": "ответ."},
                ],
            )

        assert result.processing_stats.get("diarization_backend") == "openrouter"
        assert result.diarization.num_speakers == 2
        # Дефолтные дружелюбные имена дополнены
        assert result.diarization.speaker_names["SPEAKER_00"] == "Спикер 1"
        # Текст размечен спикерами
        assert "Спикер 1" in result.processed_text

    def test_fallback_to_local_on_llm_error(self, tmp_path):
        pipeline = self._pipeline(
            diarization_backend="openrouter",
            diarization_api_key="sk-key",
            diarization_model="test/model",
        )
        with patch("app.llm.openrouter.OpenRouterProvider") as provider_cls:
            provider_cls.return_value.complete.side_effect = RuntimeError("API down")
            result = pipeline.process(
                text="привет. ответ.",
                audio_path=tmp_path / "нет_файла.wav",  # локальная тоже скипнется
                transcription_segments=[{"start": 0, "end": 5, "text": "привет."}],
            )

        # LLM упала, аудио нет → диаризация пропущена, но пайплайн не упал
        assert "diarization_llm_error" in result.processing_stats
        assert result.processing_stats.get("diarization_skipped") is True
        assert result.diarization is None

    def test_local_backend_skips_llm(self):
        pipeline = self._pipeline(diarization_backend="local")
        with patch(
            "app.text_processor.llm_diarization.LLMDiarizer"
        ) as llm_cls:
            result = pipeline.process(
                text="привет.",
                transcription_segments=[{"start": 0, "end": 5, "text": "привет."}],
            )
            llm_cls.assert_not_called()
        # Без аудио локальная диаризация пропускается
        assert result.processing_stats.get("diarization_skipped") is True


class TestPostProcessOptionsAutoBackend:
    """auto selects only a backend that is actually available."""

    def _make_queue(self, **pp_kwargs):
        from pathlib import Path
        from app.file_transcriber import FileTranscriptionQueue
        from app.transcription_models import TranscribeOptions, PostProcessOptions

        return FileTranscriptionQueue(
            transcriber=MagicMock(),
            transcribe=TranscribeOptions(
                model_size="tiny", compute_type="int8", device="cpu",
                language="ru", beam_size=5, vad_filter=True,
                models_dir=Path("/tmp"),
            ),
            postprocess=PostProcessOptions(enable=True, **pp_kwargs),
        )

    def test_auto_with_key(self):
        q = self._make_queue(diarization_backend="auto", diarization_api_key="sk-key")
        assert q.postprocessing_diarization_backend == "openrouter"

    @patch("app.file_transcriber.local_diarization_available", return_value=True)
    def test_auto_without_key(self, _available):
        q = self._make_queue(
            diarization_backend="auto",
            diarization_api_key="",
        )
        assert q.postprocessing_diarization_backend == "local"

    @patch("app.file_transcriber.local_diarization_available", return_value=False)
    def test_auto_without_key_or_optional_pack_is_disabled(self, _available):
        q = self._make_queue(
            diarization_backend="auto",
            diarization_api_key="",
        )
        assert q.postprocessing_diarization_backend == "disabled"

    @patch("app.file_transcriber.local_diarization_available", return_value=True)
    def test_explicit_local_with_key(self, _available):
        q = self._make_queue(
            diarization_backend="local",
            diarization_api_key="sk-key",
        )
        assert q.postprocessing_diarization_backend == "local"

    @patch("app.file_transcriber.local_diarization_available", return_value=False)
    def test_explicit_local_without_optional_pack_is_disabled(self, _available):
        q = self._make_queue(
            diarization_backend="local",
            diarization_api_key="sk-key",
        )
        assert q.postprocessing_diarization_backend == "disabled"


def test_disabled_diarization_records_explicit_optional_pack_reason(tmp_path):
    from app.text_processor import ProcessingConfig, TextProcessingPipeline

    config = ProcessingConfig(
        enable_diarization=True,
        diarization_backend="disabled",
        enable_punctuation=False,
        enable_fillers=False,
        enable_normalize=False,
        enable_correct=False,
    )
    pipeline = TextProcessingPipeline(config)
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"not-read")

    result = pipeline.process("исходный текст", audio_path=audio)

    assert result.diarization is None
    assert result.processing_stats["diarization_skipped"] is True
    assert (
        result.processing_stats["diarization_error"]
        == "LOCAL_DIARIZATION_PACK_REQUIRED"
    )
