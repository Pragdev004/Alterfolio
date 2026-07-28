import { ChangeEvent, FormEvent, useEffect, useState } from "react";

import { useLoading } from "../hooks/useLoading";
import { PageContainer } from "../components/PageContainer";
import { createTrade, getTrades } from "../services/alterfolioApi";
import {
  AssetType,
  Exchange,
  TradeCreateRequest,
  TradeResponse,
  TradeSource,
  TransactionType,
  getApiErrorMessage,
} from "../types/api";

const assetTypes: AssetType[] = [
  "STOCK",
  "ETF",
  "MUTUAL_FUND",
  "BOND",
  "GOLD",
  "REIT",
  "INVIT",
  "INDEX",
  "FUTURES",
  "OPTIONS",
  "CASH",
];

const exchanges: Exchange[] = ["NSE", "BSE", "NFO", "MCX"];

const transactionTypes: TransactionType[] = ["BUY", "SELL"];

const tradeSources: TradeSource[] = ["MANUAL", "IMPORT", "BROKER_SYNC", "AI"];

const DEV_USER_ID = "11111111-1111-4111-8111-111111111111";

const initialFormState: TradeCreateRequest = {
  user_id: DEV_USER_ID,
  asset_symbol: "",
  asset_name: "",
  asset_type: "STOCK",
  exchange: "NSE",
  transaction_type: "BUY",
  quantity: "",
  price_per_unit: "",
  trade_timestamp: "",
  trade_source: "MANUAL",
  market_session: "REGULAR",
};

export function TradesPage() {
  const { startLoading, stopLoading } = useLoading();

  const [formData, setFormData] = useState<TradeCreateRequest>(initialFormState);
  const [trades, setTrades] = useState<TradeResponse[]>([]);
  const [isFetchingTrades, setFetchingTrades] = useState(false);
  const [isSubmitting, setSubmitting] = useState(false);
  const [successMessage, setSuccessMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");

  const loadTrades = async () => {
    setFetchingTrades(true);
    setErrorMessage("");
    startLoading();

    try {
      const tradeList = await getTrades();
      setTrades(tradeList);
    } catch (error) {
      setErrorMessage(getApiErrorMessage(error));
    } finally {
      setFetchingTrades(false);
      stopLoading();
    }
  };

  useEffect(() => {
    void loadTrades();
  }, []);

  const handleInputChange = (
    event: ChangeEvent<HTMLInputElement | HTMLSelectElement>
  ) => {
    const { name, value } = event.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
  };

  const validateForm = () => {
    if (!formData.asset_symbol.trim()) {
      return "Asset Symbol is required.";
    }

    if (!formData.asset_name.trim()) {
      return "Asset Name is required.";
    }

    if (!formData.trade_timestamp) {
      return "Trade Timestamp is required.";
    }

    const quantity = Number(formData.quantity);
    if (!Number.isFinite(quantity) || quantity <= 0) {
      return "Quantity must be a positive number.";
    }

    const price = Number(formData.price_per_unit);
    if (!Number.isFinite(price) || price <= 0) {
      return "Price Per Unit must be a positive number.";
    }

    return "";
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSuccessMessage("");
    setErrorMessage("");

    const validationMessage = validateForm();
    if (validationMessage) {
      setErrorMessage(validationMessage);
      return;
    }

    setSubmitting(true);
    startLoading();

    try {
      await createTrade({
        ...formData,
        user_id: DEV_USER_ID,
        asset_symbol: formData.asset_symbol.trim().toUpperCase(),
        asset_name: formData.asset_name.trim(),
      });

      setFormData(initialFormState);
      setSuccessMessage("Trade added successfully.");
      await loadTrades();
    } catch (error) {
      setErrorMessage(getApiErrorMessage(error));
    } finally {
      setSubmitting(false);
      stopLoading();
    }
  };

  return (
    <PageContainer
      title="Trades"
      description="Add trades and view your trade history."
    >
      <div className="trades-grid">
        <section className="trades-panel">
          <h2 className="trades-section-title">Add Trade</h2>
          <form className="trades-form" onSubmit={handleSubmit}>
            <label>
              Asset Symbol
              <input
                type="text"
                name="asset_symbol"
                value={formData.asset_symbol}
                onChange={handleInputChange}
                placeholder="e.g. TCS"
                required
              />
            </label>

            <label>
              Asset Name
              <input
                type="text"
                name="asset_name"
                value={formData.asset_name}
                onChange={handleInputChange}
                placeholder="e.g. Tata Consultancy Services"
                required
              />
            </label>

            <label>
              Asset Type
              <select
                name="asset_type"
                value={formData.asset_type}
                onChange={handleInputChange}
              >
                {assetTypes.map((assetType) => (
                  <option key={assetType} value={assetType}>
                    {assetType}
                  </option>
                ))}
              </select>
            </label>

            <label>
              Exchange
              <select
                name="exchange"
                value={formData.exchange}
                onChange={handleInputChange}
              >
                {exchanges.map((exchange) => (
                  <option key={exchange} value={exchange}>
                    {exchange}
                  </option>
                ))}
              </select>
            </label>

            <label>
              Transaction Type
              <select
                name="transaction_type"
                value={formData.transaction_type}
                onChange={handleInputChange}
              >
                {transactionTypes.map((transactionType) => (
                  <option key={transactionType} value={transactionType}>
                    {transactionType}
                  </option>
                ))}
              </select>
            </label>

            <label>
              Quantity
              <input
                type="number"
                name="quantity"
                value={formData.quantity}
                onChange={handleInputChange}
                step="any"
                min="0"
                required
              />
            </label>

            <label>
              Price Per Unit
              <input
                type="number"
                name="price_per_unit"
                value={formData.price_per_unit}
                onChange={handleInputChange}
                step="any"
                min="0"
                required
              />
            </label>

            <label>
              Trade Timestamp
              <input
                type="datetime-local"
                name="trade_timestamp"
                value={formData.trade_timestamp}
                onChange={handleInputChange}
                required
              />
            </label>

            <label>
              Trade Source
              <select
                name="trade_source"
                value={formData.trade_source}
                onChange={handleInputChange}
              >
                {tradeSources.map((tradeSource) => (
                  <option key={tradeSource} value={tradeSource}>
                    {tradeSource}
                  </option>
                ))}
              </select>
            </label>

            <button type="submit" className="button-primary" disabled={isSubmitting}>
              {isSubmitting ? "Saving..." : "Add Trade"}
            </button>
          </form>

          {successMessage ? (
            <p className="feedback success">{successMessage}</p>
          ) : null}
          {errorMessage ? <p className="feedback error">{errorMessage}</p> : null}
        </section>

        <section className="trades-panel">
          <h2 className="trades-section-title">Trade History</h2>

          {isFetchingTrades ? <p>Loading trades...</p> : null}

          {!isFetchingTrades && trades.length === 0 ? (
            <p>No trades yet. Add your first trade.</p>
          ) : null}

          {!isFetchingTrades && trades.length > 0 ? (
            <div className="table-wrap">
              <table className="trades-table">
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Transaction Type</th>
                    <th>Quantity</th>
                    <th>Price</th>
                    <th>Timestamp</th>
                  </tr>
                </thead>
                <tbody>
                  {trades.map((trade) => (
                    <tr key={trade.id}>
                      <td>{trade.asset_symbol}</td>
                      <td>{trade.transaction_type}</td>
                      <td>{trade.quantity}</td>
                      <td>{trade.price_per_unit}</td>
                      <td>{new Date(trade.trade_timestamp).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </section>
      </div>
    </PageContainer>
  );
}
