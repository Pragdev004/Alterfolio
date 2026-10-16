"""OpenAI-compatible chat adapter (Ollama or any local server). Used only when AI_PROVIDER=openai_compatible.

The model is asked for JSON `{"text": ..., "claims": [{"value": ..., "source": ...}]}`; whatever it returns is still
verified by number_check. Tests never construct a real client.
"""

import json
import os
from collections.abc import Sequence

import httpx

from app.analyst.llm import AnalystLLMError, fact_line
from app.analyst.types import Claim, Draft, Fact, Passage

_SYSTEM = (
    "You explain structured portfolio results. Use ONLY the facts and passages given. Never compute, round, convert or "
    "estimate a number. Every number in your text must be copied exactly from a fact value (claim source = fact name) "
    "or from a cited passage (claim source = chunk id). Reply with JSON only: "
    '{"text": string, "claims": [{"value": string, "source": string}]}. Write no BUY/SELL advice.'
)


class OpenAICompatibleLLM:
    def __init__(self, base_url: str, model: str, *, api_key: str | None = None, timeout_seconds: int = 60,
                 client: "httpx.Client | None" = None) -> None:
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._model = model
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = client or httpx.Client(timeout=timeout_seconds)

    @classmethod
    def from_env(cls) -> "OpenAICompatibleLLM":
        base, model = os.environ.get("AI_BASE_URL"), os.environ.get("AI_MODEL")
        if not base or not model:
            raise ValueError("AI_PROVIDER=openai_compatible requires AI_BASE_URL and AI_MODEL")
        return cls(base, model, api_key=os.environ.get("AI_API_KEY"))

    def draft(self, question: str, facts: Sequence[Fact], passages: Sequence[Passage],
              errors: Sequence[str]) -> Draft:
        user = {
            "question": question,
            "facts": [{"name": f.name, "line": fact_line(f)} for f in facts],
            "passages": [{"chunk_id": p.chunk_id, "text": p.text} for p in passages],
            "fix_these_errors": list(errors),
        }
        body = {"model": self._model, "temperature": 0,
                "messages": [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": json.dumps(user)}]}
        try:
            response = self._client.post(self._url, json=body, headers=self._headers)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content, parse_float=str, parse_int=str)
            claims = tuple(Claim(str(c["value"]), str(c["source"])) for c in parsed.get("claims", []))
            return Draft(str(parsed["text"]), claims)
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
            raise AnalystLLMError(f"{type(exc).__name__}: {exc}") from exc
