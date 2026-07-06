"""Тесты реестра провайдеров (ProviderDescriptor / PROVIDER_REGISTRY)."""

from app.llm import (
    ProviderType,
    PROVIDER_REGISTRY,
    PROVIDER_NAMES,
    get_provider_descriptor,
    requires_api_key,
)


def test_registry_covers_all_provider_types():
    for ptype in ProviderType:
        assert ptype.value in PROVIDER_REGISTRY, f"нет дескриптора для {ptype.value}"


def test_descriptor_fields():
    d = get_provider_descriptor("openrouter")
    assert d.id == "openrouter"
    assert d.needs_api_key is True
    assert d.needs_base_url is False
    assert d.api_key_field == "openrouter_api_key"
    assert d.model_field == "openrouter_model"
    assert d.key_placeholder == "sk-or-..."


def test_no_key_providers():
    assert get_provider_descriptor("ollama").needs_api_key is False
    assert get_provider_descriptor("mindtype_cloud").needs_api_key is False
    assert get_provider_descriptor("ollama").needs_base_url is True


def test_requires_api_key_uses_registry():
    assert requires_api_key(ProviderType.OPENAI) is True
    assert requires_api_key(ProviderType.OLLAMA) is False
    assert requires_api_key(ProviderType.MINDTYPE_CLOUD) is False


def test_provider_names_derived_from_registry():
    # PROVIDER_NAMES должен покрывать все типы и совпадать с label'ами реестра
    for ptype in ProviderType:
        assert PROVIDER_NAMES[ptype] == PROVIDER_REGISTRY[ptype.value].label


def test_unknown_descriptor_is_none():
    assert get_provider_descriptor("does-not-exist") is None
