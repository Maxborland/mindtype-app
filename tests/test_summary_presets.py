"""
Тесты для модуля summary_presets.
"""

import pytest
from app.summary_presets import (
    PRESETS,
    DEFAULT_PRESET,
    get_preset,
    get_preset_prompts,
    get_preset_list,
    PM_SYSTEM_PROMPT,
    STUDENT_SYSTEM_PROMPT,
    GENERIC_SYSTEM_PROMPT,
)


class TestPresetsStructure:
    """Тесты структуры пресетов."""

    def test_all_presets_exist(self):
        """Проверяем наличие всех трёх пресетов."""
        assert "pm" in PRESETS
        assert "student" in PRESETS
        assert "generic" in PRESETS
        assert len(PRESETS) == 3

    def test_default_preset_exists(self):
        """Дефолтный пресет должен существовать."""
        assert DEFAULT_PRESET in PRESETS

    def test_preset_structure(self):
        """Каждый пресет должен содержать name, description, prompts."""
        for preset_id, preset in PRESETS.items():
            assert "name" in preset, f"Пресет {preset_id} не содержит name"
            assert "description" in preset, f"Пресет {preset_id} не содержит description"
            assert "prompts" in preset, f"Пресет {preset_id} не содержит prompts"
            
            # Проверяем что name и description - непустые строки
            assert isinstance(preset["name"], str) and len(preset["name"]) > 0
            assert isinstance(preset["description"], str) and len(preset["description"]) > 0

    def test_prompts_structure(self):
        """Каждый пресет должен содержать все 4 промпта."""
        required_prompts = ["system", "short", "extraction", "aggregation"]
        
        for preset_id, preset in PRESETS.items():
            prompts = preset["prompts"]
            for prompt_key in required_prompts:
                assert prompt_key in prompts, f"Пресет {preset_id} не содержит промпт {prompt_key}"
                assert isinstance(prompts[prompt_key], str), f"Промпт {prompt_key} в {preset_id} не строка"
                assert len(prompts[prompt_key]) > 0, f"Промпт {prompt_key} в {preset_id} пустой"


class TestPromptsContent:
    """Тесты содержимого промптов."""

    def test_prompts_contain_russian_instructions(self):
        """Все системные промпты должны содержать инструкцию про русский язык."""
        assert "русском" in PM_SYSTEM_PROMPT.lower() or "русский" in PM_SYSTEM_PROMPT.lower()
        assert "русском" in STUDENT_SYSTEM_PROMPT.lower() or "русский" in STUDENT_SYSTEM_PROMPT.lower()
        assert "русском" in GENERIC_SYSTEM_PROMPT.lower() or "русский" in GENERIC_SYSTEM_PROMPT.lower()

    def test_short_prompts_have_transcript_placeholder(self):
        """Short промпты должны содержать placeholder {transcript}."""
        for preset_id, preset in PRESETS.items():
            short_prompt = preset["prompts"]["short"]
            assert "{transcript}" in short_prompt, f"Short промпт {preset_id} не содержит {{transcript}}"

    def test_extraction_prompts_have_chunk_placeholder(self):
        """Extraction промпты должны содержать placeholder {chunk_text}."""
        for preset_id, preset in PRESETS.items():
            extraction_prompt = preset["prompts"]["extraction"]
            assert "{chunk_text}" in extraction_prompt, f"Extraction промпт {preset_id} не содержит {{chunk_text}}"

    def test_aggregation_prompts_have_placeholders(self):
        """Aggregation промпты должны содержать placeholders {n_chunks} и {extracted_facts}."""
        for preset_id, preset in PRESETS.items():
            agg_prompt = preset["prompts"]["aggregation"]
            assert "{n_chunks}" in agg_prompt, f"Aggregation промпт {preset_id} не содержит {{n_chunks}}"
            assert "{extracted_facts}" in agg_prompt, f"Aggregation промпт {preset_id} не содержит {{extracted_facts}}"

    def test_pm_preset_has_pm_specific_content(self):
        """PM пресет должен содержать PM-специфичные разделы."""
        pm_short = PRESETS["pm"]["prompts"]["short"]
        assert "заказчик" in pm_short.lower() or "исполнител" in pm_short.lower()
        assert "риски" in pm_short.lower() or "вопрос" in pm_short.lower()

    def test_student_preset_has_student_specific_content(self):
        """Student пресет должен содержать учебные разделы."""
        student_short = PRESETS["student"]["prompts"]["short"]
        assert "лекци" in student_short.lower()
        assert "экзамен" in student_short.lower() or "определени" in student_short.lower()

    def test_generic_preset_has_generic_content(self):
        """Generic пресет должен быть универсальным."""
        generic_short = PRESETS["generic"]["prompts"]["short"]
        assert "видео" in generic_short.lower() or "саммари" in generic_short.lower()


