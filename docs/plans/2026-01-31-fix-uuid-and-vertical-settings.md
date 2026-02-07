# Fix UUID Error & Vertical Settings Layout

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the "validation_error: Invalid UUID" summarization error and redesign the Settings tab from cramped two-column to a clean vertical scrollable layout.

**Architecture:** Two independent fixes. Task 1 replaces the invalid hex-string meeting_id with a proper UUID. Task 2 replaces `TwoColumnLayout` in `_build_additional_tab()` with `ScrollableContent` containing full-width `SectionBox` sections stacked vertically.

**Tech Stack:** Python, PyQt6, uuid module, existing layout components (ScrollableContent, SectionBox, FormLayout)

---

### Task 1: Fix Invalid UUID in Summarizer

**Files:**
- Modify: `app/summarizer.py:1,563`

**Step 1: Fix meeting_id generation**

In `app/summarizer.py`, line 1 add `uuid` to imports, and line 563 replace the hex-string generation with proper UUID:

Line 1 - add import:
```python
import uuid
```

Line 563 - replace:
```python
# OLD:
meeting_id = hashlib.md5(transcript[:500].encode()).hexdigest()[:16]

# NEW:
meeting_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, transcript[:500]))
```

`uuid.uuid5` creates a deterministic UUID from the transcript content, so the same transcript always produces the same meeting_id (important for credit grouping).

**Step 2: Verify syntax**

Run: `cd "D:\Projects\mindtype\mindtype-app" && python -c "import py_compile; py_compile.compile('app/summarizer.py', doraise=True)"`
Expected: No output (success)

**Step 3: Commit**

```bash
git add app/summarizer.py
git commit -m "fix: use valid UUID for MindType Cloud meeting_id

The meeting_id was generated as a 16-char hex string which failed
backend UUID validation. Now uses uuid5 for deterministic UUIDs."
```

---

### Task 2: Redesign Settings Tab to Vertical Scrollable Layout

**Files:**
- Modify: `app/main.py:1292-1618` (method `_build_additional_tab`)

**Step 1: Replace two-column layout with ScrollableContent**

Rewrite `_build_additional_tab()` in `app/main.py` (lines 1292-1618). The new structure:

