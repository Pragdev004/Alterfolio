import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";

import { useAsOf } from "../../app/useAsOf";
import { ApiError } from "../../shared/api/errors";
import { useMeta, useTrades, useTrips } from "../../shared/api/queries";
import type { TripRow, TripsOut } from "../../shared/api/types";
import { ChartHeader } from "../../shared/ui/ChartHeader";
import { Figure, Unavailable } from "../../shared/ui/Figure";
import { TooFew } from "../../shared/ui/SampleSentence";
import { StatusCode } from "../../shared/ui/StatusCode";
import { EmptyState, ErrorState, NotFinal, Skeleton } from "../../shared/ui/States";
import { tripNote, tripStatus } from "./status";

function TripTable({ data, search }: { data: TripsOut; search: string }) {
  const body = useRef<HTMLTableSectionElement>(null);
  // Arrow keys move between rows; Enter on the focused link opens the trip.
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const links = Array.from(body.current?.querySelectorAll<HTMLAnchorElement>("a[data-row-link]") ?? []);
    const at = links.indexOf(document.activeElement as HTMLAnchorElement);
    const next = links[at + (e.key === "ArrowDown" ? 1 : -1)];
    if (next) {
      e.preventDefault();
      next.focus();
    }
  };
  return (
    <table className="table-trips" onKeyDown={onKeyDown}>
      <caption>One row per closed trip, oldest first. Returns use ledger prices and exclude fees.</caption>
      <thead>
        <tr>
          <th scope="col">Listing</th>
          <th scope="col">Opened</th>
          <th scope="col">Closed</th>
          <th scope="col" className="n">Return (fees excluded)</th>
          <th scope="col">Alternatives</th>
          <th scope="col" className="n">Percentile</th>
          <th scope="col">Status</th>
          <th scope="col">Note</th>
        </tr>
      </thead>
      <tbody ref={body}>
        {data.trips.map((t) => <TripRowView key={t.trip_id} trip={t} excluded={data.excluded_listings} search={search} />)}
      </tbody>
    </table>
  );
}

function TripRowView({ trip, excluded, search }: { trip: TripRow; excluded: TripsOut["excluded_listings"]; search: string }) {
  const status = tripStatus(trip, excluded);
  const note = tripNote(trip, excluded);
  const evaluated = trip.evaluated && trip.alt !== null;
  return (
    <tr>
      <th scope="row"><Link data-row-link to={{ pathname: `/trips/${encodeURIComponent(trip.trip_id)}`, search }}>{trip.symbol}&nbsp;·&nbsp;{trip.exchange}</Link></th>
      <td className="cell">{trip.open_session.display}</td>
      <td className="cell">{trip.close_session.display}</td>
      {evaluated && trip.alt ? (
        <>
          <td className="n cell"><Figure n={trip.actual_return} /></td>
          <td className="cell">{trip.alternatives_label}</td>
          <td className="n cell"><Figure n={trip.alt.percentile} /></td>
          <td className="m-line">
            <span className="l">Opened </span>{trip.open_session.display}<span className="sep">·</span>
            <span className="l">Closed </span>{trip.close_session.display}<span className="sep">·</span>
            <span className="l">Return </span>{trip.actual_return.display}<span className="sep">·</span>
            {trip.alternatives_label}<span className="sep">·</span>
            <span className="l">Percentile </span>{trip.alt.percentile.display}
          </td>
        </>
      ) : (
        <>
          <td className="n na-cell" colSpan={3}><Unavailable span /></td>
          <td className="m-line"><span className="l">Opened </span>{trip.open_session.display}<span className="sep">·</span><span className="l">Closed </span>{trip.close_session.display}</td>
        </>
      )}
      <td className="status"><StatusCode hold={status !== "EVALUATED"}>{status}</StatusCode></td>
      <td className="note">{note && <span className="reason">{note}</span>}</td>
    </tr>
  );
}

export function TripListScreen() {
  const { asOf, setAsOf, search } = useAsOf();
  const meta = useMeta();
  const trips = useTrips(asOf);
  const empty = trips.isSuccess && trips.data.trips.length === 0;
  const trades = useTrades(empty);
  useEffect(() => { document.title = "Trips · Alterfolio"; }, []);

  const notFinal = trips.error instanceof ApiError && trips.error.code === "as_of_not_sealed";
  const sample = trips.data?.summary.ALT.sample;
  return (
    <>
      <ChartHeader meta={meta.data} asOf={trips.data?.as_of} selected={asOf} onChange={setAsOf} />
      <div className="title"><h1>Trips</h1><span className="sub">Closed round trips, each compared with similar alternatives</span></div>
      <p className="lede">Each trip is compared with random portfolios built from alternatives, to show how much of the result could be chance.</p>

      {trips.isPending && <Skeleton />}
      {trips.isError && (notFinal
        ? <NotFinal onUseLatest={() => setAsOf(null)} latestDisplay={meta.data?.latest_sealed_as_of.display ?? null} />
        : <ErrorState error={trips.error} onRetry={() => void trips.refetch()} />)}

      {trips.isSuccess && (
        <>
          {sample && !sample.enough && !empty && (sample.have === null
            ? <div className="too-few"><strong>Trip comparison</strong><Unavailable /> <span>{trips.data.summary.trip_count_reason_text}</span></div>
            : <TooFew sampleText={sample.text} />)}
          {empty ? (
            trades.isSuccess && trades.data.length === 0 ? (
              <EmptyState title="No trades yet."><p><Link to={{ pathname: "/upload", search }}>Upload your first tradebook</Link> to see trips.</p></EmptyState>
            ) : (
              <EmptyState title="No closed trips yet."><p>Trips appear when a position is fully sold.</p></EmptyState>
            )
          ) : (
            <TripTable data={trips.data} search={search} />
          )}
          <section className="sec" aria-labelledby="h-care">
            <h2 id="h-care">Read with care</h2>
            <ul className="wide margin-list">
              <li>{trips.data.alternatives_note}</li>
              {trips.data.caveats.map((c) => <li key={c}>{c}</li>)}
              {trips.data.luck_limitations.map((c) => <li key={c}>{c}</li>)}
            </ul>
          </section>
          {trips.data.analysis_errors.length > 0 && (
            <section className="sec" aria-labelledby="h-errors">
              <h2 id="h-errors">Could not be worked out</h2>
              <ul className="wide margin-list">{trips.data.analysis_errors.map((e) => <li key={`${e.analysis}-${e.reason}`}>{e.reason_text}</li>)}</ul>
            </section>
          )}
          {trips.data.excluded_listings.length > 0 && (
            <section className="sec" aria-labelledby="h-excluded">
              <h2 id="h-excluded">Listings left out<span className="h-sub">Their trips are listed above and are not compared.</span></h2>
              <ul className="wide" style={{ margin: 0, paddingLeft: "var(--s-4)" }}>
                {trips.data.excluded_listings.map((e) => (
                  <li key={`${e.symbol}-${e.exchange}`}><b>{e.symbol} · {e.exchange}</b> {e.reason_text} ({e.trips} {e.trips === 1 ? "trip" : "trips"})</li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </>
  );
}
