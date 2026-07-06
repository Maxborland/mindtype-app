"""
Генератор отчётов транскрипции в стиле Classic Mac OS.
Поддерживает HTML и PDF форматы.
"""

import html
import subprocess
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from .file_transcriber import TranscriptionResult, TranscriptionSegment


# HTML шаблон — чистый System 7 (Segoe, плоский чёрный заголовок, острые рамки).
# Вёрстка на ТАБЛИЦАХ (без flexbox/градиентов) — один шаблон корректно
# рендерится и в браузере, и через QTextDocument в PDF.
HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="{lang}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <!-- MathJax for LaTeX support (только браузер; в PDF игнорируется) -->
    <script>
        MathJax = {{
            tex: {{
                inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
                displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']]
            }},
            svg: {{ fontCache: 'global' }}
        }};
    </script>
    <script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js"></script>
    <style>
        body {{
            font-family: "Segoe UI", "Inter", Arial, sans-serif;
            font-size: 13px;
            line-height: 1.5;
            background-color: #ededed;
            color: #000000;
            padding: 24px;
        }}
        .window {{
            background-color: #ffffff;
            border: 2px solid #000000;
            max-width: 880px;
            margin: 0 auto;
        }}
        .titlebar {{
            background-color: #000000;
            color: #ffffff;
            font-weight: bold;
            font-size: 13px;
            padding: 6px 10px;
        }}
        .content {{ padding: 18px; }}

        h2.section {{
            font-size: 14px;
            font-weight: bold;
            margin: 22px 0 10px 0;
            padding-bottom: 4px;
            border-bottom: 2px solid #000000;
        }}
        .badge {{
            background-color: #000000;
            color: #ffffff;
            font-size: 10px;
            font-weight: bold;
            padding: 1px 6px;
            margin-left: 6px;
        }}

        table.info {{ border-collapse: collapse; margin-bottom: 4px; }}
        table.info td {{ padding: 3px 6px; vertical-align: top; }}
        table.info td.k {{ font-weight: bold; width: 150px; }}

        table.stats {{
            width: 100%;
            border: 1px solid #000000;
            border-collapse: collapse;
            margin: 12px 0 4px 0;
        }}
        table.stats td {{
            text-align: center;
            padding: 10px 6px;
            border-right: 1px solid #d0d0d0;
        }}
        .stat-value {{ font-size: 18px; font-weight: bold; }}
        .stat-label {{ font-size: 11px; color: #666666; }}

        .fulltext {{
            border: 1px solid #000000;
            padding: 14px;
            line-height: 1.7;
            text-align: justify;
        }}

        table.segs {{ width: 100%; border: 1px solid #000000; border-collapse: collapse; }}
        table.segs td.t {{
            width: 130px;
            font-weight: bold;
            background-color: #f2f2f2;
            border-right: 1px solid #d0d0d0;
            border-bottom: 1px solid #ececec;
            padding: 6px 10px;
            font-size: 12px;
            white-space: nowrap;
            vertical-align: top;
        }}
        table.segs td.x {{ padding: 6px 10px; border-bottom: 1px solid #ececec; }}

        .summary {{
            border: 2px solid #000000;
            background-color: #fcfcf5;
            padding: 14px;
        }}
        .summary h3 {{ font-size: 13px; font-weight: bold; margin: 10px 0 5px 0; }}
        .summary ul {{ margin: 4px 0 8px 20px; }}
        .summary li {{ margin-bottom: 4px; }}
        .summary table {{ width: 100%; border-collapse: collapse; margin: 6px 0; }}
        .summary th, .summary td {{ border: 1px solid #000000; padding: 5px 8px; text-align: left; }}
        .summary th {{ background-color: #e8e8e8; font-weight: bold; }}
        .summary strong {{ font-weight: bold; }}

        table.speakers {{ width: 100%; border: 1px solid #000000; border-collapse: collapse; }}
        table.speakers td {{ border-bottom: 1px solid #ececec; padding: 6px 10px; }}
        table.speakers td.name {{ font-weight: bold; }}

        .speaker-tag {{ font-weight: bold; padding: 1px 6px; font-size: 11px; margin-right: 8px; }}
        .speaker-tag-0 {{ background-color: #FF6B6B; color: #fff; }}
        .speaker-tag-1 {{ background-color: #4ECDC4; color: #fff; }}
        .speaker-tag-2 {{ background-color: #45B7D1; color: #fff; }}
        .speaker-tag-3 {{ background-color: #96CEB4; color: #fff; }}
        .speaker-tag-4 {{ background-color: #FFEAA7; color: #333; }}
        .speaker-tag-5 {{ background-color: #DDA0DD; color: #fff; }}
        .speaker-tag-6 {{ background-color: #98D8C8; color: #333; }}
        .speaker-tag-7 {{ background-color: #F7DC6F; color: #333; }}

        .footer {{
            text-align: center;
            padding: 14px;
            border-top: 1px solid #d0d0d0;
            font-size: 11px;
            color: #666666;
        }}

        @media print {{
            body {{ background-color: #ffffff; padding: 0; }}
            .window {{ border: none; max-width: none; }}
        }}
    </style>
</head>
<body>
    <div class="window">
        <div class="titlebar">{window_title}</div>

        <div class="content">
            <!-- Информация о файле -->
            <table class="info" cellspacing="0">
                <tr><td class="k">{label_file}:</td><td>{file_name}</td></tr>
                <tr><td class="k">{label_duration}:</td><td>{duration}</td></tr>
                <tr><td class="k">{label_language}:</td><td>{language} ({probability}%)</td></tr>
                <tr><td class="k">{label_model}:</td><td>{model}</td></tr>
                <tr><td class="k">{label_date}:</td><td>{date}</td></tr>
            </table>

            <!-- Статистика -->
            <table class="stats" cellspacing="0">
                <tr>
                    <td><div class="stat-value">{segment_count}</div><div class="stat-label">{label_segments}</div></td>
                    <td><div class="stat-value">{word_count}</div><div class="stat-label">{label_words}</div></td>
                    <td><div class="stat-value">{char_count}</div><div class="stat-label">{label_characters}</div></td>
                    <td><div class="stat-value">{speaker_count}</div><div class="stat-label">{label_speakers}</div></td>
                </tr>
            </table>

            {speakers_section}

            {summary_section}

            <!-- Полный текст -->
            <h2 class="section">{section_full_text}</h2>
            <div class="fulltext">{full_text}</div>

            <!-- Сегменты с таймкодами -->
            <h2 class="section">{section_segments}</h2>
            <table class="segs" cellspacing="0">
                {segments_html}
            </table>
        </div>

        <div class="footer"><b>MindType</b> &mdash; {footer_text}</div>
    </div>
</body>
</html>
'''

SEGMENT_TEMPLATE = '''<tr><td class="t">{time}</td><td class="x">{speaker_tag}{text}</td></tr>
'''

SPEAKERS_SECTION_TEMPLATE = '''
<h2 class="section">{title}</h2>
<table class="speakers" cellspacing="0">
    {speaker_cards}
</table>
'''

SPEAKER_CARD_TEMPLATE = '''<tr><td class="name">{speaker_name}</td><td>{duration}</td><td>{segments} {segments_label}</td><td>{words} {words_label}</td></tr>
'''


class ReportGenerator:
    """Генератор отчётов транскрипции."""

    def __init__(self, ui_language: str = "ru"):
        self.ui_language = ui_language
        self._labels = self._get_labels(ui_language)

    def _get_labels(self, lang: str) -> dict:
        """Получить метки для языка интерфейса."""
        labels = {
            "ru": {
                "window_title": "Транскрипция",
                "label_file": "Файл",
                "label_duration": "Длительность",
                "label_language": "Язык",
                "label_model": "Модель",
                "label_date": "Дата",
                "label_segments": "сегментов",
                "label_words": "слов",
                "label_characters": "символов",
                "label_speakers": "участников",
                "section_full_text": "Полный текст",
                "section_segments": "Сегменты с таймкодами",
                "section_summary": "Саммари",
                "section_speakers": "Участники встречи",
                "summary_badge": "AI",
                "footer_text": "Создано с помощью MindType — AI транскрипция",
            },
            "en": {
                "window_title": "Transcription",
                "label_file": "File",
                "label_duration": "Duration",
                "label_language": "Language",
                "label_model": "Model",
                "label_date": "Date",
                "label_segments": "segments",
                "label_words": "words",
                "label_characters": "characters",
                "label_speakers": "speakers",
                "section_full_text": "Full Text",
                "section_segments": "Segments with Timestamps",
                "section_summary": "Summary",
                "section_speakers": "Meeting Participants",
                "summary_badge": "AI",
                "footer_text": "Created with MindType — AI Transcription",
            },
            "de": {
                "window_title": "Transkription",
                "label_file": "Datei",
                "label_duration": "Dauer",
                "label_language": "Sprache",
                "label_model": "Modell",
                "label_date": "Datum",
                "label_segments": "Segmente",
                "label_words": "Wörter",
                "label_characters": "Zeichen",
                "label_speakers": "Teilnehmer",
                "section_full_text": "Volltext",
                "section_segments": "Segmente mit Zeitstempeln",
                "section_summary": "Zusammenfassung",
                "section_speakers": "Besprechungsteilnehmer",
                "summary_badge": "KI",
                "footer_text": "Erstellt mit MindType — KI-Transkription",
            },
            "fr": {
                "window_title": "Transcription",
                "label_file": "Fichier",
                "label_duration": "Durée",
                "label_language": "Langue",
                "label_model": "Modèle",
                "label_date": "Date",
                "label_segments": "segments",
                "label_words": "mots",
                "label_characters": "caractères",
                "label_speakers": "participants",
                "section_full_text": "Texte complet",
                "section_segments": "Segments avec horodatage",
                "section_summary": "Résumé",
                "section_speakers": "Participants à la réunion",
                "summary_badge": "IA",
                "footer_text": "Créé avec MindType — Transcription IA",
            },
            "es": {
                "window_title": "Transcripción",
                "label_file": "Archivo",
                "label_duration": "Duración",
                "label_language": "Idioma",
                "label_model": "Modelo",
                "label_date": "Fecha",
                "label_segments": "segmentos",
                "label_words": "palabras",
                "label_characters": "caracteres",
                "label_speakers": "participantes",
                "section_full_text": "Texto completo",
                "section_segments": "Segmentos con marcas de tiempo",
                "section_summary": "Resumen",
                "section_speakers": "Participantes de la reunión",
                "summary_badge": "IA",
                "footer_text": "Creado con MindType — Transcripción IA",
            },
            "zh": {
                "window_title": "转录",
                "label_file": "文件",
                "label_duration": "时长",
                "label_language": "语言",
                "label_model": "模型",
                "label_date": "日期",
                "label_segments": "段落",
                "label_words": "词数",
                "label_characters": "字符",
                "label_speakers": "参与者",
                "section_full_text": "完整文本",
                "section_segments": "带时间戳的段落",
                "section_summary": "摘要",
                "section_speakers": "会议参与者",
                "summary_badge": "AI",
                "footer_text": "由 MindType 创建 — AI 转录",
            },
            "ja": {
                "window_title": "文字起こし",
                "label_file": "ファイル",
                "label_duration": "長さ",
                "label_language": "言語",
                "label_model": "モデル",
                "label_date": "日付",
                "label_segments": "セグメント",
                "label_words": "単語",
                "label_characters": "文字",
                "label_speakers": "参加者",
                "section_full_text": "全文",
                "section_segments": "タイムスタンプ付きセグメント",
                "section_summary": "要約",
                "section_speakers": "会議参加者",
                "summary_badge": "AI",
                "footer_text": "MindType で作成 — AI 文字起こし",
            },
        }
        return labels.get(lang, labels["en"])

    def _get_language_name(self, code: Optional[str]) -> str:
        """Получить название языка по коду."""
        if not code:
            return "Unknown"

        names = {
            "ru": "Русский",
            "en": "English",
            "de": "Deutsch",
            "fr": "Français",
            "es": "Español",
            "it": "Italiano",
            "pt": "Português",
            "zh": "中文",
            "ja": "日本語",
            "ko": "한국어",
            "ar": "العربية",
            "hi": "हिन्दी",
            "uk": "Українська",
            "pl": "Polski",
            "nl": "Nederlands",
            "tr": "Türkçe",
            "vi": "Tiếng Việt",
            "th": "ไทย",
            "cs": "Čeština",
            "sv": "Svenska",
        }
        return names.get(code, code.upper())

    def _format_summary_as_html(self, summary: str) -> str:
        """
        Конвертировать Markdown-подобный саммари в HTML.

        Обрабатывает:
        - ## Заголовки → <h3>
        - - Списки → <ul><li>
        - **жирный** → <strong>
        - | таблицы |
        - $LaTeX$ формулы (сохраняются как есть для MathJax)
        """
        import re
        import uuid

        def _escape_preserving_latex(text: str) -> str:
            """Экранировать HTML, сохраняя LaTeX формулы."""
            # Сохраняем LaTeX формулы
            latex_placeholders = {}

            # Inline формулы $...$
            def save_latex(match):
                placeholder = f"__LATEX_{uuid.uuid4().hex[:8]}__"
                latex_placeholders[placeholder] = match.group(0)
                return placeholder

            # Сохраняем $...$ и $$...$$
            text = re.sub(r'\$\$[^$]+\$\$', save_latex, text)
            text = re.sub(r'\$[^$]+\$', save_latex, text)

            # Экранируем HTML
            text = html.escape(text)

            # Восстанавливаем LaTeX
            for placeholder, latex in latex_placeholders.items():
                text = text.replace(placeholder, latex)

            return text

        lines = summary.split('\n')
        html_parts = []
        in_list = False
        in_table = False
        table_header_done = False

        for line in lines:
            line = line.strip()
            if not line:
                if in_list:
                    html_parts.append('</ul>')
                    in_list = False
                if in_table:
                    html_parts.append('</table>')
                    in_table = False
                    table_header_done = False
                continue

            # Заголовок ##
            if line.startswith('## '):
                if in_list:
                    html_parts.append('</ul>')
                    in_list = False
                if in_table:
                    html_parts.append('</table>')
                    in_table = False
                    table_header_done = False
                header_text = _escape_preserving_latex(line[3:].strip())
                html_parts.append(f'<h3>{header_text}</h3>')
                continue

            # Таблица
            if line.startswith('|'):
                if in_list:
                    html_parts.append('</ul>')
                    in_list = False

                # Пропускаем разделитель |---|---|
                if re.match(r'^\|[\s\-|]+\|$', line):
                    continue

                cells = [c.strip() for c in line.split('|')[1:-1]]  # Убираем пустые по краям

                if not in_table:
                    html_parts.append('<table>')
                    in_table = True

                if not table_header_done:
                    html_parts.append('<tr>' + ''.join(f'<th>{_escape_preserving_latex(c)}</th>' for c in cells) + '</tr>')
                    table_header_done = True
                else:
                    html_parts.append('<tr>' + ''.join(f'<td>{_escape_preserving_latex(c)}</td>' for c in cells) + '</tr>')
                continue

            # Список - или *
            if line.startswith('- ') or line.startswith('* '):
                if in_table:
                    html_parts.append('</table>')
                    in_table = False
                    table_header_done = False

                if not in_list:
                    html_parts.append('<ul>')
                    in_list = True

                item_text = line[2:].strip()
                # Обработка **жирного** перед экранированием
                item_text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', item_text)
                # Экранируем, сохраняя LaTeX и strong теги
                item_text = _escape_preserving_latex(item_text)
                item_text = item_text.replace("&lt;strong&gt;", "<strong>").replace("&lt;/strong&gt;", "</strong>")
                html_parts.append(f'<li>{item_text}</li>')
                continue

            # Обычный текст
            if in_list:
                html_parts.append('</ul>')
                in_list = False
            if in_table:
                html_parts.append('</table>')
                in_table = False
                table_header_done = False

            text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line)
            text = _escape_preserving_latex(text)
            text = text.replace("&lt;strong&gt;", "<strong>").replace("&lt;/strong&gt;", "</strong>")
            html_parts.append(f'<p>{text}</p>')

        # Закрываем незакрытые теги
        if in_list:
            html_parts.append('</ul>')
        if in_table:
            html_parts.append('</table>')

        return '\n'.join(html_parts)

    def _get_speaker_index(self, speaker_id: str) -> int:
        """Получить индекс спикера из ID (SPEAKER_00 -> 0)."""
        import re
        match = re.search(r'SPEAKER_(\d+)', speaker_id)
        if match:
            return int(match.group(1)) % 8  # Макс 8 цветов
        return 0

    def _generate_speakers_section(self, result: TranscriptionResult) -> str:
        """Сгенерировать секцию участников встречи."""
        if not result.has_speakers or not result.speaker_stats:
            return ""

        speaker_cards = ""
        for stat in result.speaker_stats:
            index = self._get_speaker_index(stat.speaker_id)
            speaker_cards += SPEAKER_CARD_TEMPLATE.format(
                index=index,
                speaker_name=html.escape(stat.speaker_name),
                duration=stat.duration_formatted,
                segments=stat.segment_count,
                segments_label=self._labels.get("label_segments", "сегментов"),
                words=stat.word_count,
                words_label=self._labels.get("label_words", "слов"),
            )

        return SPEAKERS_SECTION_TEMPLATE.format(
            title=self._labels.get("section_speakers", "Участники встречи"),
            speaker_cards=speaker_cards,
        )

    def generate_html(self, result: TranscriptionResult, output_path: Optional[Path] = None) -> str:
        """
        Сгенерировать HTML отчёт.

        Args:
            result: Результат транскрипции
            output_path: Путь для сохранения (опционально)

        Returns:
            HTML строка
        """
        # Генерируем сегменты с поддержкой спикеров
        segments_html = ""
        for seg in result.segments:
            speaker_class = ""
            speaker_tag = ""

            if seg.speaker:
                index = self._get_speaker_index(seg.speaker)
                speaker_class = f"speaker-{index}"
                speaker_tag = f'<span class="speaker-tag speaker-tag-{index}">{html.escape(seg.speaker)}</span>'

            segments_html += SEGMENT_TEMPLATE.format(
                time=f"{seg.start_formatted} - {seg.end_formatted}",
                text=html.escape(seg.text),
                speaker_class=speaker_class,
                speaker_tag=speaker_tag,
            )

        # Подсчёт статистики
        full_text = result.full_text
        word_count = len(full_text.split())
        char_count = len(full_text)

        # Генерируем секцию участников (если есть)
        speakers_section = self._generate_speakers_section(result)

        # Генерируем секцию саммари (если есть)
        summary_section = ""
        if result.has_summary:
            summary_html = self._format_summary_as_html(result.summary)
            summary_section = f'''
            <!-- Саммари -->
            <div class="section-title">{self._labels["section_summary"]}<span class="summary-badge">{self._labels["summary_badge"]}</span></div>
            <div class="summary">
                {summary_html}
            </div>
            '''

        # Формируем HTML
        html_content = HTML_TEMPLATE.format(
            lang=result.detected_language or "en",
            title=f"{self._labels['window_title']} - {result.file_path.name}",
            window_title=f"{self._labels['window_title']}: {result.file_path.name}",

            # Метки
            label_file=self._labels["label_file"],
            label_duration=self._labels["label_duration"],
            label_language=self._labels["label_language"],
            label_model=self._labels["label_model"],
            label_date=self._labels["label_date"],
            label_segments=self._labels["label_segments"],
            label_words=self._labels["label_words"],
            label_characters=self._labels["label_characters"],
            label_speakers=self._labels.get("label_speakers", "участников"),
            section_full_text=self._labels["section_full_text"],
            section_segments=self._labels["section_segments"],
            footer_text=self._labels["footer_text"],

            # Значения
            file_name=html.escape(result.file_path.name),
            duration=result.duration_formatted,
            language=self._get_language_name(result.detected_language),
            probability=f"{result.language_probability * 100:.0f}",
            model=result.model_used,
            date=result.transcription_date.strftime("%Y-%m-%d %H:%M"),

            # Статистика
            segment_count=len(result.segments),
            word_count=word_count,
            char_count=char_count,
            speaker_count=result.num_speakers if result.num_speakers > 0 else "—",

            # Контент
            speakers_section=speakers_section,
            summary_section=summary_section,
            full_text=html.escape(full_text),
            segments_html=segments_html,
        )

        if output_path:
            output_path.write_text(html_content, encoding="utf-8")

        return html_content

    def generate_pdf(self, result: TranscriptionResult, output_path: Path) -> bool:
        """
        Сгенерировать PDF отчёт.

        Args:
            result: Результат транскрипции
            output_path: Путь для сохранения PDF

        Returns:
            True если успешно, False если PDF не поддерживается
        """
        # HTML держим в памяти (не пишем в output_path.with_suffix('.html') —
        # это совпало бы с реальным HTML в режиме 'both' и удалило бы его).
        html_content = self.generate_html(result)

        # Пробуем wkhtmltopdf (нужен файл на входе — пишем во временный)
        wkhtmltopdf = shutil.which("wkhtmltopdf")
        if wkhtmltopdf:
            tmp_html = output_path.with_suffix(".pdf.tmp.html")
            try:
                tmp_html.write_text(html_content, encoding="utf-8")
                subprocess.run(
                    [wkhtmltopdf, "--quiet", str(tmp_html), str(output_path)],
                    check=True,
                    timeout=120
                )
                if output_path.exists():
                    return True
            except (subprocess.SubprocessError, FileNotFoundError):
                pass
            finally:
                tmp_html.unlink(missing_ok=True)

        # Пробуем weasyprint
        try:
            from weasyprint import HTML
            HTML(string=html_content).write_pdf(str(output_path))
            return True
        except ImportError:
            pass
        except Exception:
            pass

        # Встроенный движок Qt (без внешних зависимостей) — основной путь.
        if self._render_pdf_qt(html_content, output_path):
            return True

        # PDF недоступен
        return False

    def _render_pdf_qt(self, html_content: str, output_path: Path) -> bool:
        """Отрендерить HTML в PDF встроенным QTextDocument (Qt rich text)."""
        try:
            from PyQt6.QtCore import QMarginsF
            from PyQt6.QtGui import QTextDocument, QPdfWriter, QPageSize, QPageLayout
            from PyQt6.QtWidgets import QApplication

            # QTextDocument требует экземпляр QApplication (метрики шрифтов).
            if QApplication.instance() is None:
                return False

            writer = QPdfWriter(str(output_path))
            writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
            writer.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Unit.Millimeter)

            doc = QTextDocument()
            doc.setHtml(html_content)
            doc.print(writer)
            return output_path.exists() and output_path.stat().st_size > 0
        except Exception:
            return False

    def generate(
        self,
        result: TranscriptionResult,
        output_dir: Path,
        format: str = "html",  # "html", "pdf", "both"
    ) -> dict:
        """
        Сгенерировать отчёт в указанном формате.

        Args:
            result: Результат транскрипции
            output_dir: Директория для сохранения
            format: Формат ("html", "pdf", "both")

        Returns:
            Словарь с путями к созданным файлам
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        # Базовое имя файла
        base_name = result.file_path.stem + "_transcription"

        created_files = {}

        if format in ("html", "both"):
            html_path = output_dir / f"{base_name}.html"
            self.generate_html(result, html_path)
            created_files["html"] = html_path

        if format in ("pdf", "both"):
            pdf_path = output_dir / f"{base_name}.pdf"
            if self.generate_pdf(result, pdf_path):
                created_files["pdf"] = pdf_path
            else:
                # Если PDF не создан, создаём хотя бы HTML
                if "html" not in created_files:
                    html_path = output_dir / f"{base_name}.html"
                    self.generate_html(result, html_path)
                    created_files["html"] = html_path

        return created_files


