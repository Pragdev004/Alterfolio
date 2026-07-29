import { type PortfolioSummary } from "../../../shared/api/types";

export type CopilotRole = "user" | "assistant" | "system";

export type CopilotMessage = {
  id: string;
  role: CopilotRole;
  content: string;
  timestamp: string;
};

export type AstraPromptContext = {
  prompt: string;
  summary: PortfolioSummary | null;
};

export type AstraAdapter = {
  respond: (context: AstraPromptContext) => Promise<string>;
};
