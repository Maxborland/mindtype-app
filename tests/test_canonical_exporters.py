from __future__ import annotations

import json
import os
from pathlib import Path
from zipfile import ZipFile

import pytest

from tests.test_result_schema import canonical_result


@pytest.fixture(scope="module", autouse=True)
def qt_application():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    application = QApplication.instance() or QApplication([])
    yield application


def _hostile_result() -> dict:
    result = canonical_result("operation-export")
    result["source"]["display_name"] = 'CON:<meeting>|".wav'
    result["transcript"]["segments"] = [
        {
            "segment_id": "segment-1",
            "start_ms": 1_234,
            "end_ms": 3_456,
            "text": '<script>alert("x")</script> & raw',
            "speaker_id": "speaker-1",
            "words": [],
            "confidence": 0.9,
            "postprocessed": False,
        },
        {
            "segment_id": "segment-2",
            "start_ms": 4_000,
            "end_ms": 5_000,
            "text": "Вторая строка",
            "speaker_id": None,
            "words": [],
            "confidence": None,
            "postprocessed": False,
        },
    ]
    result["summary"] = {
        "text": "<b>Вывод</b>",
        "preset": "pm",
        "generated": True,
        "source_segment_ids": ["segment-1"],
    }
    return result


def test_export_bundle_creates_all_open_formats_without_overwrite(
    tmp_path: Path,
) -> None:
    from app.exporters import CanonicalExporter, ExportFormat

    exporter = CanonicalExporter()
    first = exporter.export_bundle(_hostile_result(), tmp_path)
    second = exporter.export_bundle(_hostile_result(), tmp_path)

    assert set(first) == set(ExportFormat)
    assert all(path.is_file() for path in first.values())
    assert set(first.values()).isdisjoint(second.values())
    assert json.loads(first[ExportFormat.JSON].read_text(encoding="utf-8"))[
        "operation_id"
    ] == "operation-export"


def test_text_markdown_and_subtitles_preserve_raw_segments(tmp_path: Path) -> None:
    from app.exporters import CanonicalExporter, ExportFormat

    files = CanonicalExporter().export_bundle(_hostile_result(), tmp_path)
    txt = files[ExportFormat.TXT].read_text(encoding="utf-8")
    markdown = files[ExportFormat.MARKDOWN].read_text(encoding="utf-8")
    srt = files[ExportFormat.SRT].read_text(encoding="utf-8")
    vtt = files[ExportFormat.VTT].read_text(encoding="utf-8")

    assert "[00:00:01.234]" in txt
    assert 'Speaker 1: <script>alert("x")</script> & raw' in txt
    assert "AI-generated summary" in markdown
    assert "segment-1" in markdown
    assert "<script>" not in markdown
    assert "&lt;script&gt;" in markdown
    assert "00:00:01,234 --> 00:00:03,456" in srt
    assert "&lt;script&gt;" in srt
    assert vtt.startswith("WEBVTT\n")
    assert "00:01.234 --> 00:03.456" in vtt


def test_html_is_static_escaped_and_has_strict_csp(tmp_path: Path) -> None:
    from app.exporters import CanonicalExporter, ExportFormat

    html = CanonicalExporter().export_bundle(_hostile_result(), tmp_path)[
        ExportFormat.HTML
    ].read_text(encoding="utf-8")

    assert "default-src 'none'" in html
    assert "<script" not in html.lower()
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in html
    assert "&lt;b&gt;Вывод&lt;/b&gt;" in html
    assert "https://" not in html


def test_docx_is_valid_zip_and_hostile_text_is_xml_escaped(tmp_path: Path) -> None:
    from app.exporters import CanonicalExporter, ExportFormat

    docx = CanonicalExporter().export_bundle(_hostile_result(), tmp_path)[
        ExportFormat.DOCX
    ]
    with ZipFile(docx) as archive:
        assert archive.testzip() is None
        document = archive.read("word/document.xml").decode("utf-8")

    assert "<script>" not in document
    assert "&lt;script&gt;" in document
    assert "AI-generated summary" in document


def test_failed_projection_leaves_no_partial_bundle(
    tmp_path: Path, monkeypatch
) -> None:
    from app.exporters import CanonicalExporter

    exporter = CanonicalExporter()
    monkeypatch.setattr(
        exporter,
        "_write_pdf",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("PDF failed")),
    )

    with pytest.raises(RuntimeError, match="PDF failed"):
        exporter.export_bundle(_hostile_result(), tmp_path)

    assert list(tmp_path.iterdir()) == []
