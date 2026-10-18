import { useEffect } from "react";

import { useAsOf } from "../../app/useAsOf";
import { ApiError } from "../../shared/api/errors";
import { useBiases, useMeta } from "../../shared/api/queries";
import type { BiasOut } from "../../shared/api/types";
import { ChartHeader } from "../../shared/ui/ChartHeader";
import { Figure, Unavailable } from "../../shared/ui/Figure";
import { TooFew } from "../../shared/ui/SampleSentence";
import { StatusCode } from "../../shared/ui/StatusCode";
import { ErrorState, NotFinal, Skeleton } from "../../shared/ui/States";

const NAMES: Record<string, string> = { DISPOSITION: "Disposition", CHASING: "Chasing", OVERTRADING: "Overtrading" };

function Row({ b }: { b: BiasOut }) {
  const name = NAMES[b.kind] ?? b.kind;
  return (
    <tr>
      <th scope="row">{name}</th>
      <td className="n val"><Figure n={b.cost_inr} strong /></td>
      <td className="n cell"><Figure n={b.gross_cost_inr} /></td>
      <td className="n cell"><Figure n={b.fees_known} /></td>
      <td className="n cell">{b.unknown_fee_trade_count === null ? <Unavailable /> : b.unknown_fee_trade_count}</td>
      <td className="m-line">
        <span className="l">Gross </span>{b.gross_cost_inr.display}<span className="sep">·</span>
        <span className="l">Fees known </span>{b.fees_known.display}<span className="sep">·</span>
        <span className="l">Unknown-fee trades </span>{b.unknown_fee_trade_count ?? "Unavailable"}
      </td>
      <td className="note">
        {[...new Set([b.cost_inr, b.gross_cost_inr, b.fees_known].filter((n) => n.value === null && n.reason_text).map((n) => n.reason_text))].map((t) => (
          <span key={t} className="reason">{t} </span>
        ))}
        {b.exclusions.map((e) => <span key={`${e.subject}-${e.reason}`} className="reason"> {e.reason_text}</span>)}
      </td>
    </tr>
  );
}

export function CostsScreen() {
  const { asOf, setAsOf } = useAsOf();
  const meta = useMeta();
  const q = useBiases(asOf);
  useEffect(() => { document.title = "Costs · Alterfolio"; }, []);
  const notFinal = q.error instanceof ApiError && q.error.code === "as_of_not_sealed";
  const d = q.data;

  return (
    <>
      <ChartHeader meta={meta.data} asOf={d?.as_of} selected={asOf} onChange={setAsOf} />
      <div className="title"><h1>Costs</h1><span className="sub">What three trading habits cost, in rupees</span></div>
      <p className="lede">These are observations from your own ledger, each with the figures behind it. They are not instructions, and not proof of a cause.</p>

      {q.isPending && <Skeleton />}
      {q.isError && (notFinal
        ? <NotFinal onUseLatest={() => setAsOf(null)} latestDisplay={meta.data?.latest_sealed_as_of.display ?? null} />
        : <ErrorState error={q.error} onRetry={() => void q.refetch()} />)}

      {d && (
        <>
          {!d.sample.enough && (d.sample.have === null
            ? <div className="too-few"><strong>Habit sample</strong><Unavailable /> <span>{d.profile.reason_text}</span></div>
            : <TooFew sampleText={d.sample.text} headline="Not enough closed trips for a habit profile yet." />)}
          <section className="sec" aria-labelledby="h-costs">
            <h2 id="h-costs">Cost of each habit<span className="h-sub">Notes such as “lower bound” and “fees excluded” are the server’s, shown as it wrote them.</span></h2>
            <div className="wide">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Habit</th><th scope="col" className="n">Cost</th><th scope="col" className="n">Gross cost</th>
                    <th scope="col" className="n">Fees known</th><th scope="col" className="n">Trades with unknown fees</th><th scope="col">Note</th>
                  </tr>
                </thead>
                <tbody>{d.biases.map((b) => <Row key={b.kind} b={b} />)}</tbody>
              </table>
            </div>
          </section>

          <section className="sec" aria-labelledby="h-arch">
            <h2 id="h-arch">Habit profile</h2>
            <div>
              {d.profile.archetype_id
                ? <p><StatusCode>{d.profile.archetype_id.replaceAll("_", " ")}</StatusCode></p>
                : <p><Unavailable /> <span className="reason">{d.profile.reason_text}</span></p>}
              {d.profile.supporting_metrics.length > 0 && (
                <dl className="facts">
                  {d.profile.supporting_metrics.map((m) => (
                    <div key={m.name}><dt>{m.name.replaceAll("_", " ")}</dt><dd>{m.display}<span className="sub-fig reason"> ({m.unit})</span></dd></div>
                  ))}
                </dl>
              )}
            </div>
            <aside className="margin" aria-label="Notes on the profile">
              <h3>Read with care</h3>
              <ul>{d.caveats.map((c) => <li key={c}>{c}</li>)}</ul>
            </aside>
          </section>

          {d.analysis_errors.length > 0 && (
            <section className="sec" aria-labelledby="h-err">
              <h2 id="h-err">Could not be worked out</h2>
              <ul className="wide">{d.analysis_errors.map((e) => <li key={e.analysis}>{e.reason_text}</li>)}</ul>
            </section>
          )}
        </>
      )}
    </>
  );
}
