import { useEffect } from "react";
import { Link } from "react-router-dom";

import { useHoldings, useSummary } from "../../shared/api/queries";
import type { HoldingOut, SummaryHolding, SummaryOut } from "../../shared/api/types";
import { Shown, Unavailable } from "../../shared/ui/Figure";
import { StatusCode } from "../../shared/ui/StatusCode";
import { EmptyState, ErrorState, Skeleton } from "../../shared/ui/States";

const listingName = (h: { name: string | null; listings: { symbol: string; exchange: string }[] }) =>
  h.name ?? h.listings.map((l) => `${l.symbol} · ${l.exchange}`).join(", ");

/** The reason a valuation cell is empty, in the server's words. */
const whyMissing = (h: SummaryHolding) => h.market_value_unavailable_reason ?? h.unrealized_pnl_unavailable_reason ?? null;

function ValuedRow({ h }: { h: SummaryHolding }) {
  const note = whyMissing(h);
  return (
    <tr>
      <th scope="row">{listingName(h)}</th>
      <td className="n cell">{h.quantity_display}</td>
      <td className="n cell"><Shown value={h.average_buy_price} display={h.average_buy_price_display} /></td>
      <td className="n cell"><Shown value={h.invested_amount} display={h.invested_amount_display} /></td>
      <td className="n val"><Shown value={h.market_value} display={h.market_value_display} /></td>
      <td className="n cell"><Shown value={h.unrealized_pnl} display={h.unrealized_pnl_display} /></td>
      <td className="m-line">
        <span className="l">Qty </span>{h.quantity_display}<span className="sep">·</span>
        <span className="l">Avg </span>{h.average_buy_price_display}<span className="sep">·</span>
        <span className="l">Invested </span>{h.invested_amount_display}<span className="sep">·</span>
        <span className="l">P&amp;L </span>{h.unrealized_pnl_display}
      </td>
      <td className="note">
        {note && <span className="reason">{note}</span>}
        {!h.cost_basis_complete && <span className="reason"> Cost basis is incomplete for this holding.</span>}
      </td>
    </tr>
  );
}

/** Ledger-only rows, used when the prices could not be loaded: every valuation cell says Unavailable. */
function LedgerRow({ h }: { h: HoldingOut }) {
  return (
    <tr>
      <th scope="row">{listingName(h)}</th>
      <td className="n cell">{h.quantity_display}</td>
      <td className="n cell"><Shown value={h.average_buy_price} display={h.average_buy_price_display} /></td>
      <td className="n cell"><Shown value={h.invested_amount} display={h.invested_amount_display} /></td>
      <td className="n val"><Unavailable /></td>
      <td className="n cell"><Unavailable /></td>
      <td className="m-line"><span className="l">Qty </span>{h.quantity_display}<span className="sep">·</span><span className="l">Invested </span>{h.invested_amount_display}</td>
      <td className="note"><span className="reason">Prices have not loaded.</span></td>
    </tr>
  );
}

const HEAD = (
  <thead>
    <tr>
      <th scope="col">Holding</th><th scope="col" className="n">Quantity</th><th scope="col" className="n">Avg price</th>
      <th scope="col" className="n">Invested</th><th scope="col" className="n">Market value</th><th scope="col" className="n">P&amp;L</th><th scope="col">Note</th>
    </tr>
  </thead>
);

function Totals({ s }: { s: SummaryOut }) {
  const partial = s.valuation_status !== "COMPLETE";
  return (
    <tfoot>
      <tr>
        <th scope="row">Total</th><td className="cell" />
        <td className="cell" />
        <td className="n cell"><Shown value={s.total_invested} display={s.total_invested_display} strong /></td>
        <td className="n val"><Shown value={s.total_market_value} display={s.total_market_value_display} strong /></td>
        <td className="n cell"><Shown value={s.total_unrealized_pnl} display={s.total_unrealized_pnl_display} strong /></td>
        <td className="m-line"><span className="l">Invested </span>{s.total_invested_display}<span className="sep">·</span><span className="l">P&amp;L </span>{s.total_unrealized_pnl_display}</td>
        <td className="note">{partial && <span className="reason">{s.valuation_text}</span>}</td>
      </tr>
    </tfoot>
  );
}

export function HoldingsScreen() {
  const summary = useSummary();
  const ledger = useHoldings();
  useEffect(() => { document.title = "Holdings · Alterfolio"; }, []);
  const s = summary.data;
  const none = (s && s.holdings.length === 0) || (summary.isError && ledger.isSuccess && ledger.data.length === 0);

  return (
    <>
      <div className="chart-head" role="group" aria-label="Valuation">
        <span><span className="k">Prices as of</span><span className="fig">{s ? s.valuation_time_display : summary.isError ? "Unavailable" : "…"}</span></span>
        <span>Current holdings, valued at the latest price the source returned. A missing price is never estimated.</span>
      </div>
      <div className="title"><h1>Holdings</h1><span className="sub">What your ledger says you hold now</span></div>

      {summary.isPending && <Skeleton label="Fetching prices" />}
      {summary.isError && <ErrorState error={summary.error} onRetry={() => void summary.refetch()} />}

      {s && (
        <p className={s.valuation_status === "COMPLETE" ? "lede" : "too-few"} style={s.valuation_status === "COMPLETE" ? undefined : { maxWidth: "64ch" }}>
          <StatusCode hold={s.valuation_status !== "COMPLETE"}>{s.valuation_status}</StatusCode> <span>{s.valuation_text}</span>
        </p>
      )}

      {none ? (
        <EmptyState title="Nothing is held right now.">
          <p>Holdings appear after you <Link to="/upload">upload a tradebook</Link>, and disappear when a position is fully sold.</p>
        </EmptyState>
      ) : s ? (
        <table>
          <caption>One row per holding. NSE and BSE listings of the same ISIN are one holding.</caption>
          {HEAD}
          <tbody>{s.holdings.map((h) => <ValuedRow key={h.isin ?? listingName(h)} h={h} />)}</tbody>
          <Totals s={s} />
        </table>
      ) : (
        summary.isError && ledger.isSuccess && (
          <table>
            <caption>Ledger holdings only: prices are not available right now.</caption>
            {HEAD}
            <tbody>{ledger.data.map((h) => <LedgerRow key={h.isin ?? listingName(h)} h={h} />)}</tbody>
          </table>
        )
      )}
    </>
  );
}
