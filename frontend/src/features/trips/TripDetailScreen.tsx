import { useEffect } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { useAsOf } from "../../app/useAsOf";
import { ApiError } from "../../shared/api/errors";
import { useMeta, useRegimes, useTrips, useTripDetail } from "../../shared/api/queries";
import type { BaselineSummary, Outcome, RegimeTag, TripDetailRow } from "../../shared/api/types";
import { ChartHeader } from "../../shared/ui/ChartHeader";
import { Direction } from "../../shared/ui/Direction";
import { Figure, Unavailable } from "../../shared/ui/Figure";
import { Histogram } from "../../shared/ui/Histogram";
import { TooFew } from "../../shared/ui/SampleSentence";
import { StatusCode } from "../../shared/ui/StatusCode";
import { EmptyState, ErrorState, NotFinal, Skeleton } from "../../shared/ui/States";
import { VolatilityBand } from "../../shared/ui/VolatilityBand";

const bandReady = (r: RegimeTag) => Boolean(r.regime) && r.volatility.value !== null && r.low_threshold.value !== null && r.high_threshold.value !== null;
const POSITION: Record<string, string> = { CONTAINS_ZERO: "across zero", ABOVE_ZERO: "above zero", BELOW_ZERO: "below zero" };

function dropped(count: number | null): string | null {
  return count ? `${count} ${count === 1 ? "alternative" : "alternatives"} dropped` : null;
}

function Result({ trip }: { trip: TripDetailRow }) {
  const alt = trip.alt;
  if (!trip.evaluated || !alt || alt.percentile.value === null) {
    return (
      <div>
        <p className="result"><Unavailable /></p>
        <p className="strip-note">{trip.reason_text ?? alt?.reason_text ?? "This trip was not compared."}</p>
      </div>
    );
  }
  const hist = trip.histograms.ALT;
  return (
    <div>
      <p className="result">
        Your return of <span className="fig">{trip.actual_return.display}</span> was higher than <span className="fig">{alt.percentile.display}</span> of
        the {alt.portfolios_text}.
      </p>
      {hist && <Histogram data={hist} />}
    </div>
  );
}

function BaselineRow({ name, o }: { name: string; o: Outcome | null }) {
  if (!o) return null;
  const na = o.unavailable_reason !== null;
  const lost = dropped(o.lost_count);
  return (
    <tr>
      <th scope="row">{name}</th>
      {na ? (
        <td className="n na-cell" colSpan={4}><Unavailable span /></td>
      ) : (
        <>
          <td className="n cell"><Figure n={o.mean_return} /></td>
          <td className="n cell"><span className="nb"><Figure n={o.excess} strong /> <Direction direction={o.excess_direction} /></span></td>
          <td className="n cell"><Figure n={o.percentile} /></td>
          <td className="cell">{o.portfolios_text}</td>
          <td className="m-line">
            <span className="l">Mean </span>{o.mean_return.display}<span className="sep">·</span>
            <span className="l">Excess </span>{o.excess.display} <Direction direction={o.excess_direction} /><span className="sep">·</span>
            <span className="l">Percentile </span>{o.percentile.display}<span className="sep">·</span>
            {o.portfolios_text}
          </td>
        </>
      )}
      <td className="status"><StatusCode hold={na}>{na ? "Unavailable" : "Evaluated"}</StatusCode></td>
      <td className="note">{na ? <span className="reason">{o.reason_text}</span> : lost && <span className="reason">{lost}.</span>}</td>
    </tr>
  );
}

function AcrossTrips({ summary, reason }: { summary: BaselineSummary; reason: string | null }) {
  if (!summary.sample.enough) {
    return summary.sample.have === null
      ? <div className="too-few"><strong>Across your trips</strong><Unavailable /> <span>{reason ?? summary.ci_lower.reason_text}</span></div>
      : <TooFew sampleText={summary.sample.text} />;
  }
  const where = summary.position ? POSITION[summary.position] : undefined;
  return (
    <>
      <dl className="facts">
        <div><dt>Mean excess</dt><dd><Figure n={summary.mean_excess} /> <Direction direction={summary.mean_excess_direction} text={summary.mean_excess_direction_text} /></dd></div>
        <div><dt>Interval low</dt><dd><Figure n={summary.ci_lower} /></dd></div>
        <div><dt>Interval high</dt><dd><Figure n={summary.ci_upper} /></dd></div>
      </dl>
      <p className="hedge">
        Across {summary.trips_used} trips{where ? ` the interval sits ${where}` : ""}. Heuristic on a small sample, not proof of skill or luck.
      </p>
    </>
  );
}

