import { getPortfolioAnalysis } from "../../../shared/api/alterfolioApi";
import { getApiErrorMessage } from "../../../shared/api/types";
import { parseDecimal } from "../../../shared/lib/format";
import { type AstraAdapter, type AstraPromptContext } from "./astraTypes";

function buildPortfolioSummaryLine(context: AstraPromptContext): string {
  if (!context.summary) {
    return "Portfolio summary is currently unavailable.";
  }

  const holdingsCount = context.summary.holdings.length;
  const totalValue = parseDecimal(context.summary.total_invested);

  return `Portfolio snapshot: ${holdingsCount} holdings, total value ${totalValue.toFixed(2)} INR.`;
}

function toMarkdownList(items: string[]): string {
  if (items.length === 0) {
    return "- No items returned.";
  }

  return items.map((item) => `- ${item}`).join("\n");
}

function normalizePrompt(prompt: string): string {
  return prompt.trim().toLowerCase();
}

export class AnalysisBackedAstraAdapter implements AstraAdapter {
  async respond(context: AstraPromptContext): Promise<string> {
    try {
      const response = await getPortfolioAnalysis();
      const prompt = normalizePrompt(context.prompt);

      if (prompt.includes("review") && prompt.includes("portfolio")) {
        return [
          "## Portfolio Review",
          buildPortfolioSummaryLine(context),
          "",
          `**Overview:** ${response.analysis.overview}`,
          "",
          "### Strengths",
          toMarkdownList(response.analysis.strengths.slice(0, 3)),
          "",
          "### Weaknesses",
          toMarkdownList(response.analysis.weaknesses.slice(0, 3)),
        ].join("\n");
      }

      if (prompt.includes("risk")) {
        return [
          "## Portfolio Risk",
          buildPortfolioSummaryLine(context),
          "",
          response.analysis.risk_assessment,
        ].join("\n");
      }

      if (prompt.includes("diversif")) {
        return [
          "## Diversification Guidance",
          buildPortfolioSummaryLine(context),
          "",
          response.analysis.diversification_analysis,
          "",
          "### Suggested Actions",
          toMarkdownList(response.analysis.recommendations.slice(0, 3)),
        ].join("\n");
      }

      if (prompt.includes("summar") && prompt.includes("recommend")) {
        return [
          "## AI Recommendations",
          toMarkdownList(response.analysis.recommendations),
        ].join("\n");
      }

      return [
        "## Astra Response",
        buildPortfolioSummaryLine(context),
        "",
        `**Overview:** ${response.analysis.overview}`,
        "",
        "### Top Recommendations",
        toMarkdownList(response.analysis.recommendations.slice(0, 3)),
      ].join("\n");
    } catch (error) {
      const reason = getApiErrorMessage(error);

      return [
        "## Astra is ready for chat integration",
        "I couldn't reach the live copilot backend yet.",
        "",
        `- Current status: ${reason}`,
        "- The page architecture and adapter layer are in place.",
        "- Connect a chat endpoint in `astraAdapter.ts` without changing UI components.",
      ].join("\n");
    }
  }
}

export const astraAdapter: AstraAdapter = new AnalysisBackedAstraAdapter();
