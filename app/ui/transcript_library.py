"""System 7 transcript library UI."""

from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..transcript_store import SummaryVariant, TranscriptDocument, TranscriptStore
from .components import EmptyState, System7Window
from .tokens import SPACING


class TranscriptLibraryWidget(QWidget):
    """Browse durable MindType transcript documents."""

    new_transcription_requested = pyqtSignal()
    document_generation_requested = pyqtSignal(str)

    def __init__(
        self,
        store: TranscriptStore,
        translate_func: Optional[Callable[[str], str]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.store = store
        self._translate = translate_func or (lambda key: key)
        self._documents_by_id: dict[str, TranscriptDocument] = {}
        self._summary_variants_by_id: dict[str, SummaryVariant] = {}
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            SPACING["lg"],
            SPACING["lg"],
            SPACING["lg"],
            SPACING["lg"],
        )
        layout.setSpacing(SPACING["md"])

        header = QHBoxLayout()
        title = QLabel(self._translate("library_title"))
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        header.addStretch()

        self.new_transcription_button = QPushButton(
            self._translate("library_new_transcription")
        )
        self.new_transcription_button.setObjectName("primaryButton")
        self.new_transcription_button.clicked.connect(
            self.new_transcription_requested.emit
        )
        header.addWidget(self.new_transcription_button)
        layout.addLayout(header)

        self.document_list = QListWidget()
        self.document_list.setObjectName("transcriptDocumentList")
        self.document_list.currentItemChanged.connect(
            self._on_document_selected
        )

        documents_window = System7Window(
            self._translate("library_documents"),
            show_close=False,
        )
        documents_window.content_layout.setContentsMargins(0, 0, 0, 0)
        documents_window.content_layout.addWidget(self.document_list)

        details_window = System7Window(
            self._translate("library_transcript"),
            show_close=False,
        )
        self.metadata_label = QLabel()
        self.metadata_label.setObjectName("caption")
        self.metadata_label.setWordWrap(True)
        details_window.content_layout.addWidget(self.metadata_label)

        self.detail_tabs = QTabWidget()

        transcript_tab = QWidget()
        transcript_layout = QVBoxLayout(transcript_tab)
        transcript_layout.setContentsMargins(0, 0, 0, 0)
        self.transcript_output = QTextEdit()
        self.transcript_output.setReadOnly(True)
        self.transcript_output.setObjectName("transcriptOutput")
        transcript_layout.addWidget(self.transcript_output)
        self.detail_tabs.addTab(
            transcript_tab,
            self._translate("library_transcript"),
        )

        speakers_tab = QWidget()
        speakers_layout = QVBoxLayout(speakers_tab)
        speakers_layout.setContentsMargins(
            SPACING["sm"],
            SPACING["sm"],
            SPACING["sm"],
            SPACING["sm"],
        )
        self.speaker_form = QFormLayout()
        self.speaker_name_edits: dict[str, QLineEdit] = {}
        speakers_layout.addLayout(self.speaker_form)
        speakers_layout.addStretch()
        self.save_speaker_names_button = QPushButton(
            self._translate("library_save_speakers")
        )
        self.save_speaker_names_button.clicked.connect(
            self._save_speaker_names
        )
        speakers_layout.addWidget(self.save_speaker_names_button)
        self.detail_tabs.addTab(
            speakers_tab,
            self._translate("library_speakers"),
        )

        summaries_tab = QWidget()
        summaries_layout = QVBoxLayout(summaries_tab)
        summaries_layout.setContentsMargins(0, 0, 0, 0)
        summaries_layout.setSpacing(SPACING["sm"])

        summary_actions = QHBoxLayout()
        summary_actions.addStretch()
        self.create_document_button = QPushButton(
            self._translate("library_create_document")
        )
        self.create_document_button.setObjectName("primaryButton")
        self.create_document_button.clicked.connect(
            self._request_document_generation
        )
        summary_actions.addWidget(self.create_document_button)
        summaries_layout.addLayout(summary_actions)

        summary_content = QHBoxLayout()
        summary_content.setContentsMargins(0, 0, 0, 0)
        summary_content.setSpacing(SPACING["sm"])

        self.summary_variant_list = QListWidget()
        self.summary_variant_list.setObjectName("summaryVariantList")
        self.summary_variant_list.setMinimumWidth(180)
        self.summary_variant_list.currentItemChanged.connect(
            self._on_summary_variant_selected
        )
        summary_content.addWidget(self.summary_variant_list, stretch=1)

        summary_detail = QWidget()
        summary_detail_layout = QVBoxLayout(summary_detail)
        summary_detail_layout.setContentsMargins(0, 0, 0, 0)
        self.summary_metadata_label = QLabel()
        self.summary_metadata_label.setObjectName("caption")
        self.summary_metadata_label.setWordWrap(True)
        summary_detail_layout.addWidget(self.summary_metadata_label)
        self.summary_output = QTextEdit()
        self.summary_output.setReadOnly(True)
        self.summary_output.setObjectName("summaryOutput")
        summary_detail_layout.addWidget(self.summary_output, stretch=1)
        summary_content.addWidget(summary_detail, stretch=3)
        summaries_layout.addLayout(summary_content, stretch=1)

        self.detail_tabs.addTab(
            summaries_tab,
            self._translate("library_summaries"),
        )

        details_window.content_layout.addWidget(self.detail_tabs, stretch=1)

        self.library_page = QSplitter(Qt.Orientation.Horizontal)
        self.library_page.setChildrenCollapsible(False)
        self.library_page.addWidget(documents_window)
        self.library_page.addWidget(details_window)
        self.library_page.setStretchFactor(0, 1)
        self.library_page.setStretchFactor(1, 3)
        self.library_page.setSizes([260, 760])

        self.empty_state = EmptyState(
            icon="▦",
            title=self._translate("library_empty_title"),
            hint=self._translate("library_empty_hint"),
        )

        self._stack = QStackedWidget()
        self._stack.addWidget(self.empty_state)
        self._stack.addWidget(self.library_page)
        layout.addWidget(self._stack, stretch=1)

    def refresh(self) -> None:
        self.document_list.clear()
        self._documents_by_id.clear()
        for document in self.store.list_documents():
            self._documents_by_id[document.id] = document
            item = QListWidgetItem(
                f"{document.source_path.name}\n"
                f"{document.created_at:%Y-%m-%d %H:%M}"
            )
            item.setData(Qt.ItemDataRole.UserRole, document.id)
            self.document_list.addItem(item)

        self._stack.setCurrentWidget(
            self.library_page if self.document_list.count() else self.empty_state
        )
        if self.document_list.count():
            self.document_list.setCurrentRow(0)

    def _on_document_selected(
        self,
        current: Optional[QListWidgetItem],
        previous: Optional[QListWidgetItem],
    ) -> None:
        del previous
        if current is None:
            return
        document_id = current.data(Qt.ItemDataRole.UserRole)
        document = self.store.get_document(document_id)
        if document is not None:
            self._documents_by_id[document.id] = document
            self._render_document(document)
            self.create_document_button.setEnabled(True)

    def _render_document(self, document: TranscriptDocument) -> None:
        revision = document.current_revision
        self.metadata_label.setText(
            " · ".join(
                (
                    document.source_path.name,
                    document.detected_language or "—",
                    f"{document.duration:.0f}s",
                    f"{self._translate('library_revision')} {revision.number}",
                )
            )
        )

        lines = []
        for segment in revision.segments:
            speaker = revision.speaker_names.get(
                segment.speaker or "",
                segment.speaker or self._translate("library_unknown_speaker"),
            )
            lines.append(
                f"[{segment.start_formatted}] {speaker}: {segment.text}"
            )
        self.transcript_output.setPlainText("\n".join(lines))
        self._render_speaker_editor(document)
        self._render_summary_variants(document)

    def _render_summary_variants(self, document: TranscriptDocument) -> None:
        self.summary_variant_list.blockSignals(True)
        self.summary_variant_list.clear()
        self._summary_variants_by_id.clear()
        for variant in document.summary_variants:
            self._summary_variants_by_id[variant.id] = variant
            item = QListWidgetItem(variant.template_name)
            item.setData(Qt.ItemDataRole.UserRole, variant.id)
            self.summary_variant_list.addItem(item)
        self.summary_variant_list.blockSignals(False)

        if self.summary_variant_list.count():
            self.summary_variant_list.setCurrentRow(0)
        else:
            self.summary_metadata_label.clear()
            self.summary_output.setPlainText(
                self._translate("library_no_summaries")
            )

    def _on_summary_variant_selected(
        self,
        current: Optional[QListWidgetItem],
        previous: Optional[QListWidgetItem],
    ) -> None:
        del previous
        if current is None:
            return
        variant_id = current.data(Qt.ItemDataRole.UserRole)
        variant = self._summary_variants_by_id.get(variant_id)
        if variant is None:
            return
        self.summary_metadata_label.setText(
            " · ".join(
                (
                    variant.template_name,
                    f"v{variant.template_version}",
                    variant.provider,
                    variant.model,
                )
            )
        )
        self.summary_output.setPlainText(variant.content)

    def _render_speaker_editor(self, document: TranscriptDocument) -> None:
        while self.speaker_form.rowCount():
            self.speaker_form.removeRow(0)
        self.speaker_name_edits.clear()

        revision = document.current_revision
        speaker_ids = sorted(
            {
                segment.speaker
                for segment in revision.segments
                if segment.speaker
            }
            | set(revision.speaker_names)
        )
        for speaker_id in speaker_ids:
            edit = QLineEdit(
                revision.speaker_names.get(speaker_id, speaker_id)
            )
            edit.setAccessibleName(
                f"{self._translate('library_speaker_name')} {speaker_id}"
            )
            self.speaker_name_edits[speaker_id] = edit
            self.speaker_form.addRow(speaker_id, edit)

        self.save_speaker_names_button.setEnabled(bool(speaker_ids))

    def _save_speaker_names(self) -> None:
        current = self.document_list.currentItem()
        if current is None:
            return
        names = {
            speaker_id: edit.text().strip()
            for speaker_id, edit in self.speaker_name_edits.items()
        }
        if not names or any(not name for name in names.values()):
            return

        document_id = current.data(Qt.ItemDataRole.UserRole)
        updated = self.store.rename_speakers(document_id, names)
        self._documents_by_id[updated.id] = updated
        self._render_document(updated)
        self.detail_tabs.setCurrentIndex(0)

    def _request_document_generation(self) -> None:
        current = self.document_list.currentItem()
        if current is None:
            return
        document_id = current.data(Qt.ItemDataRole.UserRole)
        self.document_generation_requested.emit(document_id)

    def set_document_generation_busy(self, busy: bool) -> None:
        self.create_document_button.setEnabled(not busy)
        self.create_document_button.setText(
            self._translate(
                "library_creating_document"
                if busy
                else "library_create_document"
            )
        )

    def show_generated_document(
        self,
        document_id: str,
        variant_id: str,
    ) -> None:
        document = self.store.get_document(document_id)
        if document is None:
            return
        self._documents_by_id[document.id] = document
        self._render_document(document)
        for row in range(self.summary_variant_list.count()):
            item = self.summary_variant_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == variant_id:
                self.summary_variant_list.setCurrentRow(row)
                break
        self.detail_tabs.setCurrentIndex(2)
