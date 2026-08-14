from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


_BASE_SETTINGS = {
    "postgres_host": "localhost",
    "postgres_db": "db",
    "postgres_user": "user",
    "postgres_password": "pass",
    "azure_openai_endpoint": "https://example.openai.azure.com/",
    "azure_openai_api_key": "test-key",
    "azure_openai_deployment": "gpt-test",
}


@pytest.mark.parametrize(
    "field_name",
    [
        "astra_execution_timeout_seconds",
        "astra_provider_max_output_tokens",
        "astra_answer_max_chars",
        "astra_query_max_chars",
        "astra_symbol_max_chars",
        "astra_max_reasoning_iterations",
        "astra_max_cumulative_tool_calls",
    ],
)
def test_astra_settings_require_positive_values(field_name: str) -> None:
    with pytest.raises(ValidationError):
        Settings(**_BASE_SETTINGS, **{field_name: 0})


def test_astra_settings_defaults_match_operational_contract() -> None:
    settings = Settings(**_BASE_SETTINGS)

    assert settings.astra_execution_timeout_seconds == 45
    assert settings.astra_provider_max_output_tokens == 2000
    assert settings.astra_answer_max_chars == 12000
    assert settings.astra_query_max_chars == 4000
    assert settings.astra_symbol_max_chars == 20
    assert settings.astra_max_reasoning_iterations == 8
    assert settings.astra_max_cumulative_tool_calls == 20
