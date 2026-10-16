from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.analyst.service import ask
from app.api.analyst_wiring import quant_tools_from
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
    answer = ask(user_id, body.question, body.as_of, llm=request.app.state.analyst_llm,
                 tools=quant_tools_from(analysis.analyse), retriever=request.app.state.retriever)
    return answer.to_dict()
