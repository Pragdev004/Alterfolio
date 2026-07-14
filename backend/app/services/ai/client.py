from functools import lru_cache

from openai import OpenAI

from app.core.config import get_settings


@lru_cache(maxsize=1)
def get_ai_client() -> OpenAI:
    """
    Returns a singleton Azure AI Foundry client.
    """
    settings = get_settings()

    return OpenAI(
        api_key=settings.azure_openai_api_key,
        base_url=f"{settings.azure_openai_endpoint}/openai/v1/",
    )