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

        p.nav {{
            margin: 14px 0 4px 0;
            padding: 6px 10px;
            border: 1px solid #000000;
            background-color: #f2f2f2;
            font-size: 12px;
        }}
        p.nav a {{ color: #000000; font-weight: bold; text-decoration: none; }}

        table.segs {{ width: 100%; border: 1px solid #000000; border-collapse: collapse; }}
        table.segs td.t {{
            width: 110px;
            font-weight: bold;
            background-color: #f7f7f7;
            border-right: 1px solid #d0d0d0;
            border-bottom: 1px solid #ececec;
            padding: 6px 10px;
            font-size: 12px;
            white-space: nowrap;
            vertical-align: top;
            color: #444444;
        }}
        table.segs td.x {{ padding: 6px 10px; border-bottom: 1px solid #ececec; }}
        table.segs td.turnhead {{
            background-color: #ededed;
            border-top: 1px solid #000000;
            border-bottom: 1px solid #d0d0d0;
            padding: 6px 10px;
        }}
        .turn-range {{ font-size: 11px; color: #555555; font-weight: bold; }}

        .summary-intro {{ margin: 6px 0 10px 0; }}
        table.sumcard {{
            width: 100%;
            border: 1px solid #000000;
            border-collapse: collapse;
            margin: 0 0 10px 0;
        }}
        td.sumcard-h {{
            background-color: #000000;
            color: #ffffff;
            font-weight: bold;
            font-size: 12px;
            padding: 5px 10px;
        }}
        td.sumcard-b {{ padding: 10px 12px; background-color: #fcfcf5; }}
        td.sumcard-b h4 {{ font-size: 12px; font-weight: bold; margin: 8px 0 4px 0; }}
        td.sumcard-b ul, td.sumcard-b ol {{ margin: 4px 0 8px 20px; }}
        td.sumcard-b li {{ margin-bottom: 4px; }}
        td.sumcard-b p {{ margin: 4px 0; }}
        td.sumcard-b table {{ width: 100%; border-collapse: collapse; margin: 6px 0; }}
        td.sumcard-b th, td.sumcard-b td {{ border: 1px solid #000000; padding: 5px 8px; text-align: left; }}
        td.sumcard-b th {{ background-color: #e8e8e8; font-weight: bold; }}

        .summary {{
            border: 2px solid #000000;
            background-color: #fcfcf5;
            padding: 14px;
        }}
        .summary h3 {{ font-size: 13px; font-weight: bold; margin: 10px 0 5px 0; }}
        .summary h4 {{ font-size: 12px; font-weight: bold; margin: 8px 0 4px 0; }}
        .summary ul, .summary ol {{ margin: 4px 0 8px 20px; }}
        .summary li {{ margin-bottom: 4px; }}
        .summary table {{ width: 100%; border-collapse: collapse; margin: 6px 0; }}
        .summary th, .summary td {{ border: 1px solid #000000; padding: 5px 8px; text-align: left; }}
        .summary th {{ background-color: #e8e8e8; font-weight: bold; }}
        .summary strong {{ font-weight: bold; }}

        table.speakers {{ width: 100%; border: 1px solid #000000; border-collapse: collapse; }}
        table.speakers td {{ border-bottom: 1px solid #ececec; padding: 6px 10px; vertical-align: middle; }}
        table.speakers td.name {{ font-weight: bold; white-space: nowrap; }}
        table.speakers td.barcell {{ width: 34%; }}
        table.speakers td.pct {{ width: 60px; font-weight: bold; text-align: right; white-space: nowrap; }}
        table.speakers td.num {{ white-space: nowrap; color: #444444; }}
        table.bar {{ width: 100%; border-collapse: collapse; }}
        table.bar td {{ padding: 0; border: none; font-size: 4px; line-height: 4px; }}
        td.barrest {{ background-color: #e4e4e4; }}

        .speaker-tag {{ font-weight: bold; padding: 1px 6px; font-size: 11px; margin-right: 8px; }}
        .speaker-tag-0 {{ background-color: #FF6B6B; color: #fff; }}
        .speaker-tag-1 {{ background-color: #4ECDC4; color: #fff; }}
        .speaker-tag-2 {{ background-color: #45B7D1; color: #fff; }}
        .speaker-tag-3 {{ background-color: #96CEB4; color: #fff; }}
        .speaker-tag-4 {{ background-color: #FFEAA7; color: #333; }}
        .speaker-tag-5 {{ background-color: #DDA0DD; color: #fff; }}
        .speaker-tag-6 {{ background-color: #98D8C8; color: #333; }}
        .speaker-tag-7 {{ background-color: #F7DC6F; color: #333; }}

        td.barfill-0 {{ background-color: #FF6B6B; }}
        td.barfill-1 {{ background-color: #4ECDC4; }}
        td.barfill-2 {{ background-color: #45B7D1; }}
        td.barfill-3 {{ background-color: #96CEB4; }}
        td.barfill-4 {{ background-color: #FFEAA7; }}
        td.barfill-5 {{ background-color: #DDA0DD; }}
        td.barfill-6 {{ background-color: #98D8C8; }}
        td.barfill-7 {{ background-color: #F7DC6F; }}

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

            {nav_section}

            {summary_section}

            {speakers_section}

            <!-- Транскрипт по репликам с таймкодами -->
            <h2 class="section" id="transcript">{section_segments}</h2>
            <table class="segs" cellspacing="0">
                {segments_html}
            </table>

            <!-- Полный текст -->
            <h2 class="section" id="fulltext">{section_full_text}</h2>
            <div class="fulltext">{full_text}</div>
        </div>

        <div class="footer"><b>MindType</b> &mdash; {footer_text}</div>
    </div>
</body>
</html>
'''

SEGMENT_TEMPLATE = '''<tr><td class="t">{time}</td><td class="x">{text}</td></tr>
'''

TURN_HEADER_TEMPLATE = '''<tr><td class="t turnhead">{time}</td><td class="x turnhead">{speaker_tag}<span class="turn-range">{time_range}</span></td></tr>
'''

SPEAKERS_SECTION_TEMPLATE = '''
<h2 class="section" id="speakers">{title}</h2>
<table class="speakers" cellspacing="0">
    {speaker_cards}
</table>
'''

SPEAKER_CARD_TEMPLATE = '''<tr>
<td class="name"><span class="speaker-tag speaker-tag-{index}">{speaker_name}</span></td>
<td class="barcell"><table class="bar" cellspacing="0"><tr><td class="barfill-{index}" width="{pct_width}%">&nbsp;</td><td class="barrest" width="{pct_rest}%">&nbsp;</td></tr></table></td>
<td class="pct">{pct}%</td>
<td class="num">{duration}</td>
<td class="num">{segments} {segments_label}</td>
<td class="num">{words} {words_label}</td>
</tr>
'''

SUMMARY_CARD_TEMPLATE = '''<table class="sumcard" cellspacing="0">
<tr><td class="sumcard-h">{title}</td></tr>
<tr><td class="sumcard-b">{body}</td></tr>
</table>
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
                "section_segments": "Транскрипт",
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
                "section_segments": "Transcript",
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
        - ## / ### заголовки → <h3> / <h4>
        - - и * списки → <ul>; 1. и 1) списки → <ol>
        - **жирный** → <strong>
        - | таблицы | и || таблицы | (формат из встроенных пресетов)
        - $LaTeX$ формулы (сохраняются как есть для MathJax)
        """
        import re
        import uuid

        def _escape_preserving_latex(text: str) -> str:
            """Экранировать HTML, сохраняя LaTeX формулы."""
            latex_placeholders = {}

            def save_latex(match):
                placeholder = f"__LATEX_{uuid.uuid4().hex[:8]}__"
                latex_placeholders[placeholder] = match.group(0)
                return placeholder

            # Сохраняем $...$ и $$...$$
            text = re.sub(r'\$\$[^$]+\$\$', save_latex, text)
            text = re.sub(r'\$[^$]+\$', save_latex, text)

            text = html.escape(text)

            for placeholder, latex in latex_placeholders.items():
                text = text.replace(placeholder, latex)

            return text

        def _inline(text: str) -> str:
            """Инлайн-разметка: **жирный** + экранирование с сохранением LaTeX."""
            text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
            text = _escape_preserving_latex(text)
            return text.replace("&lt;strong&gt;", "<strong>").replace("&lt;/strong&gt;", "</strong>")

        lines = summary.split('\n')
        html_parts = []
        in_ul = False
        in_ol = False
        in_table = False
        table_header_done = False

        def close_lists():
            nonlocal in_ul, in_ol
            if in_ul:
                html_parts.append('</ul>')
                in_ul = False
            if in_ol:
                html_parts.append('</ol>')
                in_ol = False

        def close_table():
            nonlocal in_table, table_header_done
            if in_table:
                html_parts.append('</table>')
                in_table = False
                table_header_done = False

        for line in lines:
            line = line.strip()
            if not line:
                close_lists()
                close_table()
                continue

            # Заголовки ### и ##
            if line.startswith('### '):
                close_lists()
                close_table()
                html_parts.append(f'<h4>{_inline(line[4:].strip())}</h4>')
                continue
            if line.startswith('## '):
                close_lists()
                close_table()
                html_parts.append(f'<h3>{_inline(line[3:].strip())}</h3>')
                continue

            # Таблица: | ячейки | или || ячейки | (double-pipe из пресетов)
            if line.startswith('|'):
                close_lists()

                # Пропускаем разделитель |---|---| и ||---|---|
                if re.match(r'^\|{1,2}[\s\-|:]+$', line):
                    continue

                cells = [c.strip() for c in line.strip('|').split('|')]

                if not in_table:
                    html_parts.append('<table>')
                    in_table = True

                tag = 'td' if table_header_done else 'th'
                html_parts.append(
                    '<tr>' + ''.join(f'<{tag}>{_inline(c)}</{tag}>' for c in cells) + '</tr>'
                )
                table_header_done = True
                continue

            # Маркированный список - или *
            if line.startswith('- ') or line.startswith('* '):
                close_table()
                if in_ol:
                    html_parts.append('</ol>')
                    in_ol = False
                if not in_ul:
                    html_parts.append('<ul>')
                    in_ul = True
                html_parts.append(f'<li>{_inline(line[2:].strip())}</li>')
                continue

            # Нумерованный список 1. или 1)
            ol_match = re.match(r'^\d+[.)]\s+(.*)$', line)
            if ol_match:
                close_table()
                if in_ul:
                    html_parts.append('</ul>')
                    in_ul = False
                if not in_ol:
                    html_parts.append('<ol>')
                    in_ol = True
                html_parts.append(f'<li>{_inline(ol_match.group(1))}</li>')
                continue

            # Обычный текст
            close_lists()
            close_table()
            html_parts.append(f'<p>{_inline(line)}</p>')

        close_lists()
        close_table()

        return '\n'.join(html_parts)

    def _split_summary_sections(self, summary: str) -> tuple:
        """
        Разбить саммари на преамбулу и секции по строкам '## '.

        Returns:
            (интро-текст, [(заголовок, тело), ...])
        """
        intro_lines = []
        sections = []
        for line in summary.split('\n'):
            stripped = line.strip()
            if stripped.startswith('## '):
                sections.append([stripped[3:].strip(), []])
            elif sections:
                sections[-1][1].append(line)
            else:
                intro_lines.append(line)
        return (
            '\n'.join(intro_lines).strip(),
            [(title, '\n'.join(body).strip()) for title, body in sections],
        )

    def _generate_summary_section(self, result: TranscriptionResult) -> str:
        """Секция саммари: карточки по '## ' секциям промпта пресета."""
        if not result.has_summary:
            return ""

        import re

        badges = f'<span class="badge">{self._labels["summary_badge"]}</span>'
        if result.summary_preset_name:
            badges += f'<span class="badge">{html.escape(result.summary_preset_name)}</span>'

        parts = [
            f'<h2 class="section" id="summary">{self._labels["section_summary"]}{badges}</h2>'
        ]

        intro, sections = self._split_summary_sections(result.summary)
        if sections:
            if intro:
                parts.append(
                    f'<div class="summary-intro">{self._format_summary_as_html(intro)}</div>'
                )
            for title, body in sections:
                plain_title = html.escape(re.sub(r'\*\*(.+?)\*\*', r'\1', title))
                body_html = self._format_summary_as_html(body) or '<p>&mdash;</p>'
                parts.append(SUMMARY_CARD_TEMPLATE.format(title=plain_title, body=body_html))
        else:
            # Саммари без ## секций — единый блок
            parts.append(f'<div class="summary">{self._format_summary_as_html(result.summary)}</div>')

        return '\n'.join(parts)

    def _get_speaker_index(self, speaker_id: str) -> int:
        """Получить индекс спикера из ID (SPEAKER_00 -> 0)."""
        import re
        match = re.search(r'SPEAKER_(\d+)', speaker_id)
        if match:
            return int(match.group(1)) % 8  # Макс 8 цветов
        return 0

    def _speaker_display_name(self, result: TranscriptionResult, speaker_id: str) -> str:
        """Отображаемое имя спикера: карта имён → статистика → сырой ID."""
        if result.speaker_names and speaker_id in result.speaker_names:
            return result.speaker_names[speaker_id]
        if result.speaker_stats:
            for stat in result.speaker_stats:
                if stat.speaker_id == speaker_id and stat.speaker_name:
                    return stat.speaker_name
        return speaker_id

    def _generate_speakers_section(self, result: TranscriptionResult) -> str:
        """Секция участников: цветная метка, доля времени, реплики, слова."""
        if not result.has_speakers or not result.speaker_stats:
            return ""

        total_duration = sum(s.total_duration for s in result.speaker_stats) or 1.0

        speaker_cards = ""
        for stat in result.speaker_stats:
            index = self._get_speaker_index(stat.speaker_id)
            pct = round(100.0 * stat.total_duration / total_duration)
            pct_width = min(100, max(2, pct))
            speaker_cards += SPEAKER_CARD_TEMPLATE.format(
                index=index,
                speaker_name=html.escape(self._speaker_display_name(result, stat.speaker_id)),
                pct=pct,
                pct_width=pct_width,
                pct_rest=100 - pct_width,
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

    def _generate_nav_section(self, result: TranscriptionResult) -> str:
        """Строка навигации по якорям секций отчёта."""
        links = []
        if result.has_summary:
            links.append(("#summary", self._labels["section_summary"]))
        if result.has_speakers and result.speaker_stats:
            links.append(("#speakers", self._labels.get("section_speakers", "Участники")))
        links.append(("#transcript", self._labels["section_segments"]))
        links.append(("#fulltext", self._labels["section_full_text"]))
        items = ' &nbsp;&bull;&nbsp; '.join(f'<a href="{href}">{title}</a>' for href, title in links)
        return f'<p class="nav">{items}</p>'

    def _generate_segments_html(self, result: TranscriptionResult) -> str:
        """
        Транскрипт с таймкодами.

        Если есть спикеры — подряд идущие сегменты одного спикера группируются
        в «реплики»: заголовок с цветной меткой спикера и диапазоном времени,
        под ним строки [время | текст].
        """
        has_speakers = any(seg.speaker for seg in result.segments)

        if not has_speakers:
            return "".join(
                SEGMENT_TEMPLATE.format(
                    time=seg.start_formatted,
                    text=html.escape(seg.text),
                )
                for seg in result.segments
            )

        # Группируем подряд идущие сегменты одного спикера
        turns: list = []
        for seg in result.segments:
            if turns and turns[-1][0] == seg.speaker:
                turns[-1][1].append(seg)
            else:
                turns.append([seg.speaker, [seg]])

        parts = []
        for speaker, segs in turns:
            if speaker:
                index = self._get_speaker_index(speaker)
                name = self._speaker_display_name(result, speaker)
                speaker_tag = (
                    f'<span class="speaker-tag speaker-tag-{index}">{html.escape(name)}</span>'
                )
            else:
                speaker_tag = '<span class="speaker-tag">&mdash;</span>'

            parts.append(TURN_HEADER_TEMPLATE.format(
                time=segs[0].start_formatted,
                speaker_tag=speaker_tag,
                time_range=f"{segs[0].start_formatted}&ndash;{segs[-1].end_formatted}",
            ))
            for seg in segs:
                parts.append(SEGMENT_TEMPLATE.format(
                    time=seg.start_formatted,
                    text=html.escape(seg.text),
                ))

        return "".join(parts)

    def generate_html(self, result: TranscriptionResult, output_path: Optional[Path] = None) -> str:
        """
        Сгенерировать HTML отчёт.

        Args:
            result: Результат транскрипции
            output_path: Путь для сохранения (опционально)

        Returns:
            HTML строка
        """
        # Транскрипт: реплики спикеров с таймкодами
        segments_html = self._generate_segments_html(result)

        # Подсчёт статистики
        full_text = result.full_text
        word_count = len(full_text.split())
        char_count = len(full_text)

        # Полный текст: обработанный (с разметкой спикеров), если есть
        display_text = result.processed_text or full_text

        # Секции: навигация, саммари, участники
        nav_section = self._generate_nav_section(result)
        speakers_section = self._generate_speakers_section(result)
        summary_section = self._generate_summary_section(result)

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
            nav_section=nav_section,
            speakers_section=speakers_section,
            summary_section=summary_section,
            full_text=html.escape(display_text),
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


