from app.core.config import Settings


def test_allowed_origins_accepts_comma_separated_environment_value(monkeypatch) -> None:
    monkeypatch.setenv(
        "ALLOWED_ORIGINS",
        "http://localhost:3000, http://127.0.0.1:3000",
    )

    settings = Settings(_env_file=None)

    assert settings.allowed_origins == [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


def test_model_request_timeout_and_retries_can_be_configured(monkeypatch) -> None:
    monkeypatch.setenv("MODEL_REQUEST_TIMEOUT_SECONDS", "420")
    monkeypatch.setenv("MODEL_REQUEST_MAX_RETRIES", "3")
    monkeypatch.setenv("VISUAL_ENRICHMENT_MAX_NEW_ASSETS_PER_JOB", "12")

    settings = Settings(_env_file=None)

    assert settings.model_request_timeout_seconds == 420
    assert settings.model_request_max_retries == 3
    assert settings.visual_enrichment_max_new_assets_per_job == 12


def test_application_timezone_defaults_to_china_standard_time() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_timezone == "Asia/Shanghai"
