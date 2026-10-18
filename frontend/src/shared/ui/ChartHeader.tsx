import type { DateOut, MetaOut } from "../api/types";

interface Props {
  meta: MetaOut | undefined;
  /** The as-of the page is showing (the response's own date, so the header never claims a date the data does not have). */
  asOf: DateOut | undefined;
  onChange: (iso: string) => void;
}

/** "Chart prepared 30 Nov 2026 · latest bar 30 Nov 2026 · Data after this date is not used." plus the date picker. */
export function ChartHeader({ meta, asOf, onChange }: Props) {
  const sealed = meta?.latest_sealed_as_of;
  const bar = meta?.last_bar_date;
  const barText = !meta || bar ? null : (meta.last_bar_date_reason_text ?? "No price data yet.");
  const showBar = bar && asOf && sealed && asOf.iso === sealed.iso;
  return (
    <div className="chart-head" role="group" aria-label="Data as of">
      <span><span className="k">Chart prepared</span><span className="fig">{asOf?.display ?? sealed?.display ?? "…"}</span></span>
      {showBar && bar && <span><span className="k">Latest bar</span><span className="fig">{bar.display}</span></span>}
      {barText && <span><span className="k">Latest bar</span><span className="fig">{barText}</span></span>}
      <span>Data after this date is not used.</span>
      <span className="spacer" />
      <label className="picker">
        <span className="k">Change date</span>
        <input type="date" value={asOf?.iso ?? sealed?.iso ?? ""} max={sealed?.iso} disabled={!sealed} onChange={(e) => e.target.value && onChange(e.target.value)} />
      </label>
      {/* the native input shows the browser's own format (MM/DD in some locales); the server's date sits beside it */}
      {asOf && <span className="fig picked" data-testid="picked-date">{asOf.display}</span>}
    </div>
  );
}
