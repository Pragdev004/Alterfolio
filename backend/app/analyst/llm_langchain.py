"""Provider-agnostic chat adapter (Feature 015) via LangChain `init_chat_model`. Used only when AI_PROVIDER=langchain.

The model only routes (a JSON plan the harness validates) and writes prose with placeholders; it never chooses tools,
tool arguments or numbers. Retries are bounded and explicit; every failure is an `AnalystLLMError`, never an answer.
"""

import hashlib
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from decimal import ROUND_CEILING, Decimal, InvalidOperation

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage

from app.analyst.harness import (DRAFT_MAX_TOKENS, DRAFT_SYSTEM, MAX_INPUT_TOKENS, PLAN_MAX_TOKENS, PLAN_SYSTEM,
                                 draft_prompt, estimate_tokens, plan_prompt, select_passages, strip_reasoning)
from app.analyst.llm import AnalystLLMError
from app.analyst.settings import ai_env
from app.analyst.types import Draft, Fact, Passage, Usage

MAX_BACKOFF_SECONDS = 8
# One (draft, plan) chat-model pair per provider/model and client settings: the API builds an LLM per request, the
# clients (connection pools) are reused. The key holds a digest of the API key, never the key itself.
_MODELS: dict[tuple, tuple] = {}
_MODELS_LOCK = threading.Lock()


def clear_model_cache() -> None:
    with _MODELS_LOCK:
        _MODELS.clear()
_TRANSIENT_NAMES = {"APITimeoutError", "APIConnectionError", "ReadTimeout", "ConnectTimeout", "TimeoutException",
                    "ConnectError", "RemoteProtocolError"}


def _status(exc: BaseException) -> int | None:
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int):
        status = getattr(getattr(exc, "response", None), "status_code", None)
    return status if isinstance(status, int) else None


def _transient(exc: BaseException) -> bool:
    status = _status(exc)
    if status is not None:
        return status == 429 or 500 <= status <= 599
    return type(exc).__name__ in _TRANSIENT_NAMES or isinstance(exc, (TimeoutError, ConnectionError))


def _backoff(exc: BaseException, attempt: int) -> int:
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    try:
        after = Decimal(str(headers.get("retry-after", "")))
        if after.is_finite() and after >= 0:
            return min(int(after.to_integral_value(rounding=ROUND_CEILING)), MAX_BACKOFF_SECONDS)
    except (InvalidOperation, AttributeError):
        pass
    return min(1 << attempt, MAX_BACKOFF_SECONDS)


def _int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None:
        return default
    if not raw.isdigit():
        raise ValueError(f"{name} must be a whole number, got {raw!r}")
    return int(raw)


class LangChainLLM:
    """`AnalystLLM` plus a `plan()` call. `fallback_to_template` tells the graph to use the deterministic template when
    the model's drafts fail (docs/plans/015 D9); `token_budget` caps input+output tokens per question."""

    fallback_to_template = True

    def __init__(self, draft_model, plan_model=None, *, max_retries: int = 2, token_budget: int = 4000,
                 sleep: Callable[[int], object] = time.sleep, label: str = "langchain") -> None:
        self._draft_model = draft_model
        self._plan_model = plan_model if plan_model is not None else draft_model
        self._max_retries = max_retries
        self.token_budget = token_budget
        self._sleep = sleep
        self.label = label

    def __repr__(self) -> str:  # never the key or the client
        return f"LangChainLLM({self.label!r})"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, *, sleep: Callable[[int], object] = time.sleep) -> "LangChainLLM":
        env = ai_env() if env is None else env
        model = env.get("AI_MODEL", "")
        provider, _, name = model.partition(":")
        if not provider or not name:
            raise ValueError("AI_PROVIDER=langchain requires AI_MODEL=<provider>:<model>, e.g. groq:llama-3.1-8b-instant")
        kwargs: dict = {"temperature": 0, "timeout": _int(env, "AI_TIMEOUT_SECONDS", 30), "max_retries": 0}
        key = env.get("AI_API_KEY") or env.get(f"{provider.upper()}_API_KEY")
        if key:
            kwargs["api_key"] = key
        if env.get("AI_BASE_URL"):
            kwargs["base_url"] = env["AI_BASE_URL"]
        effort = env.get("AI_REASONING_EFFORT")
        if effort:
            kwargs["reasoning_effort"] = effort
            if provider == "groq" and effort != "none":
                kwargs["reasoning_format"] = "hidden"
        json_mode = env.get("AI_JSON_MODE", "1") != "0"
        digest = hashlib.sha256(key.encode()).hexdigest()[:16] if key else None
        cache_key = (provider, name, kwargs.get("base_url"), digest, kwargs["timeout"], effort, json_mode)
        with _MODELS_LOCK:
            if cache_key not in _MODELS:
                try:
                    draft = init_chat_model(model, max_tokens=DRAFT_MAX_TOKENS, **kwargs)
                    plan = init_chat_model(model, max_tokens=PLAN_MAX_TOKENS, **kwargs)
                except (ImportError, ValueError) as exc:
                    raise ValueError(f"cannot build chat model {model!r}: {type(exc).__name__}") from exc
                if json_mode:
                    plan = plan.bind(response_format={"type": "json_object"})
                _MODELS[cache_key] = (draft, plan)
            draft, plan = _MODELS[cache_key]
        return cls(draft, plan, max_retries=_int(env, "AI_MAX_RETRIES", 2),
                   token_budget=_int(env, "AI_TOKEN_BUDGET", 4000), sleep=sleep, label=model)

    def _call(self, model, step: str, system: str, user: str) -> tuple[str, Usage]:
        estimate = estimate_tokens(system) + estimate_tokens(user)
        if estimate > MAX_INPUT_TOKENS:
            raise AnalystLLMError(f"{step} prompt is about {estimate} tokens, over the {MAX_INPUT_TOKENS} input cap")
        messages = [SystemMessage(system), HumanMessage(user)]
        for attempt in range(self._max_retries + 1):
            try:
                reply = model.invoke(messages)
                break
            except Exception as exc:  # provider SDKs share no base class; each is classified, then re-raised as ours
                if attempt < self._max_retries and _transient(exc):
                    self._sleep(_backoff(exc, attempt))
                    continue
                status = _status(exc)
                detail = f" (HTTP {status})" if status is not None else ""
                # type and status only: provider text can name the account and reaches answer provenance
                raise AnalystLLMError(f"{step} call failed after {attempt + 1} tries: {type(exc).__name__}{detail}")                     from exc
        content = reply.content
        if isinstance(content, list):  # some providers return content blocks
            content = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
        if not isinstance(content, str):
            raise AnalystLLMError(f"{step} reply has no text")
        text = strip_reasoning(content)
        meta = getattr(reply, "usage_metadata", None) or {}
        tin, tout = meta.get("input_tokens"), meta.get("output_tokens")
        if isinstance(tin, int) and isinstance(tout, int):
            return text, Usage(step, tin, tout)
        return text, Usage(step, estimate, estimate_tokens(content), estimated=True)

    def plan(self, question: str) -> tuple[str, tuple[Usage, ...]]:
        """The raw plan text (validated by `harness.parse_plan`, not here) and its usage."""
        text, usage = self._call(self._plan_model, "plan", PLAN_SYSTEM, plan_prompt(question))
        return text, (usage,)

    def draft(self, question: str, facts: Sequence[Fact], passages: Sequence[Passage],
              errors: Sequence[str]) -> Draft:
        user = draft_prompt(question, facts, select_passages(passages), errors)
        text, usage = self._call(self._draft_model, "draft", DRAFT_SYSTEM, user)
        return Draft(text, (), (usage,))