export function TripDetailScreen() {
  const { tripId = "" } = useParams();
  const { asOf, setAsOf, search } = useAsOf();
  const navigate = useNavigate();
  const meta = useMeta();
  const detail = useTripDetail(tripId, asOf);
  const trips = useTrips(asOf);
  const regimes = useRegimes(asOf);
  const trip = detail.data?.trip;

  useEffect(() => { document.title = trip ? `${trip.symbol} trip · Alterfolio` : "Trip · Alterfolio"; }, [trip]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !(e.target as HTMLElement).closest("input, select, textarea")) navigate({ pathname: "/trips", search });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate, search]);

  const error = detail.error;
  const notFinal = error instanceof ApiError && error.code === "as_of_not_sealed";
  const notFound = error instanceof ApiError && error.code === "analysis_trip_not_found";
  const left = trip?.exclusions ?? [];
  const block = trip?.regime.regime ? regimes.data?.blocks.find((b) => b.regime === trip.regime.regime) : undefined;
  const alternativesNote = detail.data?.alternatives_note;

  return (
    <>
      <ChartHeader meta={meta.data} asOf={detail.data?.as_of} selected={asOf} onChange={setAsOf} />
      <p style={{ marginTop: "var(--s-4)" }}><Link to={{ pathname: "/trips", search }}>← All trips</Link></p>

      {detail.isPending && <Skeleton />}
      {detail.isError && (notFinal
        ? <NotFinal onUseLatest={() => setAsOf(null)} latestDisplay={meta.data?.latest_sealed_as_of.display ?? null} />
        : notFound
          ? <EmptyState title="That trip is not in your analysis."><p>It may belong to a different date. <Link to={{ pathname: "/trips", search }}>Back to the list</Link>.</p></EmptyState>
          : <ErrorState error={error} onRetry={() => void detail.refetch()} />)}

      <header>
        <div className="title"><h1>{trip ? trip.symbol : "Trip"}</h1>{trip && <span className="sub">{trip.exchange} · {trip.open_session.display} to {trip.close_session.display}</span>}</div>
        {trip && (
          <ul className="codes" aria-label="Status">
              <li><StatusCode hold={!trip.evaluated}>{trip.evaluated ? "Evaluated" : "Not evaluated"}</StatusCode></li>
              {trip.regime.regime && <li><StatusCode>{`Regime ${trip.regime.regime}`}</StatusCode></li>}
              {trip.survivorship_flag && <li><StatusCode hold>{trip.alt && dropped(trip.alt.lost_count) ? `Survivorship: ${dropped(trip.alt.lost_count)}` : "Survivorship flag"}</StatusCode></li>}
            </ul>
        )}
      </header>

      {trip && detail.data && (
        <>

          <section className="sec" aria-labelledby="h-result">
            <h2 id="h-result">How this trip compares</h2>
            <Result trip={trip} />
            <aside className="margin" aria-label="Notes on this result">
              <h3>Read with care</h3>
              <ul>
                {alternativesNote && <li>{alternativesNote}</li>}
                {detail.data.caveats.map((c) => <li key={c}>{c}</li>)}
              </ul>
            </aside>
          </section>

          <section className="sec" aria-labelledby="h-base">
            <h2 id="h-base">Against each baseline<span className="h-sub">{alternativesNote}</span></h2>
            <p className="strip-note wide" style={{ marginBottom: "var(--s-4)" }}>
              Your return is <Figure n={trip.actual_return} strong /> in both rows; each row compares it with random portfolios from a different pool.
            </p>
            <div className="wide">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Baseline</th><th scope="col" className="n">Alternatives’ mean</th><th scope="col" className="n">Excess</th>
                    <th scope="col" className="n">Percentile</th><th scope="col">Portfolios</th><th scope="col">Status</th><th scope="col">Note</th>
                  </tr>
                </thead>
                <tbody>
                  <BaselineRow name={trip.alternatives_label ?? "Alternatives"} o={trip.alt} />
                  <BaselineRow name="Nifty 50 random portfolios" o={trip.nifty} />
                </tbody>
              </table>
            </div>
          </section>

          <section className="sec" aria-labelledby="h-picks">
            <h2 id="h-picks">Alternatives picked<span className="h-sub">{trip.picks.length} picked and {left.length} left out. Returns are over the same dates as your trip.</span></h2>
            <div>
              {trip.picks.length === 0 ? <p className="strip-note">No alternatives were picked for this trip.</p> : (
                <table>
                  <thead><tr><th scope="col">Listing</th><th scope="col" className="n">Return over the trip</th><th scope="col">Note</th></tr></thead>
                  <tbody>
                    {trip.picks.map((p) => (
                      <tr key={`${p.symbol}-${p.exchange}`}>
                        <th scope="row">{p.rank}. {p.symbol} · {p.exchange}</th>
                        <td className="n val"><Figure n={p.return_ratio} /></td>
                        <td className="note">{p.return_ratio.value === null && <span className="reason">{p.return_ratio.reason_text} Dropped.</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
            <aside className="margin" aria-label="Alternatives left out">
              <h3>Left out</h3>
              {left.length === 0 ? <p>None.</p> : (
                <ul>{left.map((e) => <li key={`${e.baseline}-${e.isin}`}><b>{e.symbol ?? "A listing"}{e.exchange ? ` · ${e.exchange}` : ""}</b> {e.reason_text}</li>)}</ul>
              )}
            </aside>
          </section>

          <section className="sec" aria-labelledby="h-regime">
            <h2 id="h-regime">Volatility regime<span className="h-sub">Relative to this stock&apos;s own history before the trip opened.</span></h2>
            <div>
              {bandReady(trip.regime) ? <VolatilityBand regime={trip.regime} /> : (
                <p><Unavailable /> <span className="reason">{trip.regime.reason_text ?? trip.regime.volatility.reason_text ?? regimes.data?.reason_text ?? "No volatility reading for this trip."}</span></p>
              )}
              {regimes.isSuccess && regimes.data.analysis_errors.map((e) => <p key={`${e.analysis}-${e.reason}`} className="strip-note">{e.reason_text}</p>)}
              {regimes.isSuccess && (regimes.data.none_ready_text
                ? <TooFew headline={regimes.data.none_ready_text} sampleText="" />
                : block && !block.sample.enough && <TooFew headline="Not enough trips in this regime yet." sampleText={block.sample.text} />)}
              {regimes.isError && <ErrorState error={regimes.error} onRetry={() => void regimes.refetch()} />}
            </div>
            <aside className="margin" aria-label="Notes on regimes">
              <h3>Limits</h3>
              <ul>{(regimes.data?.limitations ?? []).map((c) => <li key={c}>{c}</li>)}</ul>
            </aside>
          </section>

          <section className="sec" aria-labelledby="h-all">
            <h2 id="h-all">Across all your trips</h2>
            <div>
              {trips.isPending && <Skeleton rows={2} />}
              {trips.isError && <ErrorState error={trips.error} onRetry={() => void trips.refetch()} />}
              {trips.isSuccess && <AcrossTrips summary={trips.data.summary.ALT} reason={trips.data.summary.trip_count_reason_text} />}
            </div>
            <aside className="margin" aria-label="Notes on the sample">
              <h3>Sample</h3>
              <ul>{trips.isSuccess && <li>{trips.data.summary.ALT.sample.have === null ? (trips.data.summary.trip_count_reason_text ?? "Unavailable") : trips.data.summary.ALT.sample.enough ? `${trips.data.summary.ALT.trips_used} trips in the interval` : trips.data.summary.ALT.sample.text}</li>}</ul>
            </aside>
          </section>
        </>
      )}
    </>
  );
}
