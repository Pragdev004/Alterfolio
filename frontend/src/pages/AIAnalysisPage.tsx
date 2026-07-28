import { useState } from "react";

import { PageContainer } from "../components/PageContainer";
import { useLoading } from "../hooks/useLoading";
import { getPortfolioAnalysis } from "../services/alterfolioApi";
import { PortfolioAnalysisResponse, getApiErrorMessage } from "../types/api";

function renderList(items: string[]) {
  if (items.length === 0) {
    return <p>No items available.</p>;
  }

  return (
    <ul className="analysis-list">
      {items.map((item, index) => (
        <li key={`${item}-${index}`}>{item}</li>
      ))}
    </ul>
  );
}

export function AIAnalysisPage() {
  const { startLoading, stopLoading } = useLoading();

  const [analysisResponse, setAnalysisResponse] =
    useState<PortfolioAnalysisResponse | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  const handleAnalyzePortfolio = async () => {
    setIsAnalyzing(true);
    setErrorMessage("");
    startLoading();

    try {
      const response = await getPortfolioAnalysis();
      setAnalysisResponse(response);
    } catch (error) {
      setAnalysisResponse(null);
      setErrorMessage(getApiErrorMessage(error));
    } finally {
      setIsAnalyzing(false);
      stopLoading();
    }
  };

  return (
    <PageContainer
      title="AI Analysis"
      description="Run AI analysis for your current portfolio."
    >
      <button
        type="button"
        className="button-primary analysis-button"
        onClick={handleAnalyzePortfolio}
        disabled={isAnalyzing}
      >
        {isAnalyzing ? "Analyzing..." : "Analyze Portfolio"}
      </button>

      {isAnalyzing ? <p className="analysis-status">Generating analysis...</p> : null}

      {!isAnalyzing && errorMessage ? (
        <p className="feedback error">{errorMessage}</p>
      ) : null}

      {!isAnalyzing && !errorMessage && !analysisResponse ? (
        <p className="analysis-empty">No analysis yet. Click "Analyze Portfolio" to begin.</p>
      ) : null}

      {!isAnalyzing && !errorMessage && analysisResponse ? (
        <div className="analysis-sections">
          <section className="dashboard-holdings">
            <h2 className="trades-section-title">Overview</h2>
            <p>{analysisResponse.analysis.overview}</p>
          </section>

          <section className="dashboard-holdings">
            <h2 className="trades-section-title">Diversification Analysis</h2>
            <p>{analysisResponse.analysis.diversification_analysis}</p>
          </section>

          <section className="dashboard-holdings">
            <h2 className="trades-section-title">Risk Assessment</h2>
            <p>{analysisResponse.analysis.risk_assessment}</p>
          </section>

          <section className="dashboard-holdings">
            <h2 className="trades-section-title">Strengths</h2>
            {renderList(analysisResponse.analysis.strengths)}
          </section>

          <section className="dashboard-holdings">
            <h2 className="trades-section-title">Weaknesses</h2>
            {renderList(analysisResponse.analysis.weaknesses)}
          </section>

          <section className="dashboard-holdings">
            <h2 className="trades-section-title">Recommendations</h2>
            {renderList(analysisResponse.analysis.recommendations)}
          </section>
        </div>
      ) : null}
    </PageContainer>
  );
}
