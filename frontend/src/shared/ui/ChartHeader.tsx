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
  const showBar = meta?.last_bar_date && asOf && sealed && asOf.iso === sealed.iso;
  return (
    <div className="chart-head" role="group" aria-label="Data as of">
      <span><span className="k">Chart prepared</span><span className="fig">{asOf?.display ?? sealed?.display ?? "…"}</span></span>
      {showBar && meta?.last_bar_date && <span><span className="k">Latest bar</span><span className="fig">{meta.last_bar_date.display}</span></span>}
      <span>Data after this date is not used.</span>
      <span className="spacer" />
      <label>
        <span className="k">Change date</span>
        <input type="date" value={asOf?.iso ?? sealed?.iso ?? ""} max={sealed?.iso} disabled={!sealed} onChange={(e) => e.target.value && onChange(e.target.value)} />
      </label>
    </div>
  );
}
