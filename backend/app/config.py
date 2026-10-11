from uuid import UUID

from pydantic_settings import BaseSettings, SettingsConfigDict

# The single local user (U7). Real auth later replaces the get_current_user_id dependency only.
DEFAULT_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


class Settings(BaseSettings):
    """No field is required: tests and /health run with no .env and no database."""

    model_config = SettingsConfigDict(env_prefix="ALTERFOLIO_", env_file=".env", extra="ignore")

    database_url: str | None = None
    user_id: UUID = DEFAULT_USER_ID
