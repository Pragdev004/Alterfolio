from pydantic import BaseModel
from openai import OpenAI

from app.core.config import get_settings

settings = get_settings()

client = OpenAI(
    api_key=settings.azure_openai_api_key,
    base_url=f"{settings.azure_openai_endpoint}/openai/v1/",
)


class MathResponse(BaseModel):
    answer: int
    explanation: str


response = client.responses.parse(
    model=settings.azure_openai_deployment,
    input="What is 25 + 17?",
    text_format=MathResponse,
)

print(response.output_parsed)