class TestGetPreset:
    """Тесты функции get_preset."""

    def test_get_existing_preset(self):
        """Получение существующего пресета."""
        preset = get_preset("pm")
        assert preset["name"] == "PM-ассистент"
        
        preset = get_preset("student")
        assert preset["name"] == "Студент"
        
        preset = get_preset("generic")
        assert preset["name"] == "Общее видео"

    def test_get_nonexistent_preset_returns_default(self):
        """Несуществующий пресет должен вернуть дефолтный."""
        preset = get_preset("nonexistent")
        default = get_preset(DEFAULT_PRESET)
        assert preset == default

    def test_get_preset_with_empty_string(self):
        """Пустая строка должна вернуть дефолтный пресет."""
        preset = get_preset("")
        default = get_preset(DEFAULT_PRESET)
        assert preset == default


class TestGetPresetPrompts:
    """Тесты функции get_preset_prompts."""

    def test_returns_only_prompts(self):
        """Функция должна возвращать только промпты."""
        prompts = get_preset_prompts("pm")
        assert "system" in prompts
        assert "short" in prompts
        assert "extraction" in prompts
        assert "aggregation" in prompts
        # Не должно быть name и description
        assert "name" not in prompts
        assert "description" not in prompts

    def test_prompts_are_strings(self):
        """Все промпты должны быть строками."""
        for preset_id in PRESETS:
            prompts = get_preset_prompts(preset_id)
            for key, value in prompts.items():
                assert isinstance(value, str), f"Промпт {key} в {preset_id} не строка"

    def test_nonexistent_preset_returns_default_prompts(self):
        """Несуществующий пресет должен вернуть промпты дефолтного."""
        prompts = get_preset_prompts("nonexistent")
        default_prompts = get_preset_prompts(DEFAULT_PRESET)
        assert prompts == default_prompts


class TestGetPresetList:
    """Тесты функции get_preset_list."""

    def test_returns_list(self):
        """Функция должна возвращать список."""
        result = get_preset_list()
        assert isinstance(result, list)
        assert len(result) == 3

    def test_list_item_structure(self):
        """Каждый элемент списка должен содержать id, name, description."""
        result = get_preset_list()
        for item in result:
            assert "id" in item
            assert "name" in item
            assert "description" in item
            # Не должно быть prompts
            assert "prompts" not in item

    def test_list_contains_all_presets(self):
        """Список должен содержать все пресеты."""
        result = get_preset_list()
        ids = [item["id"] for item in result]
        assert "pm" in ids
        assert "student" in ids
        assert "generic" in ids


class TestPresetIntegration:
    """Интеграционные тесты для пресетов."""

    def test_prompts_can_be_formatted(self):
        """Промпты должны корректно форматироваться с placeholder'ами."""
        for preset_id in PRESETS:
            prompts = get_preset_prompts(preset_id)
            
            # Short prompt
            try:
                formatted = prompts["short"].format(transcript="Тестовая транскрипция")
                assert "Тестовая транскрипция" in formatted
            except KeyError as e:
                pytest.fail(f"Short промпт {preset_id} содержит неизвестный placeholder: {e}")
            
            # Extraction prompt
            try:
                formatted = prompts["extraction"].format(chunk_text="Тестовый чанк")
                assert "Тестовый чанк" in formatted
            except KeyError as e:
                pytest.fail(f"Extraction промпт {preset_id} содержит неизвестный placeholder: {e}")
            
            # Aggregation prompt
            try:
                formatted = prompts["aggregation"].format(n_chunks=3, extracted_facts="Факты")
                assert "3" in formatted
                assert "Факты" in formatted
            except KeyError as e:
                pytest.fail(f"Aggregation промпт {preset_id} содержит неизвестный placeholder: {e}")

    def test_custom_prompts_override(self):
        """Тест объединения пресета с кастомными промптами."""
        preset_prompts = get_preset_prompts("pm")
        custom_prompts = {"system": "Кастомный системный промпт"}
        
        # Симулируем объединение как в коде
        merged = {**preset_prompts, **custom_prompts}
        
        # Кастомный должен перезаписать
        assert merged["system"] == "Кастомный системный промпт"
        # Остальные из пресета
        assert merged["short"] == preset_prompts["short"]
        assert merged["extraction"] == preset_prompts["extraction"]
        assert merged["aggregation"] == preset_prompts["aggregation"]