```python
def _build_additional_tab(self) -> QWidget:
    """Построить вкладку дополнительных настроек."""
    tab = QWidget()
    tab_layout = QVBoxLayout(tab)
    tab_layout.setContentsMargins(0, 0, 0, 0)
    tab_layout.setSpacing(0)

    # Скроллируемый контейнер
    scroll = ScrollableContent(horizontal_scroll=False)

    # === Секция AI Provider ===
    ai_section = SectionBox(self._t("ai_provider"), label_width=140)
    self.ai_section_label = ai_section

    # Выбор провайдера
    self.provider_combo = QComboBox()
    self.provider_combo.setMinimumWidth(200)
    self.provider_combo.addItem("MindType Cloud", "mindtype_cloud")
    self.provider_combo.addItem("OpenAI", "openai")
    self.provider_combo.addItem("Claude (Anthropic)", "anthropic")
    self.provider_combo.addItem("Gemini (Google)", "gemini")
    self.provider_combo.addItem("Ollama (Local)", "ollama")
    self.provider_combo.addItem("OpenRouter (Private)", "openrouter")
    self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
    self._provider_row = ai_section.form.add_row(self._t("llm_provider"), self.provider_combo)
    self.provider_label = self._provider_row.label

    # API ключ
    self.api_key_edit = QLineEdit()
    self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
    self.api_key_edit.setPlaceholderText("sk-...")
    self.api_key_edit.setObjectName("monoInput")
    self._api_key_row = ai_section.form.add_row(self._t("api_key"), self.api_key_edit)
    self.api_key_label = self._api_key_row.label

    # Base URL (для Ollama)
    self.base_url_edit = QLineEdit()
    self.base_url_edit.setPlaceholderText("http://localhost:11434")
    self.base_url_edit.setObjectName("monoInput")
    self._base_url_row = ai_section.form.add_row(self._t("base_url"), self.base_url_edit)
    self.base_url_label = self._base_url_row.label

    # Выбор модели с поиском
    model_widget = QWidget()
    model_layout = QHBoxLayout(model_widget)
    model_layout.setContentsMargins(0, 0, 0, 0)
    model_layout.setSpacing(SPACING["sm"])
    self.model_combo = QComboBox()
    self.model_combo.setEditable(True)
    self.model_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    self.model_combo.lineEdit().setPlaceholderText(self._t("search_model"))
    self.model_combo.setObjectName("wideCombo")
    self.model_combo.addItem(self._t("select_model"), "")
    self.refresh_models_btn = QPushButton(self._t("refresh_models"))
    self.refresh_models_btn.setObjectName("smallButton")
    self.refresh_models_btn.clicked.connect(self._on_refresh_models)
    model_layout.addWidget(self.model_combo, stretch=1)
    model_layout.addWidget(self.refresh_models_btn)
    self._model_select_row = ai_section.form.add_row(self._t("openrouter_model"), model_widget)
    self.model_select_label = self._model_select_row.label

    # Reasoning mode
    reasoning_widget = QWidget()
    reasoning_layout = QHBoxLayout(reasoning_widget)
    reasoning_layout.setContentsMargins(0, 0, 0, 0)
    reasoning_layout.setSpacing(SPACING["sm"])
    self.reasoning_checkbox = QCheckBox(self._t("reasoning_mode"))
    self.reasoning_checkbox.setToolTip(self._t("reasoning_tooltip"))
    self.reasoning_checkbox.stateChanged.connect(self._on_reasoning_changed)
    self.effort_label = QLabel(self._t("reasoning_effort"))
    self.effort_combo = QComboBox()
    self.effort_combo.addItem(self._t("effort_low"), "low")
    self.effort_combo.addItem(self._t("effort_medium"), "medium")
    self.effort_combo.addItem(self._t("effort_high"), "high")
    self.effort_combo.setCurrentIndex(1)
    self.effort_combo.setObjectName("compactCombo")
    self.effort_combo.currentIndexChanged.connect(self._on_effort_changed)
    reasoning_layout.addWidget(self.reasoning_checkbox)
    reasoning_layout.addWidget(self.effort_label)
    reasoning_layout.addWidget(self.effort_combo)
    reasoning_layout.addStretch()
    ai_section.form.add_widget(reasoning_widget)

    # Загрузка сохранённых настроек провайдера
    cfg = self.config.config
    saved_provider = cfg.get("llm_provider", "openrouter")
    provider_idx = self.provider_combo.findData(saved_provider)
    if provider_idx >= 0:
        self.provider_combo.setCurrentIndex(provider_idx)
    self._load_provider_settings(saved_provider)
    self.reasoning_checkbox.setChecked(cfg.get("llm_reasoning_enabled", True))
    effort = cfg.get("llm_reasoning_effort", "medium")
    effort_idx = self.effort_combo.findData(effort)
    if effort_idx >= 0:
        self.effort_combo.setCurrentIndex(effort_idx)
    self.api_key_edit.textChanged.connect(self._on_api_key_changed)
    self.base_url_edit.textChanged.connect(self._on_base_url_changed)
    self.model_combo.currentTextChanged.connect(self._on_model_changed)
    self._update_provider_fields()

    scroll.content_layout.addWidget(ai_section)

    # === Секция Performance ===
    perf_section = SectionBox(self._t("performance_section"), label_width=140)
    self.perf_section_label = perf_section

    # VAD Filter
    self.vad_toggle = QCheckBox()
    self.vad_toggle.setChecked(True)
    self._vad_row = perf_section.form.add_row(self._t("vad_filter"), self.vad_toggle)
    self.vad_label = self._vad_row.label

    # Размер луча
    beam_widget = QWidget()
    beam_layout = QHBoxLayout(beam_widget)
    beam_layout.setContentsMargins(0, 0, 0, 0)
    beam_layout.setSpacing(SPACING["sm"])
    self.beam_slider = QSlider(Qt.Orientation.Horizontal)
    self.beam_slider.setRange(1, 10)
    self.beam_slider.setValue(5)
    self.beam_value_label = QLabel("5")
    self.beam_value_label.setFixedWidth(30)
    beam_layout.addWidget(self.beam_slider)
    beam_layout.addWidget(self.beam_value_label)
    self._beam_row = perf_section.form.add_row(self._t("beam_size"), beam_widget)
    self.beam_label = self._beam_row.label

    # Квантование
    self.compute_box = QComboBox()
    for ct in ["auto", "int8", "int8_float16", "float16", "float32"]:
        self.compute_box.addItem(ct)
    self._quant_row = perf_section.form.add_row(self._t("quantization"), self.compute_box)
    self.quant_label = self._quant_row.label

    # Устройство
    self.accel_box = QComboBox()
    for mode in ["auto", "npu", "gpu", "cpu"]:
        self.accel_box.addItem(mode)
    self._accel_row = perf_section.form.add_row(self._t("device"), self.accel_box)
    self.accel_label = self._accel_row.label

    # Статус NPU
    if has_npu():
        npu_status = QLabel(f"[OK] {self._t('npu_detected')} ({detect_available_providers()[0]})")
        npu_status.setObjectName("smallBold")
        perf_section.form.add_widget(npu_status)

    # Бэкенд транскрипции
    self.backend_box = QComboBox()
    self.backend_box.addItem(self._t("backend_whispercpp"), "whisper_cpp")
    self.backend_box.addItem(self._t("backend_faster_whisper"), "faster_whisper")
    self.backend_box.addItem(self._t("backend_onnx"), "onnx")
    self._backend_row = perf_section.form.add_row(self._t("whisper_backend"), self.backend_box)
    self.backend_label = self._backend_row.label

    # Модель
    self.model_box = QComboBox()
    self._populate_model_combo()
    self._model_row = perf_section.form.add_row(self._t("model"), self.model_box)
    self.model_label = self._model_row.label

    # Предупреждение о distil
    self.distil_warning = QLabel(self._t("distil_en_only"))
    self.distil_warning.setObjectName("warning")
    perf_section.form.add_widget(self.distil_warning)

    # Кнопка скачивания модели
    self.download_btn = QPushButton(self._t("download_model"))
    self.download_btn.setObjectName("downloadButton")
    perf_section.form.add_widget(self.download_btn)

    # Прогресс скачивания
    self.download_progress = QProgressBar()
    self.download_progress.setRange(0, 100)
    self.download_progress.setValue(0)
    self.download_progress.setTextVisible(True)
    perf_section.form.add_widget(self.download_progress)

    self.download_status_label = QLabel("")
    perf_section.form.add_widget(self.download_status_label)

    # Путь модели
    self.models_path_edit = QLineEdit()
    self.models_path_edit.setText(str(self.models_dir))
    self.models_path_edit.setReadOnly(True)
    self._model_path_row = perf_section.form.add_row(self._t("model_path"), self.models_path_edit)
    self.model_path_label = self._model_path_row.label

    scroll.content_layout.addWidget(perf_section)

    # === Секция Overlay ===
    overlay_section = SectionBox(self._t("overlay_section"), label_width=140)
    self.overlay_section_label = overlay_section

    # Позиция
    self.overlay_position_box = QComboBox()
    positions = [
        ("bottom-center", "bottom_center"),
        ("top-center", "top_center"),
        ("bottom-right", "bottom_right"),
        ("bottom-left", "bottom_left"),
        ("top-right", "top_right"),
        ("top-left", "top_left"),
    ]
    for key, text_key in positions:
        self.overlay_position_box.addItem(self._t(text_key), key)
    self._position_row = overlay_section.form.add_row(self._t("position"), self.overlay_position_box)
    self.position_label = self._position_row.label

    # Отступ
    margin_widget = QWidget()
    margin_layout = QHBoxLayout(margin_widget)
    margin_layout.setContentsMargins(0, 0, 0, 0)
    margin_layout.setSpacing(SPACING["sm"])
    self.overlay_margin_slider = QSlider(Qt.Orientation.Horizontal)
    self.overlay_margin_slider.setRange(0, 100)
    self.overlay_margin_slider.setValue(20)
    self.overlay_margin_value = QLabel("20")
    self.overlay_margin_value.setFixedWidth(40)
    margin_layout.addWidget(self.overlay_margin_slider)
    margin_layout.addWidget(self.overlay_margin_value)
    self._margin_row = overlay_section.form.add_row(self._t("margin"), margin_widget)
    self.margin_label = self._margin_row.label

    # Усиление волны
    gain_widget = QWidget()
    gain_layout = QHBoxLayout(gain_widget)
    gain_layout.setContentsMargins(0, 0, 0, 0)
    gain_layout.setSpacing(SPACING["sm"])
    self.overlay_gain_slider = QSlider(Qt.Orientation.Horizontal)
    self.overlay_gain_slider.setRange(10, 100)
    self.overlay_gain_slider.setValue(15)
    self.overlay_gain_value = QLabel("1.5")
    self.overlay_gain_value.setFixedWidth(40)
    gain_layout.addWidget(self.overlay_gain_slider)
    gain_layout.addWidget(self.overlay_gain_value)
    self._wave_gain_row = overlay_section.form.add_row(self._t("wave_gain"), gain_widget)
    self.wave_gain_label = self._wave_gain_row.label

    # Прозрачность
    opacity_widget = QWidget()
    opacity_layout = QHBoxLayout(opacity_widget)
    opacity_layout.setContentsMargins(0, 0, 0, 0)
    opacity_layout.setSpacing(SPACING["sm"])
    self.overlay_opacity_slider = QSlider(Qt.Orientation.Horizontal)
    self.overlay_opacity_slider.setRange(50, 255)
    self.overlay_opacity_slider.setValue(230)
    self.overlay_preview_btn = QPushButton(self._t("preview"))
    opacity_layout.addWidget(self.overlay_opacity_slider)
    opacity_layout.addWidget(self.overlay_preview_btn)
    self._opacity_row = overlay_section.form.add_row(self._t("opacity"), opacity_widget)
    self.opacity_label = self._opacity_row.label

    scroll.content_layout.addWidget(overlay_section)

    # === Секция App ===
    app_section = SectionBox(self._t("app_section"), label_width=140)
    self.app_section_label = app_section

    # Язык интерфейса
    self.ui_lang_box = QComboBox()
    for code, name in UI_LANGUAGES.items():
        self.ui_lang_box.addItem(name, code)
    self._ui_lang_row = app_section.form.add_row(self._t("ui_language"), self.ui_lang_box)
    self.ui_lang_label = self._ui_lang_row.label

    # Версия и обновления
    update_widget = QWidget()
    update_layout = QHBoxLayout(update_widget)
    update_layout.setContentsMargins(0, 0, 0, 0)
    update_layout.setSpacing(SPACING["sm"])

    try:
        from .env import APP_VERSION
        current_ver = APP_VERSION
    except ImportError:
        current_ver = "1.0.0"

    self.update_version_label = QLabel(f"v{current_ver}")
    self.update_version_label.setObjectName("bodyBold")
    update_layout.addWidget(self.update_version_label)
    update_layout.addStretch()

    self.check_update_btn = QPushButton(self._t("check_updates"))
    self.check_update_btn.clicked.connect(self._check_for_updates)
    update_layout.addWidget(self.check_update_btn)

    self._update_row = app_section.form.add_row(self._t("current_version"), update_widget)
    self.update_label = self._update_row.label

    # Статус обновления
    self.update_status_label = QLabel("")
    self.update_status_label.setObjectName("caption")
    self.update_status_label.setVisible(False)
    app_section.form.add_widget(self.update_status_label)

    # Прогресс-бар обновления
    self.update_progress = QProgressBar()
    self.update_progress.setRange(0, 100)
    self.update_progress.setValue(0)
    self.update_progress.setVisible(False)
    app_section.form.add_widget(self.update_progress)

    # Кнопка поддержки
    self.support_btn = QPushButton("help@mindtype.space")
    self.support_btn.setObjectName("smallButton")
    self.support_btn.clicked.connect(self._on_contact_support)
    self._support_row = app_section.form.add_row(self._t("contact_support"), self.support_btn)
    self.support_label = self._support_row.label

    scroll.content_layout.addWidget(app_section)
    scroll.content_layout.addStretch()

    tab_layout.addWidget(scroll)
    return tab
```

Key changes from the current code:
1. `TwoColumnLayout` replaced with `ScrollableContent`
2. All sections stacked vertically in single column (full width)
3. Unified `label_width=140` for all sections (was 100-130, cramped)
4. `ScrollableContent` provides vertical scrollbar when content overflows
5. Zero margins on outer tab (ScrollableContent has its own 16/24/16/16 margins)
6. All widget names, signals, and attribute assignments are preserved exactly

**Step 2: Verify syntax**

Run: `cd "D:\Projects\mindtype\mindtype-app" && python -c "import py_compile; py_compile.compile('app/main.py', doraise=True)"`
Expected: No output (success)

**Step 3: Commit**

```bash
git add app/main.py
git commit -m "refactor: redesign Settings tab to vertical scrollable layout

Replace cramped two-column layout with full-width vertical sections
inside ScrollableContent. Unified label width at 140px for readability."
```

---

## Execution Checklist

- [ ] Task 1: Fix UUID (1 file, 2 line changes)
- [ ] Task 2: Vertical settings layout (1 file, method rewrite)
- [ ] Visual verification: restart app, check Settings tab scrolls and reads well
