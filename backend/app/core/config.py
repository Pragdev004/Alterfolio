from functools import lru_cache
from urllib.parse import quote_plus
from uuid import UUID

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DEV_USER_ID = UUID("11111111-1111-4111-8111-111111111111")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="Alterfolio API")
    app_version: str = Field(default="0.1.0")
    debug: bool = Field(default=False)
    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")
    default_dev_user_id: UUID = Field(default=DEFAULT_DEV_USER_ID)

    postgres_host: str
    postgres_port: int = 5432
    postgres_db: str
    postgres_user: str
    postgres_password: str

    # Azure AI Foundry
    azure_openai_endpoint: str
    azure_openai_api_key: str
    azure_openai_deployment: str
    azure_openai_api_version: str = "v1"

    # ASTRA limits
    astra_execution_timeout_seconds: int = Field(default=45, gt=0)
    astra_provider_max_output_tokens: int = Field(default=2000, gt=0)
    astra_answer_max_chars: int = Field(default=12000, gt=0)
    astra_query_max_chars: int = Field(default=4000, gt=0)
    astra_symbol_max_chars: int = Field(default=20, gt=0)
    astra_max_reasoning_iterations: int = Field(default=8, gt=0)
    astra_max_cumulative_tool_calls: int = Field(default=20, gt=0)

    @computed_field
    @property
    def database_url(self) -> str:
        password = quote_plus(self.postgres_password)
        return (
            f"postgresql+psycopg://"
            f"{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}"
            f"/{self.postgres_db}?sslmode=require"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
