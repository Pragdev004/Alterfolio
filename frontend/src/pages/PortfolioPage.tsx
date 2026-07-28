import { useEffect, useState } from "react";

import { PageContainer } from "../components/PageContainer";
import { useLoading } from "../hooks/useLoading";
import { getPortfolioSummary } from "../services/alterfolioApi";
import { HoldingSummary, getApiErrorMessage } from "../types/api";

export function PortfolioPage() {
  const { startLoading, stopLoading } = useLoading();

  const [holdings, setHoldings] = useState<HoldingSummary[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    const loadPortfolio = async () => {
      setIsLoading(true);
      setErrorMessage("");
      startLoading();

      try {
        const summary = await getPortfolioSummary();
        setHoldings(summary.holdings);
      } catch (error) {
        setErrorMessage(getApiErrorMessage(error));
      } finally {
        setIsLoading(false);
        stopLoading();
      }
    };

    void loadPortfolio();
  }, []);

  return (
    <PageContainer
      title="Portfolio"
      description="Portfolio holdings summary from backend."
    >
      {isLoading ? <p>Loading portfolio...</p> : null}

      {!isLoading && errorMessage ? (
        <p className="feedback error">{errorMessage}</p>
      ) : null}

      {!isLoading && !errorMessage && holdings.length === 0 ? (
        <p>No holdings found in your portfolio yet.</p>
      ) : null}

      {!isLoading && !errorMessage && holdings.length > 0 ? (
        <div className="table-wrap">
          <table className="trades-table">
            <thead>
              <tr>
                <th>Holdings</th>
                <th>Quantity</th>
                <th>Average Buy Price</th>
                <th>Invested Amount</th>
              </tr>
            </thead>
            <tbody>
              {holdings.map((holding) => (
                <tr key={holding.symbol}>
                  <td>{holding.symbol}</td>
                  <td>{holding.quantity}</td>
                  <td>{holding.average_buy_price}</td>
                  <td>{holding.invested_amount}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </PageContainer>
  );
}
