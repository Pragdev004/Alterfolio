from __future__ import annotations

from app.schemas.portfolio import PortfolioSummary


SYSTEM_PROMPT = """
You are Astra, an AI investment copilot.

Your purpose is to analyze investment portfolios objectively.

Rules:
- Never fabricate information.
- Only use the supplied portfolio data.
- If information is missing, clearly state that.
- Keep responses concise.
- Focus on actionable insights.
"""


def build_portfolio_analysis_prompt(
    portfolio: PortfolioSummary,
) -> str:
    return f"""
Analyze the following investment portfolio.

Portfolio:

{portfolio.model_dump_json(indent=2)}

Return:

1. Portfolio Overview
2. Diversification Analysis
3. Risk Assessment
4. Strengths
5. Weaknesses
6. Three Actionable Recommendations
"""