from datetime import datetime
from pydantic import BaseModel, ConfigDict


class PortfolioAnalysis(BaseModel):
    overview: str
    diversification_analysis: str
    risk_assessment: str

    strengths: list[str]
    weaknesses: list[str]
    recommendations: list[str]

    model_config = ConfigDict(from_attributes=True)


class PortfolioAnalysisResponse(BaseModel):
    analysis: PortfolioAnalysis

    model: str

    generated_at: datetime

    model_config = ConfigDict(from_attributes=True)