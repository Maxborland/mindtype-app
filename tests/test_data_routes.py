from unittest.mock import patch

from app.data_routes import resolve_processing_route


def test_laptop_cloud_route_is_explicit():
    route = resolve_processing_route(
        {
            "transcriber_backend": "openrouter",
            "llm_provider": "mindtype_cloud",
            "openrouter_api_key": "key",
            "postprocessing_diarization": True,
        },
        summary_enabled=True,
        diarization_backend="auto",
    )

    assert route.audio == "OpenRouter"
    assert route.diarization == "OpenRouter"
    assert route.summary == "MindType Cloud"
    assert route.uses_cloud is True


def test_fully_local_route_is_identified():
    with patch("app.optional_features.local_diarization_available", return_value=True):
        route = resolve_processing_route(
            {
                "transcriber_backend": "whisper_cpp",
                "llm_provider": "ollama",
                "postprocessing_diarization": True,
            },
            summary_enabled=True,
            diarization_backend="local",
        )

    assert route.audio == "Local"
    assert route.diarization == "Local"
    assert route.summary == "Local"
    assert route.uses_cloud is False


def test_mindtype_cloud_default_routes_heavy_laptop_stages_to_cloud():
    route = resolve_processing_route(
        {
            "use_mindtype_cloud": True,
            "transcriber_backend": "whisper_cpp",
            "llm_provider": "mindtype_cloud",
            "postprocessing_diarization": True,
        },
        summary_enabled=True,
        diarization_backend="local",
    )

    assert route.audio == "MindType Cloud"
    assert route.diarization == "MindType Cloud"
    assert route.summary == "MindType Cloud"


def test_unavailable_auto_diarization_is_reported_as_off():
    with patch("app.optional_features.local_diarization_available", return_value=False):
        route = resolve_processing_route(
            {
                "transcriber_backend": "whisper_cpp",
                "llm_provider": "ollama",
                "openrouter_api_key": "",
                "postprocessing_diarization": True,
            },
            summary_enabled=False,
            diarization_backend="auto",
        )

    assert route.diarization == "Off"


def test_disabled_processing_stages_are_not_claimed_as_cloud():
    route = resolve_processing_route(
        {
            "transcriber_backend": "whisper_cpp",
            "llm_provider": "openrouter",
            "postprocessing_diarization": False,
        },
        summary_enabled=False,
        diarization_backend="openrouter",
    )

    assert route.diarization == "Off"
    assert route.summary == "Off"
    assert route.uses_cloud is False


def test_canonical_route_records_provider_and_model_per_enabled_stage():
    from app.data_routes import ProcessingRoute, canonical_processing_route

    route = ProcessingRoute(
        audio="OpenRouter",
        diarization="Local",
        summary="MindType Cloud",
    )

    canonical = canonical_processing_route(
        route,
        {
            "openrouter_transcribe_model": "openai/whisper-1",
            "model_size": "large-v3",
            "openrouter_diarization_model": "",
            "openrouter_model": "must-not-leak-into-cloud",
            "llm_provider": "mindtype_cloud",
        },
    )

    assert canonical == {
        "transcription": {
            "provider": "openrouter",
            "model": "openai/whisper-1",
        },
        "diarization": {
            "provider": "local",
            "model": "mfcc",
        },
        "summary": {
            "provider": "mindtype_cloud",
            "model": "auto",
        },
    }
