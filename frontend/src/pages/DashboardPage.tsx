import { useEffect, useState } from "react";

import { PageContainer } from "../components/PageContainer";
import { useLoading } from "../hooks/useLoading";
import { getPortfolioSummary } from "../services/alterfolioApi";
import { PortfolioSummary, getApiErrorMessage } from "../types/api";

export function DashboardPage() {
  const { startLoading, stopLoading } = useLoading();

  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    const loadDashboardSummary = async () => {
      setIsLoading(true);
      setErrorMessage("");
      startLoading();

      try {
        const portfolioSummary = await getPortfolioSummary();
        setSummary(portfolioSummary);
      } catch (error) {
        setErrorMessage(getApiErrorMessage(error));
      } finally {
        setIsLoading(false);
        stopLoading();
      }
    };

    void loadDashboardSummary();
  }, []);

  const holdings = summary?.holdings ?? [];

  return (
    <PageContainer
      title="Dashboard"
      description="High-level view of your portfolio summary."
    >
      {isLoading ? <p>Loading dashboard...</p> : null}

      {!isLoading && errorMessage ? (
        <p className="feedback error">{errorMessage}</p>
      ) : null}

      {!isLoading && !errorMessage ? (
        <>
          <div className="dashboard-cards">
            <article className="dashboard-card">
              <p className="dashboard-card-label">Total Invested</p>
              <p className="dashboard-card-value">{summary?.total_invested ?? "0"}</p>
            </article>

            <article className="dashboard-card">
              <p className="dashboard-card-label">Total Trades</p>
              <p className="dashboard-card-value">{summary?.total_trades ?? 0}</p>
            </article>

            <article className="dashboard-card">
              <p className="dashboard-card-label">Total Holdings</p>
              <p className="dashboard-card-value">{holdings.length}</p>
            </article>
          </div>

          <section className="dashboard-holdings">
            <h2 className="trades-section-title">Holdings Overview</h2>

            {holdings.length === 0 ? (
              <p>No holdings found in your portfolio yet.</p>
            ) : (
              <div className="table-wrap">
                <table className="trades-table">
                  <thead>
                    <tr>
                      <th>Symbol</th>
                      <th>Quantity</th>
                      <th>Invested Amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {holdings.map((holding) => (
                      <tr key={holding.symbol}>
                        <td>{holding.symbol}</td>
                        <td>{holding.quantity}</td>
                        <td>{holding.invested_amount}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      ) : null}
    </PageContainer>
  );
}
