from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.core.config import get_settings
from app.schemas.analysis import PortfolioAnalysisInput
from app.schemas.ai import PortfolioAnalysis, PortfolioAnalysisResponse
from app.services.ai.client import get_ai_client
from app.services.ai.prompts import SYSTEM_PROMPT, build_portfolio_analysis_prompt
from app.services.ai.tool_executor import ToolExecutor
from app.services.ai.tool_definitions import TOOLS

class AIService:
    """
    Astra AI service responsible for orchestrating AI requests.
    """

    def __init__(self) -> None:
        self._client = get_ai_client()
        self._settings = get_settings()

    def analyze_portfolio(
            self, 
            analysis_input: PortfolioAnalysisInput
            ) -> PortfolioAnalysisResponse:
        prompt = build_portfolio_analysis_prompt(analysis_input)

        response = self._client.responses.parse(
            model=self._settings.azure_openai_deployment,
            instructions=SYSTEM_PROMPT,
            input=prompt,
            text_format=PortfolioAnalysis,
        )

        analysis = response.output_parsed

        return PortfolioAnalysisResponse(
            analysis=analysis,
            model=self._settings.azure_openai_deployment,
            generated_at=datetime.now(timezone.utc),
        )

    def create_tool_response(self, user_input: str):
        return self._client.responses.create(
            model=self._settings.azure_openai_deployment,
            input=user_input,
            tools=TOOLS,
        )

    def run_agent(
        self,
        user_input: str,
        executor: ToolExecutor,
    ) -> str:
        response = self._client.responses.create(
            model=self._settings.azure_openai_deployment,
            input=user_input,
            tools=TOOLS,
        )

        while True:
            tool_outputs: list[dict[str, Any]] = []

            for item in response.output:
                if item.type != "function_call":
                    continue

                arguments = item.arguments
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)

                tool_result = executor.execute(
                    item.name,
                    arguments,
                )

                if hasattr(tool_result, "model_dump_json"):
                    output = tool_result.model_dump_json()
                elif hasattr(tool_result, "model_dump"):
                    output = json.dumps(tool_result.model_dump(), default=str)
                else:
                    output = json.dumps(tool_result, default=str)

                tool_outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": item.call_id,
                        "output": output,
                    }
                )

            if not tool_outputs:
                return getattr(response, "output_text", "")

            response = self._client.responses.create(
                model=self._settings.azure_openai_deployment,
                previous_response_id=response.id,
                input=tool_outputs,
                tools=TOOLS,
            )


ai_service = AIService()