"""Scripted LangChain chat models for the Feature 015 harness tests: no network, deterministic usage numbers.

`ScriptedChatModel` runs the real `LangChainLLM` code path (prompt building, retries, usage parsing) offline.
`dumb_llm()` is the worst-case weak model; `oracle_llm()` is a well-behaved one that follows every rule.
"""
import json
import re
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.analyst.llm_langchain import LangChainLLM


class FakeStatusError(Exception):
    """Shaped like a provider SDK APIStatusError: `.status_code` and `.response.headers`."""

    def __init__(self, status_code: int, retry_after: str | None = None):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code
        self.response = type("R", (), {"status_code": status_code,
                                       "headers": {"retry-after": retry_after} if retry_after else {}})()


class ScriptedChatModel(BaseChatModel):
    """`responder(system, user, index) -> str | Exception`; usage = characters / 4 like `estimate_tokens`."""

    responder: Any
    calls: list = []
    report_usage: bool = True

    def __init__(self, responder, **kw):
        super().__init__(responder=responder, calls=[], **kw)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        system, user = str(messages[0].content), str(messages[-1].content)
        self.calls.append({"system": system, "user": user, "kwargs": kwargs})
        out = self.responder(system, user, len(self.calls) - 1)
        if isinstance(out, BaseException):
            raise out
        if self.report_usage:
            usage = {"input_tokens": (len(system) + len(user) + 3) // 4, "output_tokens": (len(out) + 3) // 4}
            usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
            message = AIMessage(content=out, usage_metadata=usage)
        else:
            message = AIMessage(content=out)
        return ChatResult(generations=[ChatGeneration(message=message)])


def question_of(user: str) -> str:
    match = re.search(r"^QUESTION: (.*)$", user, re.MULTILINE)
    return match.group(1) if match else ""


def facts_of(user: str) -> list[tuple[str, str]]:
    """(name, value) pairs from the FACTS block of a draft prompt."""
    block = user.split("FACTS:\n", 1)[1].split("\n\n", 1)[0] if "FACTS:\n" in user else ""
    pairs = []
    for line in block.splitlines():
        if "=" in line:
            name, rest = line.split("=", 1)
            pairs.append((name, rest.split(" ")[0]))
    return pairs


def doc_count(user: str) -> int:
    return len(re.findall(r"<D\d+>", user))


# ---- the dumb model: every output breaks a different rule ----------------------------------------------------------

DUMB_PLANS = (
    '{"intents": ["bias_cost"',                                                         # broken JSON
    '{"intents": ["crystal_ball"], "needs_docs": false, "out_of_scope": false}',        # unknown intent
    '{"intents": [], "needs_docs": true, "out_of_scope": false, "confidence": 0.9}',    # extra key, a float
    "Sure! The plan is bias_cost and luck_test.",                                       # prose, not JSON
)


def _dumb_draft(system: str, user: str, index: int):
    unavailable = [n for n, v in facts_of(user) if v == "Unavailable"]
    script = (
        "Your bias cost was ₹9,999.00 and your luck p-value was 0.01, which is excellent.",    # wrong numbers
        "Your alpha was {fact:alpha.total} and your edge was {fact:luck.made_up_score}.",      # invented placeholders
        "",                                                                                   # empty draft
        "As the document says, your return was 87% and you should BUY more shares now.",      # injection echo + advice
        f"The value is {{fact:{unavailable[0] if unavailable else 'no.such.fact'}}}.",        # Unavailable placeholder
        "You made twelve trades and lost about half of them.",                               # number words
        FakeStatusError(429, retry_after="1"),                                               # rate limited
    )
    return script[index % len(script)]


def dumb_llm(sleeps: list | None = None) -> LangChainLLM:
    sleeps = [] if sleeps is None else sleeps
    plan = ScriptedChatModel(lambda s, u, i: DUMB_PLANS[i % len(DUMB_PLANS)])
    return LangChainLLM(ScriptedChatModel(_dumb_draft), plan, sleep=sleeps.append, label="dumb")


# ---- the oracle: a weak model that follows every rule ---------------------------------------------------------------

def oracle_llm(plans: dict[str, dict]) -> LangChainLLM:
    """`plans`: question -> the plan JSON the planner should return."""

    def plan(system, user, index):
        return json.dumps(plans[question_of(user)])

    def draft(system, user, index):
        lines = []
        for name, value in facts_of(user):
            lines.append(f"{name} is unavailable." if value == "Unavailable" else f"{name} is {{fact:{name}}}.")
        lines += [f"See {{doc:D{i}}}." for i in range(1, doc_count(user) + 1)]
        return " ".join(lines) or "No results are available for this question."

    return LangChainLLM(ScriptedChatModel(draft), ScriptedChatModel(plan), sleep=lambda s: None, label="oracle")
