import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../../shared/api/errors";
import { useImportStatus, useImportTradebook } from "../../shared/api/queries";
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
        <table role="table">
          <caption>What happened to each row in the file</caption>
          <tbody role="rowgroup">
            <tr role="row"><th role="rowheader" scope="row">Rows in the file</th><td role="cell" className="n">{result.total_rows}</td></tr>
            <tr role="row"><th role="rowheader" scope="row">Imported</th><td role="cell" className="n">{result.imported}</td></tr>
            <tr role="row"><th role="rowheader" scope="row">Already imported</th><td role="cell" className="n">{result.duplicates}</td></tr>
            <tr role="row"><th role="rowheader" scope="row">Rejected</th><td role="cell" className="n">{result.rejected_total}</td></tr>
          </tbody>
        </table>
        {oversold && <OversellNote />}
        {result.rejected.length > 0 && (
          <table role="table" style={{ marginTop: "var(--s-5)" }}>
            <caption>
              Rejected rows{result.rejected_text ? `: ${result.rejected_text}` : ""}
            </caption>
            <thead role="rowgroup"><tr role="row"><th role="columnheader" scope="col" className="n">Line</th><th role="columnheader" scope="col">Code</th><th role="columnheader" scope="col">Message</th></tr></thead>
            <tbody role="rowgroup">
              {result.rejected.map((r) => (
                <tr role="row" key={`${r.row}-${r.code}`}>
                  <td role="cell" className="n">{r.row}</td>
                  <td role="cell"><StatusCode hold>{r.code}</StatusCode></td>
                  <td role="cell" className="reason">{r.message}</td>
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

/** Past uploads, from the ledger's own record. Rejected rows are counted, not stored, so their list exists only at upload time. */
function PreviousUploads() {
  const status = useImportStatus();
  const batches = status.data?.batches ?? [];
  if (batches.length === 0) return null;
  return (
    <section className="sec" id="previous" aria-labelledby="h-previous">
      <h2 id="h-previous">Previous uploads<span className="h-sub">{status.data?.warning ?? "No rows were rejected."}</span></h2>
      <table role="table">
        <caption>Newest first. The rows that were rejected are listed only in the result shown right after an upload.</caption>
        <thead role="rowgroup">
          <tr role="row">
            <th role="columnheader" scope="col">File</th><th role="columnheader" scope="col">Uploaded</th><th role="columnheader" scope="col" className="n">Rows</th>
            <th role="columnheader" scope="col" className="n">Imported</th><th role="columnheader" scope="col" className="n">Already imported</th><th role="columnheader" scope="col" className="n">Rejected</th>
          </tr>
        </thead>
        <tbody role="rowgroup">
          {batches.map((b) => (
            <tr role="row" key={b.import_batch_id}>
              <th role="rowheader" scope="row">{b.file_name}</th>
              <td role="cell" className="cell">{b.created_at_display}</td>
              <td role="cell" className="n cell">{b.total_rows}</td>
              <td role="cell" className="n cell">{b.imported}</td>
              <td role="cell" className="n cell">{b.duplicates}</td>
              <td role="cell" className="n val">{b.rejected_total}{b.superseded && b.rejected_total > 0 ? " (replaced by a newer upload of this file)" : ""}</td>
              <td role="cell" className="m-line">{b.created_at_display}<span className="sep">·</span>{b.imported} imported<span className="sep">·</span>{b.duplicates} already imported<span className="sep">·</span>{b.rejected_total} rejected</td>
            </tr>
          ))}
        </tbody>
      </table>
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
      <PreviousUploads />
    </>
  );
}
