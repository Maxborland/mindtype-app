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


# HTML шаблон в стиле Classic Mac OS System 7
HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="{lang}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        /* Classic Mac OS System 7 Style */
        @import url('https://fonts.googleapis.com/css2?family=VT323&display=swap');

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: "Chicago", "Geneva", "VT323", "Courier New", monospace;
            font-size: 14px;
            line-height: 1.5;
            background-color: #c0c0c0;
            color: #000000;
            padding: 20px;
        }}

        /* Главное окно */
        .window {{
            background-color: #ffffff;
            border: 2px solid #000000;
            max-width: 900px;
            margin: 0 auto;
            box-shadow: 4px 4px 0 #808080;
        }}

        /* Заголовок окна */
        .window-header {{
            background: linear-gradient(to right, #000000 0%, #808080 50%, #000000 100%);
            padding: 4px 8px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }}

        .window-title {{
            color: #ffffff;
            font-weight: bold;
            font-size: 13px;
            text-shadow: 1px 1px 0 #000000;
        }}

        .window-buttons {{
            display: flex;
            gap: 4px;
        }}

        .window-btn {{
            width: 12px;
            height: 12px;
            border: 1px solid #000000;
            background: #ffffff;
        }}

        /* Контент */
        .content {{
            padding: 16px;
        }}

        /* Информационная панель */
        .info-panel {{
            background-color: #ffffff;
            border: 2px solid;
            border-top-color: #808080;
            border-left-color: #808080;
            border-right-color: #ffffff;
            border-bottom-color: #ffffff;
            padding: 12px;
            margin-bottom: 16px;
        }}

        .info-row {{
            display: flex;
            margin-bottom: 6px;
        }}

        .info-label {{
            font-weight: bold;
            min-width: 140px;
            color: #000000;
        }}

        .info-value {{
            color: #000000;
        }}

        /* Заголовок секции */
        .section-title {{
            font-weight: bold;
            font-size: 14px;
            padding: 8px 0;
            margin-top: 16px;
            border-bottom: 2px solid #000000;
            margin-bottom: 12px;
        }}

        /* Полный текст */
        .full-text {{
            background-color: #ffffff;
            border: 2px solid;
            border-top-color: #808080;
            border-left-color: #808080;
            border-right-color: #ffffff;
            border-bottom-color: #ffffff;
            padding: 16px;
            margin-bottom: 16px;
            line-height: 1.8;
            text-align: justify;
        }}

        /* Сегменты транскрипции */
        .segments {{
            background-color: #ffffff;
            border: 2px solid;
            border-top-color: #808080;
            border-left-color: #808080;
            border-right-color: #ffffff;
            border-bottom-color: #ffffff;
        }}

        .segment {{
            display: flex;
            border-bottom: 1px solid #c0c0c0;
            transition: background-color 0.1s;
        }}

        .segment:last-child {{
            border-bottom: none;
        }}

        .segment:hover {{
            background-color: #e8e8e8;
        }}

        .segment-time {{
            min-width: 100px;
            padding: 8px 12px;
            font-weight: bold;
            background-color: #f0f0f0;
            border-right: 1px solid #c0c0c0;
            font-family: "Courier New", monospace;
            font-size: 12px;
        }}

        .segment-text {{
            padding: 8px 12px;
            flex: 1;
        }}

        /* Футер */
        .footer {{
            text-align: center;
            padding: 16px;
            border-top: 1px solid #c0c0c0;
            font-size: 11px;
            color: #808080;
        }}

        .footer a {{
            color: #000000;
            text-decoration: none;
        }}

        .footer a:hover {{
            text-decoration: underline;
        }}

        /* Логотип MindType */
        .logo {{
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            margin-bottom: 8px;
        }}

        .logo-icon {{
            width: 24px;
            height: 24px;
            border: 2px solid #000000;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 16px;
        }}

        .logo-text {{
            font-weight: bold;
            font-size: 16px;
        }}

        /* Статистика */
        .stats {{
            display: flex;
            justify-content: space-around;
            padding: 12px;
            background-color: #f0f0f0;
            border: 1px solid #000000;
            margin-bottom: 16px;
        }}

        .stat-item {{
            text-align: center;
        }}

        .stat-value {{
            font-size: 20px;
            font-weight: bold;
        }}

        .stat-label {{
            font-size: 11px;
            color: #808080;
        }}

        /* Саммари */
        .summary {{
            background-color: #fffff0;
            border: 2px solid #000000;
            padding: 16px;
            margin-bottom: 16px;
        }}

        .summary h2 {{
            font-size: 14px;
            font-weight: bold;
            margin-bottom: 12px;
            padding-bottom: 6px;
            border-bottom: 1px dashed #808080;
        }}

        .summary h3 {{
            font-size: 13px;
            font-weight: bold;
            margin-top: 12px;
            margin-bottom: 6px;
        }}

        .summary ul {{
            margin-left: 20px;
            margin-bottom: 8px;
        }}

        .summary li {{
            margin-bottom: 4px;
        }}

        .summary table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 8px;
        }}

        .summary th, .summary td {{
            border: 1px solid #000000;
            padding: 6px 8px;
            text-align: left;
        }}

        .summary th {{
            background-color: #e0e0e0;
            font-weight: bold;
        }}

        .summary strong {{
            font-weight: bold;
        }}

        .summary-badge {{
            display: inline-block;
            background-color: #000000;
            color: #ffffff;
            padding: 2px 8px;
            font-size: 11px;
            margin-left: 8px;
        }}

        /* Для печати */
        @media print {{
            body {{
                background-color: #ffffff;
                padding: 0;
            }}

            .window {{
                box-shadow: none;
                border: none;
            }}

            .window-header {{
                background: #000000;
                -webkit-print-color-adjust: exact;
                print-color-adjust: exact;
            }}

            .segment:hover {{
                background-color: transparent;
            }}
        }}
    </style>
