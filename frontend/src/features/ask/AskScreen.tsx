import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../../shared/api/errors";
import { useAsk, useMeta } from "../../shared/api/queries";
import type { AskOut } from "../../shared/api/types";
import { StatusCode } from "../../shared/ui/StatusCode";
import { AnalystOffline, ErrorState, NotFinal } from "../../shared/ui/States";

const MAX_QUESTION = 2000;

/** Where a cited fact is shown: 006 = costs, 007 and 008 = trips and their regimes. A document chunk has no screen. */
function citationTarget(ref: string): string | null {
  if (ref.startsWith("006:")) return "/costs";
  if (ref.startsWith("007:") || ref.startsWith("008:")) return "/trips";
  return null;
}

function Answer({ answer }: { answer: AskOut }) {
  return (
    <section className="sec" aria-labelledby="h-answer">
      <h2 id="h-answer">Answer</h2>
      <div>
        <ul className="codes" aria-label="How this answer was made">
          {answer.answer_source === "template" && <li><StatusCode>Template answer</StatusCode></li>}
          {!answer.verified ? <li><StatusCode hold>Unverified: showing the raw facts</StatusCode></li> : <li><StatusCode>Numbers checked</StatusCode></li>}
        </ul>
        {!answer.verified && <p className="strip-note" style={{ marginBottom: "var(--s-3)" }}>The wording could not be checked against your numbers, so only the facts themselves are shown.</p>}
        <p style={{ whiteSpace: "pre-line", maxWidth: "70ch" }}>{answer.text}</p>
      </div>
      <aside className="margin" aria-label="Facts cited">
        <h3>Cited facts</h3>
        {answer.citations.length === 0 ? <p>None.</p> : (
          <ul className="chips">
            {answer.citations.map((c) => {
              const to = c.kind === "tool" ? citationTarget(c.ref) : null;
              return (
                <li key={`${c.kind}-${c.ref}`}>{to ? <Link className="chip" to={to}>{c.ref}</Link> : <span className="chip">{c.kind === "chunk" ? `Document ${c.ref}` : c.ref}</span>}</li>
              );
            })}
          </ul>
        )}
      </aside>
    </section>
  );
}

/** The analyst is optional: unavailable, slow or unreachable all collapse to one line and nothing else changes (spec 013 D4). */
const isOffline = (e: unknown) =>
  e instanceof DOMException || (e instanceof ApiError && (e.kind !== "client" || e.code === "ai_provider_not_configured"));

export function AskScreen() {
  const meta = useMeta();
  const ask = useAsk();
  const [question, setQuestion] = useState("");
  const [asOf, setAsOf] = useState<string | null>(null);
  useEffect(() => { document.title = "Ask · Alterfolio"; }, []);
  const sealed = meta.data?.latest_sealed_as_of;
  const date = asOf ?? sealed?.iso ?? "";

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (question.trim() && date) ask.mutate({ question, as_of: date });
  };
  const notFinal = ask.error instanceof ApiError && ask.error.code === "as_of_not_sealed";

  return (
    <>
      <div className="title"><h1>Ask</h1><span className="sub">Questions about your own numbers</span></div>
      <p className="lede">The analyst only explains numbers the app has already computed. It never produces a number of its own, and it does not give advice.</p>
      <form onSubmit={submit} aria-label="Ask the analyst">
        <p>
          <label htmlFor="question"><span className="k-label">Your question</span></label><br />
          <textarea id="question" rows={3} maxLength={MAX_QUESTION} value={question} disabled={ask.isPending} onChange={(e) => setQuestion(e.target.value)} className="ask-box" />
        </p>
        <p>
          <label htmlFor="ask-date"><span className="k-label">As of</span></label>{" "}
          <input id="ask-date" type="date" value={date} max={sealed?.iso} disabled={!sealed || ask.isPending} onChange={(e) => setAsOf(e.target.value || null)} />
          {date && <span className="fig"> {asOf && asOf !== sealed?.iso ? asOf : sealed?.display}</span>}
        </p>
        <p style={{ marginTop: "var(--s-4)" }}>
          <button type="submit" className="btn" disabled={!question.trim() || !date || ask.isPending}>{ask.isPending ? "Fetching market data and computing…" : "Ask"}</button>
        </p>
      </form>

      {ask.isPending && <p role="status" className="strip-note">Fetching market data and computing…</p>}
      {ask.isError && (isOffline(ask.error)
        ? <AnalystOffline />
        : notFinal
          ? <NotFinal onUseLatest={() => { setAsOf(null); ask.reset(); }} latestDisplay={sealed?.display ?? null} />
          : <ErrorState error={ask.error} />)}
      {ask.isSuccess && <Answer answer={ask.data} />}
    </>
  );
}
