from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import portfolio as portfolio_routes
from app.models.enums import (
    AssetType,
    Currency,
    Exchange,
    MarketSession,
    TradeSource,
    TradeStatus,
    TransactionType,
)
from app.schemas.ai import PortfolioAnalysis, PortfolioAnalysisResponse
from app.schemas.news import CompanyNews, NewsArticle
from app.schemas.portfolio import HoldingSummary, PortfolioSummary
from app.schemas.stock import StockQuote
from app.services.ai.ai_service import AIService
from app.services.ai.tool_executor import ToolExecutor
from app.services.ai.tool_registry import ToolRegistry
from app.services.ai.workflow_service import AIWorkflowService


class StubPortfolioService:
    def get_summary(self) -> PortfolioSummary:
        return PortfolioSummary(
            total_trades=2,
            total_invested=Decimal("3500"),
            holdings=[
                HoldingSummary(
                    symbol="TCS",
                    quantity=Decimal("10"),
                    average_buy_price=Decimal("300"),
                    invested_amount=Decimal("3000"),
                ),
                HoldingSummary(
                    symbol="INFY",
                    quantity=Decimal("2"),
                    average_buy_price=Decimal("250"),
                    invested_amount=Decimal("500"),
                ),
            ],
        )


class StubMarketService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_stock_quote(self, symbol: str) -> StockQuote:
        self.calls.append(symbol)
        return StockQuote(
            symbol=symbol,
            company_name=f"{symbol} Ltd",
            current_price=123.45,
            currency="INR",
            change=1.2,
            change_percent=0.9,
            day_high=124.0,
            day_low=120.0,
            previous_close=122.25,
            market_state="REGULAR",
        )


class StubNewsService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_company_news(self, symbol: str) -> CompanyNews:
        self.calls.append(symbol)
        return CompanyNews(
            symbol=symbol,
            articles=[
                NewsArticle(
                    title=f"{symbol} update",
                    summary="Earnings and outlook",
                    source="TestWire",
                    url="https://example.com/news",
                )
            ],
        )


class ConfigurableMarketService:
    def __init__(self, fail_symbols: set[str] | None = None) -> None:
        self.fail_symbols = fail_symbols or set()
        self.calls: list[str] = []

    def get_stock_quote(self, symbol: str) -> StockQuote:
        self.calls.append(symbol)

        if symbol in self.fail_symbols:
            raise RuntimeError(f"Failed quote for {symbol}")

        return StockQuote(
            symbol=symbol,
            company_name=f"{symbol} Ltd",
            current_price=123.45,
            currency="INR",
            change=1.2,
            change_percent=0.9,
            day_high=124.0,
            day_low=120.0,
            previous_close=122.25,
            market_state="REGULAR",
        )


class ConfigurableNewsService:
    def __init__(self, fail_symbols: set[str] | None = None) -> None:
        self.fail_symbols = fail_symbols or set()
        self.calls: list[str] = []

    def get_company_news(self, symbol: str) -> CompanyNews:
        self.calls.append(symbol)

        if symbol in self.fail_symbols:
            raise RuntimeError(f"Failed news for {symbol}")

        return CompanyNews(
            symbol=symbol,
            articles=[
                NewsArticle(
                    title=f"{symbol} update",
                    summary="Earnings and outlook",
                    source="TestWire",
                    url="https://example.com/news",
                )
            ],
        )


class CaptureAIService:
    def __init__(self, response: PortfolioAnalysisResponse) -> None:
        self.captured_input = None
        self._response = response

    def analyze_portfolio(self, analysis_input):
        self.captured_input = analysis_input
        return self._response


class FakeResponsesAPI:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self._responses = responses
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


def _build_analysis_response() -> PortfolioAnalysisResponse:
    return PortfolioAnalysisResponse(
        analysis=PortfolioAnalysis(
            overview="Overall healthy portfolio",
            diversification_analysis="Moderate concentration",
            risk_assessment="Medium risk",
            strengths=["Diversified across two holdings"],
            weaknesses=["Limited sector spread"],
            recommendations=["Add defensive exposure"],
        ),
        model="test-model",
        generated_at=datetime.now(timezone.utc),
    )


def _build_workflow_with_services(
    market_service,
    news_service,
    ai_service,
) -> AIWorkflowService:
    registry = ToolRegistry(
        portfolio_service=StubPortfolioService(),
        market_service=market_service,
        news_service=news_service,
    )

    return AIWorkflowService(
        tool_registry=registry,
        ai_service=ai_service,
    )


def test_ai_workflow_service_builds_context_and_calls_ai_service() -> None:
    portfolio_service = StubPortfolioService()
    market_service = StubMarketService()
    news_service = StubNewsService()

    expected_response = _build_analysis_response()
    ai_service = CaptureAIService(expected_response)

    registry = ToolRegistry(
        portfolio_service=portfolio_service,
        market_service=market_service,
        news_service=news_service,
    )

    workflow = AIWorkflowService(
        tool_registry=registry,
        ai_service=ai_service,
    )

    result = workflow.analyze_portfolio()

    assert result == expected_response
    assert ai_service.captured_input is not None
    assert ai_service.captured_input.portfolio.total_trades == 2
    assert [quote.symbol for quote in ai_service.captured_input.quotes] == ["TCS", "INFY"]
    assert [item.symbol for item in ai_service.captured_input.news] == ["TCS", "INFY"]
    assert market_service.calls == ["TCS", "INFY"]
    assert news_service.calls == ["TCS", "INFY"]