</head>
<body>
    <div class="window">
        <div class="window-header">
            <span class="window-title">{window_title}</span>
            <div class="window-buttons">
                <div class="window-btn"></div>
                <div class="window-btn"></div>
            </div>
        </div>

        <div class="content">
            <!-- Информация о файле -->
            <div class="info-panel">
                <div class="info-row">
                    <span class="info-label">{label_file}:</span>
                    <span class="info-value">{file_name}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">{label_duration}:</span>
                    <span class="info-value">{duration}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">{label_language}:</span>
                    <span class="info-value">{language} ({probability}%)</span>
                </div>
                <div class="info-row">
                    <span class="info-label">{label_model}:</span>
                    <span class="info-value">{model}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">{label_date}:</span>
                    <span class="info-value">{date}</span>
                </div>
            </div>

            <!-- Статистика -->
            <div class="stats">
                <div class="stat-item">
                    <div class="stat-value">{segment_count}</div>
                    <div class="stat-label">{label_segments}</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">{word_count}</div>
                    <div class="stat-label">{label_words}</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">{char_count}</div>
                    <div class="stat-label">{label_characters}</div>
                </div>
            </div>

            {summary_section}

            <!-- Полный текст -->
            <div class="section-title">{section_full_text}</div>
            <div class="full-text">
                {full_text}
            </div>

            <!-- Сегменты с таймкодами -->
            <div class="section-title">{section_segments}</div>
            <div class="segments">
                {segments_html}
            </div>
        </div>

        <div class="footer">
            <div class="logo">
                <div class="logo-icon">M</div>
                <span class="logo-text">MindType</span>
            </div>
            <div>{footer_text}</div>
        </div>
    </div>
</body>
</html>
'''

SEGMENT_TEMPLATE = '''<div class="segment">
    <div class="segment-time">{time}</div>
    <div class="segment-text">{text}</div>
