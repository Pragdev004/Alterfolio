export type HealthResponse = {
  status: "ok";
};

export type HoldingSummary = {
  symbol: string;
  quantity: string;
  average_buy_price: string;
  invested_amount: string;
};

export type PortfolioSummary = {
  total_trades: number;
  total_invested: string;
  holdings: HoldingSummary[];
};

export type PortfolioAnalysis = {
  overview: string;
  diversification_analysis: string;
  risk_assessment: string;
  strengths: string[];
  weaknesses: string[];
  recommendations: string[];
};

export type PortfolioAnalysisResponse = {
  analysis: PortfolioAnalysis;
  model: string;
  generated_at: string;
};

export type AssetType =
  | "STOCK"
  | "ETF"
  | "MUTUAL_FUND"
  | "BOND"
  | "GOLD"
  | "REIT"
  | "INVIT"
  | "INDEX"
  | "FUTURES"
  | "OPTIONS"
  | "CASH";

export type Exchange = "NSE" | "BSE" | "NFO" | "MCX";

export type TransactionType = "BUY" | "SELL";

export type TradeSource = "MANUAL" | "IMPORT" | "BROKER_SYNC" | "AI";

export type MarketSession = "PRE_MARKET" | "REGULAR" | "POST_MARKET";

export type TradeCreateRequest = {
  asset_symbol: string;
  asset_name: string;
  asset_type: AssetType;
  exchange: Exchange;
  transaction_type: TransactionType;
  quantity: string;
  price_per_unit: string;
  trade_timestamp: string;
  trade_source: TradeSource;
  market_session: MarketSession;
};

export type TradeResponse = TradeCreateRequest & {
  id: string;
  user_id: string;
  created_at: string;
  updated_at: string;
};

export type ApiValidationIssue = {
  msg?: string;
};

export type ApiErrorBody = {
  code?: string;
  message?: string;
  detail?: string | ApiValidationIssue[];
};

export type ApiErrorLike = {
  response?: {
    status?: number;
    data?: ApiErrorBody;
  };
};

export function getApiErrorMessage(error: unknown): string {
  if (
    typeof error === "object" &&
    error !== null &&
    "response" in error &&
    (error as ApiErrorLike).response
  ) {
    const response = (error as ApiErrorLike).response;

    if (response?.status === 422 && Array.isArray(response.data?.detail)) {
      const messages = response.data.detail
        .map((issue) => issue.msg)
        .filter((msg): msg is string => Boolean(msg));

      if (messages.length > 0) {
        return messages.join(", ");
      }

      return "Validation failed. Please review the form values.";
    }

    if (typeof response?.data?.message === "string") {
      return response.data.message;
    }

    if (typeof response?.data?.detail === "string") {
      return response.data.detail;
    }
  }

  return "Request failed. Please try again.";
}
