import os
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.analyst.llm import TemplateLLM
from app.analyst.service import ask, llm_from_provider
from app.api.analyst_wiring import apply_caveats, quant_tools_with_caveats
from app.api.display import render_fact
from app.api.deps import get_analysis_service, get_current_user_id
from app.services.portfolio_analysis import PortfolioAnalysisService

router = APIRouter(prefix="/api/analyst")


class AskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")  # no user_id in the body: the user comes from the auth dependency only
    question: str = Field(max_length=2000)
    as_of: date

    @field_validator("question")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip() or "\x00" in v:
            raise ValueError("question must be non-blank text")
        return v


@router.post("/ask")
def ask_route(
    body: AskIn,
    request: Request,
    user_id: UUID = Depends(get_current_user_id),
    analysis: PortfolioAnalysisService = Depends(get_analysis_service),
):
    analysis.require_sealed(body.as_of)  # rejected even when the question needs no quant tool
    tools, caveats = quant_tools_with_caveats(analysis.analyse)
    provider = os.environ.get("AI_PROVIDER", "none")
    # The offline template renders facts through the display formatter, so its text matches the analysis API (whole percents, INR).
    try:
        llm = request.app.state.analyst_llm or (TemplateLLM(render=render_fact) if provider == "none" else llm_from_provider(provider))
    except ValueError as exc:  # unknown provider or missing AI_BASE_URL/AI_MODEL: explicit, never a 500
        raise HTTPException(status_code=503, detail={"code": "ai_provider_not_configured", "message": str(exc)}) from exc
    answer = ask(user_id, body.question, body.as_of, llm=llm, tools=tools, retriever=request.app.state.retriever, render=render_fact)
    # `answer_source` tells the reader whether the words came from the offline template or from a language model.
    return {**apply_caveats(answer, caveats()).to_dict(), "answer_source": "template" if isinstance(llm, TemplateLLM) else "llm"}