</div>
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
                "section_full_text": "Полный текст",
                "section_segments": "Сегменты с таймкодами",
                "section_summary": "Саммари",
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
                "section_full_text": "Full Text",
                "section_segments": "Segments with Timestamps",
                "section_summary": "Summary",
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
                "section_full_text": "Volltext",
                "section_segments": "Segmente mit Zeitstempeln",
                "section_summary": "Zusammenfassung",
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
                "section_full_text": "Texte complet",
                "section_segments": "Segments avec horodatage",
                "section_summary": "Résumé",
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
                "section_full_text": "Texto completo",
                "section_segments": "Segmentos con marcas de tiempo",
                "section_summary": "Resumen",
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
                "section_full_text": "完整文本",
                "section_segments": "带时间戳的段落",
                "section_summary": "摘要",
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
                "section_full_text": "全文",
                "section_segments": "タイムスタンプ付きセグメント",
                "section_summary": "要約",
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
        """
        import re

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
                header_text = html.escape(line[3:].strip())
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
                    html_parts.append('<tr>' + ''.join(f'<th>{html.escape(c)}</th>' for c in cells) + '</tr>')
                    table_header_done = True
                else:
                    html_parts.append('<tr>' + ''.join(f'<td>{html.escape(c)}</td>' for c in cells) + '</tr>')
                continue

            # Список -
            if line.startswith('- '):
                if in_table:
                    html_parts.append('</table>')
                    in_table = False
                    table_header_done = False

                if not in_list:
                    html_parts.append('<ul>')
                    in_list = True

                item_text = line[2:].strip()
                # Обработка **жирного**
                item_text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', item_text)
                html_parts.append(f'<li>{html.escape(item_text).replace("&lt;strong&gt;", "<strong>").replace("&lt;/strong&gt;", "</strong>")}</li>')
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
            html_parts.append(f'<p>{html.escape(text).replace("&lt;strong&gt;", "<strong>").replace("&lt;/strong&gt;", "</strong>")}</p>')

        # Закрываем незакрытые теги
        if in_list:
            html_parts.append('</ul>')
        if in_table:
            html_parts.append('</table>')

        return '\n'.join(html_parts)

    def generate_html(self, result: TranscriptionResult, output_path: Optional[Path] = None) -> str:
        """
        Сгенерировать HTML отчёт.

        Args:
            result: Результат транскрипции
            output_path: Путь для сохранения (опционально)

        Returns:
            HTML строка
        """
        # Генерируем сегменты
        segments_html = ""
        for seg in result.segments:
            segments_html += SEGMENT_TEMPLATE.format(
                time=f"{seg.start_formatted} - {seg.end_formatted}",
                text=html.escape(seg.text)
            )

        # Подсчёт статистики
        full_text = result.full_text
        word_count = len(full_text.split())
        char_count = len(full_text)

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

            # Контент
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
        # Сначала генерируем HTML
        html_path = output_path.with_suffix(".html")
        self.generate_html(result, html_path)

        # Пробуем wkhtmltopdf
        wkhtmltopdf = shutil.which("wkhtmltopdf")
        if wkhtmltopdf:
            try:
                subprocess.run(
                    [wkhtmltopdf, "--quiet", str(html_path), str(output_path)],
                    check=True,
                    timeout=120
                )
                # Удаляем временный HTML если PDF создан успешно
                if output_path.exists():
                    html_path.unlink(missing_ok=True)
                    return True
            except (subprocess.SubprocessError, FileNotFoundError):
                pass

        # Пробуем weasyprint
        try:
            from weasyprint import HTML
            HTML(string=html_path.read_text(encoding="utf-8")).write_pdf(str(output_path))
            html_path.unlink(missing_ok=True)
            return True
        except ImportError:
            pass
        except Exception:
            pass

        # PDF недоступен, оставляем HTML
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


