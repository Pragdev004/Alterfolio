import { useEffect } from "react";
import { Link } from "react-router-dom";

import { useHoldings, useSummary } from "../../shared/api/queries";
import type { HoldingOut, SummaryHolding, SummaryOut } from "../../shared/api/types";
import { Shown, Unavailable } from "../../shared/ui/Figure";
import { RefreshFailed, RejectedRowsWarning } from "../../shared/ui/Notices";
import { StatusCode } from "../../shared/ui/StatusCode";
import { EmptyState, ErrorState, Skeleton } from "../../shared/ui/States";

const listingName = (h: { name: string | null; listings: { symbol: string; exchange: string }[] }) =>
  h.name ?? h.listings.map((l) => `${l.symbol} · ${l.exchange}`).join(", ");

/** The reasons a valuation cell is empty, in the server's words: the price comes first, then the cost basis. */
const whyMissing = (h: SummaryHolding) => [h.market_value_unavailable_reason, h.unrealized_pnl_unavailable_reason].filter((r): r is string => !!r);

function ValuedRow({ h }: { h: SummaryHolding }) {
  const notes = whyMissing(h);
  return (
    <tr role="row">
      <th role="rowheader" scope="row">{listingName(h)}</th>
      <td role="cell" className="n cell">{h.quantity_display}</td>
      <td role="cell" className="n cell"><Shown value={h.average_buy_price} display={h.average_buy_price_display} /></td>
      <td role="cell" className="n cell"><Shown value={h.invested_amount} display={h.invested_amount_display} /></td>
      <td role="cell" className="n val"><Shown value={h.market_value} display={h.market_value_display} /></td>
      <td role="cell" className="n cell"><Shown value={h.unrealized_pnl} display={h.unrealized_pnl_display} /></td>
      <td role="cell" className="m-line">
        <span className="l">Qty </span>{h.quantity_display}<span className="sep">·</span>
        <span className="l">Avg </span>{h.average_buy_price_display}<span className="sep">·</span>
        <span className="l">Invested </span>{h.invested_amount_display}<span className="sep">·</span>
        <span className="l">P&amp;L </span>{h.unrealized_pnl_display}
      </td>
      <td role="cell" className="note">
        {notes.map((n) => <span key={n} className="reason">{n} </span>)}
      </td>
    </tr>
  );
}

/** Ledger-only rows, used when the prices could not be loaded: every valuation cell says Unavailable. */
function LedgerRow({ h }: { h: HoldingOut }) {
  return (
    <tr role="row">
      <th role="rowheader" scope="row">{listingName(h)}</th>
      <td role="cell" className="n cell">{h.quantity_display}</td>
      <td role="cell" className="n cell"><Shown value={h.average_buy_price} display={h.average_buy_price_display} /></td>
      <td role="cell" className="n cell"><Shown value={h.invested_amount} display={h.invested_amount_display} /></td>
      <td role="cell" className="n val"><Unavailable /></td>
      <td role="cell" className="n cell"><Unavailable /></td>
      <td role="cell" className="m-line"><span className="l">Qty </span>{h.quantity_display}<span className="sep">·</span><span className="l">Invested </span>{h.invested_amount_display}</td>
      <td role="cell" className="note"><span className="reason">Prices have not loaded.</span></td>
    </tr>
  );
}

const HEAD = (
  <thead role="rowgroup">
    <tr role="row">
      <th role="columnheader" scope="col">Holding</th><th role="columnheader" scope="col" className="n">Quantity</th><th role="columnheader" scope="col" className="n">Avg price</th>
      <th role="columnheader" scope="col" className="n">Invested</th><th role="columnheader" scope="col" className="n">Market value</th><th role="columnheader" scope="col" className="n">P&amp;L</th><th role="columnheader" scope="col">Note</th>
    </tr>
  </thead>
);

function Totals({ s }: { s: SummaryOut }) {
  const partial = s.valuation_status !== "COMPLETE";
  return (
    <tfoot role="rowgroup">
      <tr role="row">
        <th role="rowheader" scope="row">Total</th><td role="cell" className="cell" />
        <td role="cell" className="cell" />
        <td role="cell" className="n cell"><Shown value={s.total_invested} display={s.total_invested_display} strong /></td>
        <td role="cell" className="n val"><Shown value={s.total_market_value} display={s.total_market_value_display} strong /></td>
        <td role="cell" className="n cell"><Shown value={s.total_unrealized_pnl} display={s.total_unrealized_pnl_display} strong /></td>
        <td role="cell" className="m-line"><span className="l">Invested </span>{s.total_invested_display}<span className="sep">·</span><span className="l">P&amp;L </span>{s.total_unrealized_pnl_display}</td>
        <td role="cell" className="note">
          {partial && <span className="reason">{s.valuation_text}</span>}
          {s.total_unrealized_pnl_unavailable_reason && <span className="reason">{s.total_unrealized_pnl_unavailable_reason}</span>}
        </td>
      </tr>
    </tfoot>
  );
}

export function HoldingsScreen() {
  const summary = useSummary();
  const ledger = useHoldings();
  useEffect(() => { document.title = "Holdings · Alterfolio"; }, []);
  const s = summary.data;
  // A failed refresh with figures already on screen is a notice, not an error state above a full table.
  const stale = summary.isError && s !== undefined;
  const failed = summary.isError && s === undefined;
  const none = (s && s.holdings.length === 0) || (failed && ledger.isSuccess && ledger.data.length === 0);

  return (
    <>
      <div className="chart-head" role="group" aria-label="Valuation">
        <span><span className="k">Prices as of</span><span className="fig">{s ? s.valuation_time_display : failed ? "Unavailable" : "…"}</span></span>
        <span>Current holdings, valued at the latest price the source returned. A missing price is never estimated.</span>
      </div>
      <div className="title"><h1>Holdings</h1><span className="sub">What your ledger says you hold now</span></div>

      <RejectedRowsWarning />
      {summary.isPending && <Skeleton label="Fetching prices" />}
      {failed && <ErrorState error={summary.error} onRetry={() => void summary.refetch()} />}
      {stale && <RefreshFailed at={summary.dataUpdatedAt} onRetry={() => void summary.refetch()} />}

      {s && s.holdings_count > 0 && (
        <p className={s.status_label === "COMPLETE" ? "lede" : "too-few"} style={s.status_label === "COMPLETE" ? undefined : { maxWidth: "64ch" }}>
          <StatusCode hold={s.status_label !== "COMPLETE"}>{s.status_label}</StatusCode> <span>{s.status_text}</span>
        </p>
      )}

      {none ? (
        <EmptyState title="Nothing is held right now.">
          <p>Holdings appear after you <Link to="/upload">upload a tradebook</Link>, and disappear when a position is fully sold.</p>
        </EmptyState>
      ) : s ? (
        <table role="table">
          <caption>One row per holding. NSE and BSE listings of the same ISIN are one holding.</caption>
          {HEAD}
          <tbody role="rowgroup">{s.holdings.map((h) => <ValuedRow key={h.isin ?? listingName(h)} h={h} />)}</tbody>
          <Totals s={s} />
        </table>
      ) : (
        failed && ledger.isSuccess && (
          <table role="table">
            <caption>Ledger holdings only: prices are not available right now.</caption>
            {HEAD}
            <tbody role="rowgroup">{ledger.data.map((h) => <LedgerRow key={h.isin ?? listingName(h)} h={h} />)}</tbody>
          </table>
        )
      )}
    </>
  );
}
