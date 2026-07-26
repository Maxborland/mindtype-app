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
