import type { NumberOut } from "../api/types";

/** The word "Unavailable" in its own cell: hatch and word, never a tint, never 0 or blank (spec 013 section 5). */
export function Unavailable({ span = false }: { span?: boolean }) {
  return <span className={span ? "na-span" : "na"}>Unavailable</span>;
}

/** A server number: its `display`, or the word Unavailable when the value is null. A genuine zero renders as the server's text. */
export function Figure({ n, strong = false }: { n: NumberOut; strong?: boolean }) {
  return n.value === null ? <Unavailable /> : <span className={strong ? "fig strong" : "fig"}>{n.display}</span>;
}

export const isUnavailable = (n: NumberOut | null | undefined): boolean => !n || n.value === null;

/** The plain sentence that explains an Unavailable number, hung beside it. */
export function Reason({ n }: { n: NumberOut }) {
  return n.value === null && n.reason_text ? <span className="reason">{n.reason_text}</span> : null;
}

/** A value that arrives as separate `x`, `x_display` and `x_unavailable_reason` fields (the older endpoints). Null is the word, not a blank. */
export function Shown({ value, display, strong = false }: { value: string | null; display: string; strong?: boolean }) {
  return value === null ? <Unavailable /> : <span className={strong ? "fig strong" : "fig"}>{display}</span>;
}
