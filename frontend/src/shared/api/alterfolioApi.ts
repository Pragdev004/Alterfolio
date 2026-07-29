import { apiClient } from "../../services/apiClient";
import {
  HealthResponse,
  PortfolioAnalysisResponse,
  PortfolioSummary,
  TradeCreateRequest,
  TradeResponse,
} from "./types";

export async function getHealth() {
  const response = await apiClient.get<HealthResponse>("/health");
  return response.data;
}

export async function getPortfolioSummary() {
  const response = await apiClient.get<PortfolioSummary>("/portfolio/summary");
  return response.data;
}

export async function getPortfolioAnalysis() {
  const response = await apiClient.get<PortfolioAnalysisResponse>(
    "/portfolio/analysis"
  );
  return response.data;
}

export async function getTrades() {
  const response = await apiClient.get<TradeResponse[]>("/trades/");
  return response.data;
}

export async function createTrade(payload: TradeCreateRequest) {
  const response = await apiClient.post<TradeResponse>("/trades/", payload);
  return response.data;
}
