import { Navigate, Route, Routes } from "react-router-dom";

import { AppLayout } from "../layouts/AppLayout";
import { AIAnalysisPage } from "../pages/AIAnalysisPage";
import { DashboardPage } from "../pages/DashboardPage";
import { MarketIntelligencePage } from "../pages/MarketIntelligencePage";
import { NotFoundPage } from "../pages/NotFoundPage";
import { PortfolioPage } from "../pages/PortfolioPage";
import { TradesPage } from "../pages/TradesPage";

export function App() {
  return (
    <Routes>
      <Route path="/" element={<AppLayout />}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<DashboardPage />} />
        <Route path="trades" element={<TradesPage />} />
        <Route path="portfolio" element={<PortfolioPage />} />
        <Route path="ai-analysis" element={<AIAnalysisPage />} />
        <Route path="market-intelligence" element={<MarketIntelligencePage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
