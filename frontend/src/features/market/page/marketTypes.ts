export type MarketSentiment = "positive" | "negative" | "neutral";

export type MarketNewsItem = {
  id: string;
  headline: string;
  summary: string;
  source: string;
  publishedAt: string;
  relatedSymbols: string[];
  sentiment: MarketSentiment;
};

export type PortfolioImpactItem = {
  symbol: string;
  mentionCount: number;
  latestHeadline: string;
};

export type MarketMover = {
  symbol: string;
  changePercent: number;
  latestPrice: number;
};

export type EarningsEvent = {
  symbol: string;
  earningsDate: string;
  confidenceNote: string;
};

export type MarketIntelligenceData = {
  news: MarketNewsItem[];
  impact: PortfolioImpactItem[];
  aiSummary: string;
  movers: {
    gainers: MarketMover[];
    losers: MarketMover[];
  };
  earnings: EarningsEvent[];
  dataSource: "backend" | "derived";
};
