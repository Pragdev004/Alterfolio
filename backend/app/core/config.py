from functools import lru_cache
from os import getenv

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()


class Settings(BaseModel):
    app_name: str = Field(default="Alterfolio API")
    app_version: str = Field(default="0.1.0")
    debug: bool = Field(default=False)
    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/alterfolio"
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        app_name=getenv("APP_NAME", "Alterfolio API"),
        app_version=getenv("APP_VERSION", "0.1.0"),
        debug=getenv("DEBUG", "false").lower() == "true",
        environment=getenv("ENVIRONMENT", "development"),
        log_level=getenv("LOG_LEVEL", "INFO"),
        database_url=getenv(
            "DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@localhost:5432/alterfolio",
        ),
    )