def test_ai_workflow_service_continues_when_quote_fails_and_news_succeeds() -> None:
    market_service = ConfigurableMarketService(fail_symbols={"TCS"})
    news_service = ConfigurableNewsService()

    expected_response = _build_analysis_response()
    ai_service = CaptureAIService(expected_response)

    workflow = _build_workflow_with_services(
        market_service=market_service,
        news_service=news_service,
        ai_service=ai_service,
    )

    result = workflow.analyze_portfolio()

    assert result == expected_response
    assert ai_service.captured_input is not None
    assert [quote.symbol for quote in ai_service.captured_input.quotes] == ["INFY"]
    assert [item.symbol for item in ai_service.captured_input.news] == ["TCS", "INFY"]
    assert market_service.calls == ["TCS", "INFY"]
    assert news_service.calls == ["TCS", "INFY"]


def test_ai_workflow_service_continues_when_news_fails_and_quote_succeeds() -> None:
    market_service = ConfigurableMarketService()
    news_service = ConfigurableNewsService(fail_symbols={"INFY"})

    expected_response = _build_analysis_response()
    ai_service = CaptureAIService(expected_response)

    workflow = _build_workflow_with_services(
        market_service=market_service,
        news_service=news_service,
        ai_service=ai_service,
    )

    result = workflow.analyze_portfolio()

    assert result == expected_response
    assert ai_service.captured_input is not None
    assert [quote.symbol for quote in ai_service.captured_input.quotes] == ["TCS", "INFY"]
    assert [item.symbol for item in ai_service.captured_input.news] == ["TCS"]
    assert market_service.calls == ["TCS", "INFY"]
    assert news_service.calls == ["TCS", "INFY"]


def test_ai_workflow_service_continues_when_quotes_and_news_all_fail() -> None:
    market_service = ConfigurableMarketService(fail_symbols={"TCS", "INFY"})
    news_service = ConfigurableNewsService(fail_symbols={"TCS", "INFY"})

    expected_response = _build_analysis_response()
    ai_service = CaptureAIService(expected_response)

    workflow = _build_workflow_with_services(
        market_service=market_service,
        news_service=news_service,
        ai_service=ai_service,
    )

    result = workflow.analyze_portfolio()

    assert result == expected_response
    assert ai_service.captured_input is not None
    assert ai_service.captured_input.quotes == []
    assert ai_service.captured_input.news == []
    assert market_service.calls == ["TCS", "INFY"]
    assert news_service.calls == ["TCS", "INFY"]


def test_ai_workflow_service_mixes_success_and_failures_across_holdings() -> None:
    market_service = ConfigurableMarketService(fail_symbols={"TCS"})
    news_service = ConfigurableNewsService(fail_symbols={"TCS"})

    expected_response = _build_analysis_response()
    ai_service = CaptureAIService(expected_response)

    workflow = _build_workflow_with_services(
        market_service=market_service,
        news_service=news_service,
        ai_service=ai_service,
    )

    result = workflow.analyze_portfolio()

    assert result == expected_response
    assert ai_service.captured_input is not None
    assert [quote.symbol for quote in ai_service.captured_input.quotes] == ["INFY"]
    assert [item.symbol for item in ai_service.captured_input.news] == ["INFY"]
    assert market_service.calls == ["TCS", "INFY"]
    assert news_service.calls == ["TCS", "INFY"]


def test_ai_service_run_agent_executes_tools_and_returns_final_text() -> None:
    first_response = SimpleNamespace(
        id="resp_1",
        output=[
            SimpleNamespace(
                type="function_call",
                name="get_stock_quote",
                arguments='{"symbol":"TCS"}',
                call_id="call_1",
            )
        ],
        output_text="",
    )

    second_response = SimpleNamespace(
        id="resp_2",
        output=[],
        output_text="Final recommendation from model",
    )

    fake_responses = FakeResponsesAPI([first_response, second_response])
    fake_client = SimpleNamespace(responses=fake_responses)
    fake_settings = SimpleNamespace(azure_openai_deployment="test-deployment")

    ai_service = object.__new__(AIService)
    ai_service._client = fake_client
    ai_service._settings = fake_settings

    portfolio_tool = SimpleNamespace(get_portfolio_summary=lambda: {"total_trades": 2})
    market_tool = SimpleNamespace(get_stock_quote=lambda symbol: {"symbol": symbol, "price": 100})
    news_tool = SimpleNamespace(get_company_news=lambda symbol: {"symbol": symbol, "articles": []})

    executor = ToolExecutor(
        SimpleNamespace(
            portfolio=portfolio_tool,
            market=market_tool,
            news=news_tool,
        )
    )

    final_text = ai_service.run_agent(
        "Analyze my portfolio",
        executor,
    )

    assert final_text == "Final recommendation from model"
    assert len(fake_responses.calls) == 2

    initial_call = fake_responses.calls[0]
    assert initial_call["input"] == "Analyze my portfolio"

    followup_call = fake_responses.calls[1]
    assert followup_call["previous_response_id"] == "resp_1"
    assert followup_call["input"] == [
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": '{"symbol": "TCS", "price": 100}',
        }
    ]


def test_portfolio_analysis_endpoint_returns_expected_response() -> None:
    app = FastAPI()
    app.include_router(portfolio_routes.router, prefix="/portfolio")

    response_payload = _build_analysis_response()

    class StubWorkflow:
        def analyze_portfolio(self) -> PortfolioAnalysisResponse:
            return response_payload

    app.dependency_overrides[portfolio_routes.get_ai_workflow_service] = lambda: StubWorkflow()

    client = TestClient(app)

    response = client.get("/portfolio/analysis")

    assert response.status_code == 200
    body = response.json()
    assert body["analysis"]["overview"] == "Overall healthy portfolio"
    assert body["model"] == "test-model"
    assert "generated_at" in body

    app.dependency_overrides.clear()
