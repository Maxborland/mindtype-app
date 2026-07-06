"""Тесты генератора отчётов: саммари-карточки, участники, транскрипт по репликам."""

from pathlib import Path

import pytest

from app.report_generator import ReportGenerator
from app.transcription_models import (
    SpeakerStats,
    TranscriptionResult,
    TranscriptionSegment,
)


def make_result(**overrides) -> TranscriptionResult:
    segments = overrides.pop("segments", [
        TranscriptionSegment(0, 5, "Привет, начнём.", speaker="SPEAKER_00"),
        TranscriptionSegment(5, 9, "Обсудим бюджет.", speaker="SPEAKER_00"),
        TranscriptionSegment(9, 15, "Цифры готовы.", speaker="SPEAKER_01"),
        TranscriptionSegment(15, 30, "Отлично.", speaker="SPEAKER_00"),
    ])
    defaults = dict(
        file_path=Path("call.mp3"),
        segments=segments,
        detected_language="ru",
        language_probability=0.99,
        duration=30.0,
        model_used="large-v3",
    )
    defaults.update(overrides)
    return TranscriptionResult(**defaults)


class TestSummaryMarkdown:
    """Markdown-рендер саммари."""

    def setup_method(self):
        self.gen = ReportGenerator("ru")

    def test_headers(self):
        html = self.gen._format_summary_as_html("## Секция\n### Подсекция")
        assert "<h3>Секция</h3>" in html
        assert "<h4>Подсекция</h4>" in html

    def test_bold(self):
        html = self.gen._format_summary_as_html("Бюджет **500 тысяч**")
        assert "<strong>500 тысяч</strong>" in html

    def test_unordered_list(self):
        html = self.gen._format_summary_as_html("- один\n- два")
        assert html.count("<li>") == 2
        assert "<ul>" in html and "</ul>" in html

    def test_ordered_list(self):
        html = self.gen._format_summary_as_html("1. первый\n2. второй\n3) третий")
        assert "<ol>" in html
        assert html.count("<li>") == 3

    def test_single_pipe_table(self):
        html = self.gen._format_summary_as_html(
            "| A | B |\n|---|---|\n| 1 | 2 |"
        )
        assert "<th>A</th>" in html
        assert "<td>2</td>" in html

    def test_double_pipe_table_from_presets(self):
        """Встроенные пресеты генерируют таблицы с '||' в начале строки."""
        html = self.gen._format_summary_as_html(
            "|| Action | Responsible | Deadline |\n"
            "||--------|-------------|----------|\n"
            "|| Подготовить смету | Иван | 15 марта |"
        )
        assert "<th>Action</th>" in html
        assert "<td>Иван</td>" in html
        # Разделитель не должен превратиться в строку таблицы
        assert "---" not in html

    def test_escapes_html(self):
        html = self.gen._format_summary_as_html("текст <script>alert(1)</script>")
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


class TestSummarySection:
    """Секция саммари: карточки по '## ' секциям пресета."""

    def setup_method(self):
        self.gen = ReportGenerator("ru")

    def test_sections_become_cards(self):
        result = make_result(summary="Интро.\n\n## 1) Решения\n- пункт\n\n## 2) Риски\n—")
        html = self.gen._generate_summary_section(result)
        assert html.count('class="sumcard"') == 2
        assert 'sumcard-h">1) Решения' in html
        assert "Интро." in html

    def test_preset_name_badge(self):
        result = make_result(summary="## X\n- y", summary_preset_name="Созвон")
        html = self.gen._generate_summary_section(result)
        assert ">Созвон</span>" in html

    def test_fallback_without_sections(self):
        result = make_result(summary="Просто текст без секций.")
        html = self.gen._generate_summary_section(result)
        assert 'class="summary"' in html
        assert "sumcard" not in html

    def test_empty_when_no_summary(self):
        result = make_result()
        assert self.gen._generate_summary_section(result) == ""


class TestTranscriptTurns:
    """Транскрипт: группировка подряд идущих сегментов одного спикера."""

    def setup_method(self):
        self.gen = ReportGenerator("ru")

    def test_turn_grouping(self):
        result = make_result()
        html = self.gen._generate_segments_html(result)
        # 3 реплики (00, 01, 00) — по одному заголовку на каждую
        assert html.count("turnhead") == 6  # 2 ячейки на заголовок
        # Диапазон времени первой реплики: 00:00–00:09
        assert "00:00&ndash;00:09" in html

    def test_speaker_names_used(self):
        result = make_result(
            speaker_names={"SPEAKER_00": "Спикер 1", "SPEAKER_01": "Спикер 2"},
        )
        html = self.gen._generate_segments_html(result)
        assert "Спикер 1" in html
        assert "Спикер 2" in html
        assert "SPEAKER_00" not in html

    def test_flat_without_speakers(self):
        result = make_result(segments=[
            TranscriptionSegment(0, 5, "Один."),
            TranscriptionSegment(5, 9, "Два."),
        ])
        html = self.gen._generate_segments_html(result)
        assert "turnhead" not in html
        assert html.count("<tr>") == 2


class TestSpeakersSection:
    """Секция участников: имена, доля времени."""

    def setup_method(self):
        self.gen = ReportGenerator("ru")

    def make_with_stats(self):
        return make_result(
            num_speakers=2,
            speaker_stats=[
                SpeakerStats("SPEAKER_00", "Спикер 1", 24.0, 3, 8),
                SpeakerStats("SPEAKER_01", "Спикер 2", 6.0, 1, 2),
            ],
            speaker_names={"SPEAKER_00": "Спикер 1", "SPEAKER_01": "Спикер 2"},
        )

    def test_percentage(self):
        html = self.gen._generate_speakers_section(self.make_with_stats())
        assert ">80%</td>" in html
        assert ">20%</td>" in html

    def test_names(self):
        html = self.gen._generate_speakers_section(self.make_with_stats())
        assert "Спикер 1" in html
        assert "SPEAKER_00" not in html

    def test_empty_for_single_speaker(self):
        result = make_result(num_speakers=1)
        assert self.gen._generate_speakers_section(result) == ""


class TestFullReport:
    """Интеграция: полный HTML-отчёт."""

    def test_generate_html(self, tmp_path):
        gen = ReportGenerator("ru")
        result = make_result(
            summary="## 1) Решения\n- Бюджет **500**",
            summary_preset_name="Созвон",
            num_speakers=2,
            speaker_stats=[
                SpeakerStats("SPEAKER_00", "Спикер 1", 24.0, 3, 8),
                SpeakerStats("SPEAKER_01", "Спикер 2", 6.0, 1, 2),
            ],
            speaker_names={"SPEAKER_00": "Спикер 1", "SPEAKER_01": "Спикер 2"},
            processed_text="Спикер 1: Привет, начнём.",
        )
        out = tmp_path / "report.html"
        html = gen.generate_html(result, out)

        assert out.exists()
        # Навигация со всеми якорями
        for anchor in ("#summary", "#speakers", "#transcript", "#fulltext"):
            assert anchor in html
        # Саммари перед транскриптом
        assert html.index('id="summary"') < html.index('id="transcript"')
        # Полный текст — обработанный (с разметкой спикеров)
        assert "Спикер 1: Привет, начнём." in html

    def test_generate_html_minimal(self, tmp_path):
        """Без саммари и спикеров отчёт тоже генерируется."""
        gen = ReportGenerator("en")
        result = make_result(segments=[TranscriptionSegment(0, 5, "Hello.")])
        html = gen.generate_html(result)
        assert "#transcript" in html
        assert "#summary" not in html
