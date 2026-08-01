from app.config import _default_config
from app.provider_catalog import visible_summary_providers


def test_new_install_uses_mindtype_cloud_for_generated_documents():
    defaults = _default_config()

    assert defaults["use_mindtype_cloud"] is True
    assert defaults["llm_provider"] == "mindtype_cloud"


def test_cloud_config_only_offers_mindtype_cloud_in_ordinary_settings():
    assert visible_summary_providers("mindtype_cloud") == (
        ("MindType Cloud", "mindtype_cloud"),
    )


def test_known_legacy_config_keeps_only_its_selected_provider_for_migration():
    assert visible_summary_providers("openrouter") == (
        ("MindType Cloud", "mindtype_cloud"),
        ("OpenRouter (Legacy)", "openrouter"),
    )


def test_unknown_legacy_provider_fails_closed_to_cloud():
    assert visible_summary_providers("arbitrary_remote") == (
        ("MindType Cloud", "mindtype_cloud"),
    )


def test_explicit_legacy_config_loads_without_changing_route_or_values(
    tmp_path, monkeypatch
):
    import json

    import app.config as config_module

    config_dir = tmp_path / "MindType"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "llm_provider": "openrouter",
                "use_mindtype_cloud": False,
                "openrouter_api_key": "key_in_keyring",
                "openrouter_model": "example/legacy-model",
                "transcriber_backend": "openrouter",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(config_module, "keyring", None)

    loaded = config_module.ConfigManager().config

    assert loaded["llm_provider"] == "openrouter"
    assert loaded["use_mindtype_cloud"] is False
    assert loaded["openrouter_api_key"] == "key_in_keyring"
    assert loaded["openrouter_model"] == "example/legacy-model"
    assert loaded["transcriber_backend"] == "openrouter"
