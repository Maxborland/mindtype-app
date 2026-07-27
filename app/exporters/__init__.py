from __future__ import annotations

import html
import hashlib
import json
import os
import re
import shutil
import tempfile
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZipFile

from ..result_schema import validate_canonical_result


class ExportFormat(str, Enum):
    TXT = "txt"
    MARKDOWN = "md"
    JSON = "json"
    SRT = "srt"
    VTT = "vtt"
    DOCX = "docx"
    HTML = "html"
    PDF = "pdf"


_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def _safe_stem(display_name: str) -> str:
    stem = Path(display_name).stem
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", stem)
    stem = stem.strip(" .")[:100] or "transcript"
    if stem.upper() in _WINDOWS_RESERVED:
        stem = f"_{stem}"
    return f"{stem}_transcription"


def _timecode(milliseconds: int, *, decimal: str = ".") -> str:
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return (
        f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        f"{decimal}{millis:03d}"
    )


def _vtt_timecode(milliseconds: int) -> str:
    full = _timecode(milliseconds)
    return full[3:] if full.startswith("00:") else full


class CanonicalExporter:
    formats = tuple(ExportFormat)

    def export_bundle(
        self,
        payload: Mapping[str, Any],
        output_dir: Path,
        *,
        formats: Iterable[ExportFormat] = formats,
        idempotency_key: str | None = None,
    ) -> dict[ExportFormat, Path]:
        result = validate_canonical_result(payload)
        selected = tuple(dict.fromkeys(ExportFormat(item) for item in formats))
        if not selected:
            raise ValueError("At least one export format is required")
        destination = Path(output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        base_stem = _safe_stem(result["source"]["display_name"])
        if idempotency_key is None:
            stem = self._unique_stem(destination, base_stem, selected)
        else:
            digest = hashlib.sha256(
                idempotency_key.encode("utf-8")
            ).hexdigest()[:12]
            stem = f"{base_stem}_{digest}"
        final_paths = {
            format_: destination / f"{stem}.{format_.value}"
            for format_ in selected
        }

        stage = Path(tempfile.mkdtemp(prefix=".mindtype-export-", dir=destination))
        published: list[Path] = []
        backups: dict[Path, Path] = {}
        try:
            staged_paths = {
                format_: stage / final_path.name
                for format_, final_path in final_paths.items()
            }
            html_content = self._render_html(result)
            for format_, path in staged_paths.items():
                self._write_projection(
                    format_, result, path, html_content=html_content
                )
            if idempotency_key is None and any(
                path.exists() for path in final_paths.values()
            ):
                raise FileExistsError("Export destination appeared during rendering")
            backup_dir = stage / "backups"
            for final_path in final_paths.values():
                if final_path.exists():
                    backup_dir.mkdir(exist_ok=True)
                    backup_path = backup_dir / final_path.name
                    shutil.copy2(final_path, backup_path)
                    backups[final_path] = backup_path
            for format_, staged_path in staged_paths.items():
                os.replace(staged_path, final_paths[format_])
                published.append(final_paths[format_])
            return final_paths
        except Exception as publish_error:
            restore_errors: list[OSError] = []
            for final_path in published:
                backup_path = backups.get(final_path)
                try:
                    if backup_path is not None:
                        os.replace(backup_path, final_path)
                    else:
                        final_path.unlink(missing_ok=True)
                except OSError as exc:
                    restore_errors.append(exc)
            if restore_errors:
                raise RuntimeError(
                    "Export publication failed and existing projections "
                    "could not be fully restored"
                ) from publish_error
            raise
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    @staticmethod
    def _unique_stem(
        output_dir: Path,
        base: str,
        formats: Iterable[ExportFormat],
    ) -> str:
        candidate = base
        counter = 2
        suffixes = tuple(format_.value for format_ in formats)
        while any((output_dir / f"{candidate}.{suffix}").exists() for suffix in suffixes):
            candidate = f"{base}_{counter}"
            counter += 1
        return candidate

    def _write_projection(
        self,
        format_: ExportFormat,
        result: Mapping[str, Any],
        path: Path,
        *,
        html_content: str,
    ) -> None:
        if format_ is ExportFormat.TXT:
            path.write_text(self._render_txt(result), encoding="utf-8", newline="\n")
        elif format_ is ExportFormat.MARKDOWN:
            path.write_text(
                self._render_markdown(result), encoding="utf-8", newline="\n"
            )
        elif format_ is ExportFormat.JSON:
            path.write_text(
                json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)
                + "\n",
                encoding="utf-8",
                newline="\n",
            )
        elif format_ is ExportFormat.SRT:
            path.write_text(self._render_srt(result), encoding="utf-8", newline="\n")
        elif format_ is ExportFormat.VTT:
            path.write_text(self._render_vtt(result), encoding="utf-8", newline="\n")
        elif format_ is ExportFormat.DOCX:
            self._write_docx(result, path)
        elif format_ is ExportFormat.HTML:
            path.write_text(html_content, encoding="utf-8", newline="\n")
        elif format_ is ExportFormat.PDF:
            self._write_pdf(html_content, path)
        else:
            raise ValueError(f"Unsupported export format: {format_}")

    @staticmethod
    def _speaker_names(result: Mapping[str, Any]) -> dict[str, str]:
        return {
            str(speaker["speaker_id"]): str(
                speaker.get("display_name") or speaker["speaker_id"]
            )
            for speaker in result["speakers"]
        }

    @classmethod
    def _segment_label(
        cls, result: Mapping[str, Any], segment: Mapping[str, Any]
    ) -> str:
        speaker_id = segment.get("speaker_id")
        if not speaker_id:
            return ""
        return cls._speaker_names(result).get(str(speaker_id), str(speaker_id))

    @classmethod
    def _render_txt(cls, result: Mapping[str, Any]) -> str:
        lines = [f"Transcript: {result['source']['display_name']}", ""]
        for segment in result["transcript"]["segments"]:
            label = cls._segment_label(result, segment)
            prefix = f"{label}: " if label else ""
            lines.append(
                f"[{_timecode(segment['start_ms'])}] {prefix}{segment['text']}"
            )
        summary = result.get("summary")
        if summary is not None:
            lines.extend(
                [
                    "",
                    "AI-generated summary",
                    str(summary["text"]),
                    "Sources: " + ", ".join(summary["source_segment_ids"]),
                ]
            )
        return "\n".join(lines).rstrip() + "\n"

    @classmethod
    def _render_markdown(cls, result: Mapping[str, Any]) -> str:
        def safe_text(value: object) -> str:
            return html.escape(str(value), quote=False)

        lines = [
            f"# Transcript: {safe_text(result['source']['display_name'])}",
            "",
            f"- Language: `{safe_text(result['transcript']['language'])}`",
            f"- Duration: `{_timecode(result['source']['duration_ms'])}`",
            "",
            "## Raw transcript",
            "",
        ]
        for segment in result["transcript"]["segments"]:
            label = cls._segment_label(result, segment)
            prefix = f" **{safe_text(label)}:**" if label else ""
            lines.append(
                f"- `{_timecode(segment['start_ms'])}`{prefix} "
                f"{safe_text(segment['text'])}"
            )
        summary = result.get("summary")
        if summary is not None:
            lines.extend(
                [
                    "",
                    "## AI-generated summary",
                    "",
                    safe_text(summary["text"]),
                    "",
                    "**Source segments:** "
                    + ", ".join(f"`{item}`" for item in summary["source_segment_ids"]),
                ]
            )
        return "\n".join(lines).rstrip() + "\n"

    @classmethod
    def _subtitle_text(
        cls, result: Mapping[str, Any], segment: Mapping[str, Any]
    ) -> str:
        label = cls._segment_label(result, segment)
        prefix = f"{label}: " if label else ""
        return html.escape(prefix + str(segment["text"]), quote=True)

    @classmethod
    def _render_srt(cls, result: Mapping[str, Any]) -> str:
        blocks = []
        for index, segment in enumerate(result["transcript"]["segments"], start=1):
            blocks.append(
                "\n".join(
                    [
                        str(index),
                        f"{_timecode(segment['start_ms'], decimal=',')} --> "
                        f"{_timecode(segment['end_ms'], decimal=',')}",
                        cls._subtitle_text(result, segment),
                    ]
                )
            )
        return "\n\n".join(blocks).rstrip() + "\n"

    @classmethod
    def _render_vtt(cls, result: Mapping[str, Any]) -> str:
        blocks = ["WEBVTT"]
        for segment in result["transcript"]["segments"]:
            blocks.append(
                "\n".join(
                    [
                        f"{_vtt_timecode(segment['start_ms'])} --> "
                        f"{_vtt_timecode(segment['end_ms'])}",
                        cls._subtitle_text(result, segment),
                    ]
                )
            )
        return "\n\n".join(blocks).rstrip() + "\n"

    @classmethod
    def _render_html(cls, result: Mapping[str, Any]) -> str:
        title = html.escape(str(result["source"]["display_name"]), quote=True)
        rows = []
        for segment in result["transcript"]["segments"]:
            label = cls._segment_label(result, segment)
            rows.append(
                "<li>"
                f"<time>{_timecode(segment['start_ms'])}</time> "
                + (
                    f"<strong>{html.escape(label, quote=True)}:</strong> "
                    if label
                    else ""
                )
                + f"<span>{html.escape(str(segment['text']), quote=True)}</span>"
                "</li>"
            )
        summary_html = ""
        summary = result.get("summary")
        if summary is not None:
            references = ", ".join(
                html.escape(str(item), quote=True)
                for item in summary["source_segment_ids"]
            )
            summary_html = (
                "<section><h2>AI-generated summary</h2>"
                f"<p>{html.escape(str(summary['text']), quote=True)}</p>"
                f"<p><strong>Source segments:</strong> {references}</p></section>"
            )
        return (
            "<!doctype html><html><head><meta charset=\"utf-8\">"
            "<meta http-equiv=\"Content-Security-Policy\" "
            "content=\"default-src 'none'; style-src 'unsafe-inline'; "
            "img-src data:; base-uri 'none'; form-action 'none'; "
            "frame-ancestors 'none'\">"
            f"<title>{title}</title>"
            "<style>body{font:15px/1.5 system-ui,sans-serif;max-width:900px;"
            "margin:2rem auto;padding:0 1rem;color:#111}time{font-family:monospace;"
            "color:#555}li{margin:.7rem 0}h1,h2{line-height:1.2}</style>"
            "</head><body>"
            f"<h1>Transcript: {title}</h1><section><h2>Raw transcript</h2>"
            f"<ol>{''.join(rows)}</ol></section>{summary_html}</body></html>"
        )

    @classmethod
    def _docx_paragraphs(cls, result: Mapping[str, Any]) -> list[str]:
        paragraphs = [f"Transcript: {result['source']['display_name']}", "Raw transcript"]
        for segment in result["transcript"]["segments"]:
            label = cls._segment_label(result, segment)
            prefix = f"{label}: " if label else ""
            paragraphs.append(
                f"[{_timecode(segment['start_ms'])}] {prefix}{segment['text']}"
            )
        summary = result.get("summary")
        if summary is not None:
            paragraphs.extend(
                [
                    "AI-generated summary",
                    str(summary["text"]),
                    "Source segments: " + ", ".join(summary["source_segment_ids"]),
                ]
            )
        return paragraphs

    @classmethod
    def _write_docx(cls, result: Mapping[str, Any], path: Path) -> None:
        word_namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        ElementTree.register_namespace("w", word_namespace)
        document = ElementTree.Element(f"{{{word_namespace}}}document")
        body = ElementTree.SubElement(document, f"{{{word_namespace}}}body")
        for text in cls._docx_paragraphs(result):
            paragraph = ElementTree.SubElement(body, f"{{{word_namespace}}}p")
            run = ElementTree.SubElement(paragraph, f"{{{word_namespace}}}r")
            node = ElementTree.SubElement(run, f"{{{word_namespace}}}t")
            node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            node.text = text
        section = ElementTree.SubElement(body, f"{{{word_namespace}}}sectPr")
        ElementTree.SubElement(section, f"{{{word_namespace}}}pgSz")

        content_types = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>"
        )
        relationships = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/></Relationships>'
        )
        with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", content_types)
            archive.writestr("_rels/.rels", relationships)
            archive.writestr(
                "word/document.xml",
                ElementTree.tostring(
                    document, encoding="utf-8", xml_declaration=True
                ),
            )

    @staticmethod
    def _write_pdf(html_content: str, path: Path) -> None:
        from PyQt6.QtCore import QMarginsF
        from PyQt6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument
        from PyQt6.QtWidgets import QApplication

        if QApplication.instance() is None:
            raise RuntimeError("PDF export requires the running desktop application")
        writer = QPdfWriter(str(path))
        writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        writer.setPageMargins(
            QMarginsF(15, 15, 15, 15),
            QPageLayout.Unit.Millimeter,
        )
        document = QTextDocument()
        document.setHtml(html_content)
        document.print(writer)
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError("Qt did not create a PDF")


__all__ = ["CanonicalExporter", "ExportFormat"]
