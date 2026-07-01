"""
Тесты для OpenRouter STT-бэкенда транскрипции.

Покрывают:
- чанкинг по времени и RMS-гейт тишины (OpenRouterTranscriber._iter_chunks)
- склейку чанков в transcribe()
- форму запроса/ответа STT-эндпоинта (OpenRouterProvider.transcribe_audio)
- парсинг списка STT-моделей (fetch_transcription_models)
"""

from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pytest

from app.transcriber_openrouter import OpenRouterTranscriber
from app.llm.openrouter import OpenRouterProvider, TRANSCRIPTIONS_ENDPOINT


def _make_transcriber(chunk_sec=1):
    t = OpenRouterTranscriber()
    t._provider = Mock()
    t._model = "openai/whisper-1"
    t._chunk_sec = chunk_sec
    t._language = "auto"
    return t


class TestChunking:
    def test_chunk_boundaries(self):
        """3 секунды аудио при chunk_sec=1 → ровно 3 чанка с корректными таймкодами."""
        t = _make_transcriber(chunk_sec=1)
        t._provider.transcribe_audio.side_effect = ["alpha", "beta", "gamma"]
        audio = np.full(16000 * 3, 0.1, dtype=np.float32)  # RMS=0.1 > порога

        with patch("librosa.load", return_value=(audio, 16000)):
            chunks = list(t._iter_chunks(Path("x.wav")))

        assert [c[0] for c in chunks] == [0, 1, 2]
        assert [round(c[1], 3) for c in chunks] == [0.0, 1.0, 2.0]
        assert [c[3] for c in chunks] == ["alpha", "beta", "gamma"]
        assert t._provider.transcribe_audio.call_count == 3

    def test_silence_gate_skips_request(self):
        """Тишина не отправляется на API (пустой текст, нет вызовов)."""
        t = _make_transcriber(chunk_sec=1)
        audio = np.zeros(16000 * 2, dtype=np.float32)  # RMS=0

        with patch("librosa.load", return_value=(audio, 16000)):
            chunks = list(t._iter_chunks(Path("x.wav")))

        assert [c[3] for c in chunks] == ["", ""]
        t._provider.transcribe_audio.assert_not_called()

    def test_empty_audio(self):
        """Пустое аудио → нет чанков."""
        t = _make_transcriber()
        with patch("librosa.load", return_value=(np.array([], dtype=np.float32), 16000)):
            assert list(t._iter_chunks(Path("x.wav"))) == []

    def test_failed_chunk_skipped_in_multichunk(self):
        """В многочанковом файле упавший чанк пропускается, остальные продолжают."""
        t = _make_transcriber(chunk_sec=1)
        t._provider.transcribe_audio.side_effect = ["alpha", RuntimeError("520"), "gamma"]
        audio = np.full(16000 * 3, 0.1, dtype=np.float32)
        with patch("librosa.load", return_value=(audio, 16000)):
            chunks = list(t._iter_chunks(Path("x.wav")))
        assert [c[3] for c in chunks] == ["alpha", "", "gamma"]

    def test_all_chunks_fail_raises(self):
        """Если все отправленные чанки упали (даже в многочанковом файле) — ошибка, не пустой 'успех'."""
        t = _make_transcriber(chunk_sec=1)
        t._provider.transcribe_audio.side_effect = RuntimeError("520")
        audio = np.full(16000 * 3, 0.1, dtype=np.float32)  # 3 чанка, все упадут
        with patch("librosa.load", return_value=(audio, 16000)):
            with pytest.raises(Exception):
                list(t._iter_chunks(Path("x.wav")))

    def test_single_failed_chunk_raises(self):
        """Одиночный чанк (диктовка): ошибка пробрасывается, а не глотается."""
        t = _make_transcriber(chunk_sec=30)
        t._provider.transcribe_audio.side_effect = RuntimeError("520")
        audio = np.full(16000 * 2, 0.1, dtype=np.float32)  # 2с < 30с → 1 чанк
        with patch("librosa.load", return_value=(audio, 16000)):
            with pytest.raises(RuntimeError):
                list(t._iter_chunks(Path("x.wav")))

    def test_transcribe_joins_chunks(self):
        t = _make_transcriber(chunk_sec=1)
        t._provider.transcribe_audio.side_effect = ["alpha", "beta", "gamma"]
        audio = np.full(16000 * 3, 0.1, dtype=np.float32)

        with patch("librosa.load", return_value=(audio, 16000)):
            text, lang, prob = t.transcribe(Path("x.wav"), language="auto")

        for w in ("alpha", "beta", "gamma"):
            assert w in text
        assert lang is None  # auto → None
        assert prob == 1.0

    def test_transcribe_with_timestamps(self):
        t = _make_transcriber(chunk_sec=1)
        t._provider.transcribe_audio.side_effect = ["one", "two"]
        audio = np.full(16000 * 2, 0.1, dtype=np.float32)

        with patch("librosa.load", return_value=(audio, 16000)):
            segments, lang, _ = t.transcribe_with_timestamps(Path("x.wav"), language="ru")

        assert segments == [
            {"start": 0.0, "end": 1.0, "text": "one"},
            {"start": 1.0, "end": 2.0, "text": "two"},
        ]
        assert lang == "ru"


class TestTranscribeAudio:
    def test_payload_and_response(self):
        p = OpenRouterProvider(api_key="k")
        with patch.object(p, "_make_request", return_value={"text": "  привет  "}) as m:
            out = p.transcribe_audio("BASE64", "wav", "openai/whisper-1", language="ru")

        assert out == "привет"
        url, kwargs = m.call_args[0][0], m.call_args[1]
        assert url == TRANSCRIPTIONS_ENDPOINT
        assert kwargs["method"] == "POST"
        data = kwargs["data"]
        assert data["model"] == "openai/whisper-1"
        assert data["input_audio"] == {"data": "BASE64", "format": "wav"}
        assert data["language"] == "ru"
        assert kwargs.get("retries") == 3  # transient 520/502 повторяются

    def test_auto_language_omitted(self):
        p = OpenRouterProvider(api_key="k")
        with patch.object(p, "_make_request", return_value={"text": "x"}) as m:
            p.transcribe_audio("B", "wav", "m", language="auto")
        assert "language" not in m.call_args[1]["data"]


class TestFetchTranscriptionModels:
    def test_parses_and_skips_empty_ids(self):
        p = OpenRouterProvider(api_key="k")
        resp = {"data": [
            {"id": "openai/whisper-1", "name": "Whisper v1"},
            {"id": "", "name": "broken"},
            {"id": "openai/whisper-large-v3", "name": "Whisper large v3"},
        ]}
        with patch.object(p, "_make_request", return_value=resp):
            models = p.fetch_transcription_models()

        ids = [m.id for m in models]
        assert "openai/whisper-1" in ids
        assert "openai/whisper-large-v3" in ids
        assert "" not in ids
        assert len(models) == 2
