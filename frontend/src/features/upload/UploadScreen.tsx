import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../../shared/api/errors";
import { useImportTradebook } from "../../shared/api/queries";
import type { ImportResult } from "../../shared/api/types";
import { StatusCode } from "../../shared/ui/StatusCode";
import { ErrorState } from "../../shared/ui/States";

const MAX_BYTES = 2 * 1024 * 1024; // the server enforces the same limit while streaming
const OVERSELL = new Set(["oversell", "after_oversell"]);

function OversellNote() {
  return (
    <div className="state" role="note">
      <h2>A sell in this file has no earlier buy.</h2>
      <p>
        Your ledger is long-only, so a sell can only be recorded after the buy it closes. The file was checked against everything you
        have already uploaded and those rows were left out.
      </p>
      <p>Upload your oldest tradebook first, then upload this one again.</p>
    </div>
  );
}

function Summary({ result }: { result: ImportResult }) {
  const oversold = result.rejected.some((r) => OVERSELL.has(r.code));
  return (
    <section className="sec" aria-labelledby="h-result">
      <h2 id="h-result">Import result<span className="h-sub">{result.file_name}</span></h2>
      <div>
        <table>
          <caption>What happened to each row in the file</caption>
          <tbody>
            <tr><th scope="row">Rows in the file</th><td className="n">{result.total_rows}</td></tr>
            <tr><th scope="row">Imported</th><td className="n">{result.imported}</td></tr>
            <tr><th scope="row">Already imported</th><td className="n">{result.duplicates}</td></tr>
            <tr><th scope="row">Rejected</th><td className="n">{result.rejected_total}</td></tr>
          </tbody>
        </table>
        {oversold && <OversellNote />}
        {result.rejected.length > 0 && (
          <table style={{ marginTop: "var(--s-5)" }}>
            <caption>
              Rejected rows{result.rejected_total > result.rejected.length ? `: the first ${result.rejected.length} of ${result.rejected_total}` : ""}
            </caption>
            <thead><tr><th scope="col" className="n">Line</th><th scope="col">Code</th><th scope="col">Message</th></tr></thead>
            <tbody>
              {result.rejected.map((r) => (
                <tr key={`${r.row}-${r.code}`}>
                  <td className="n">{r.row}</td>
                  <td><StatusCode hold>{r.code}</StatusCode></td>
                  <td className="reason">{r.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p style={{ marginTop: "var(--s-5)" }}>
          <Link to="/trips">See your trips</Link> · <Link to="/holdings">See your holdings</Link>
        </p>
      </div>
      <aside className="margin" aria-label="Notes on this import">
        <h3>Read with care</h3>
        <ul>
          <li>{result.fees_taxes_provided ? "Fees and taxes were provided in this file." : "Charges are unknown, not zero: this file has no fees or taxes, so none are assumed."}</li>
          {result.quarantined_isins.length > 0 && (
            <li><b>Set aside:</b> {result.quarantined_isins.join(", ")}. Later rows for these ISINs were not imported until the earlier buys exist.</li>
          )}
        </ul>
      </aside>
    </section>
  );
}

export function UploadScreen() {
  const [file, setFile] = useState<File | null>(null);
  const [tooBig, setTooBig] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const upload = useImportTradebook();
  useEffect(() => { document.title = "Upload · Alterfolio"; }, []);

  const choose = (picked: File | null) => {
    upload.reset();
    setTooBig(picked !== null && picked.size > MAX_BYTES);
    setFile(picked);
  };
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (file && !tooBig) upload.mutate(file);
  };
  const oversellError = upload.error instanceof ApiError && upload.error.code === "oversell";

  return (
    <>
      <div className="title"><h1>Upload</h1><span className="sub">Add a Zerodha tradebook CSV</span></div>
      <p className="lede"><strong>Upload your oldest tradebook first.</strong> A sell is only accepted after the buy it closes, so older files go in before newer ones.</p>

      <form onSubmit={submit} aria-label="Upload a tradebook">
        <p>
          <label htmlFor="tradebook"><span className="k-label">Tradebook CSV</span></label><br />
          <input id="tradebook" ref={input} type="file" accept=".csv,text/csv" disabled={upload.isPending} onChange={(e) => choose(e.target.files?.[0] ?? null)} />
        </p>
        {file && <p className="strip-note">Selected: {file.name} · {file.size} bytes</p>}
        {tooBig && <p role="alert">This file is larger than 2 MiB, which is the most the server accepts. Split it by period and upload the older part first.</p>}
        <p style={{ marginTop: "var(--s-4)" }}>
          <button type="submit" className="btn" disabled={!file || tooBig || upload.isPending}>{upload.isPending ? "Importing…" : "Import tradebook"}</button>
        </p>
      </form>
      {upload.isPending && <p role="status" className="strip-note">Importing…</p>}

      {upload.isError && (
        <ErrorState error={upload.error} onRetry={() => file && upload.mutate(file)}>
          {oversellError && <OversellNote />}
        </ErrorState>
      )}
      {upload.isSuccess && <Summary result={upload.data} />}
    </>
  );
}
