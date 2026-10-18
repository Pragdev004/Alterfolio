import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";

/** `?as_of=` is URL state, so any view is linkable and printable. null = the server's latest sealed day (never today). */
export function useAsOf() {
  const [params, setParams] = useSearchParams();
  const asOf = params.get("as_of");
  const setAsOf = useCallback(
    (iso: string | null) =>
      setParams((current) => {
        const next = new URLSearchParams(current);
        if (iso) next.set("as_of", iso);
        else next.delete("as_of");
        return next;
      }),
    [setParams],
  );
  const search = asOf ? `?as_of=${encodeURIComponent(asOf)}` : "";
  return { asOf, setAsOf, search };
}
