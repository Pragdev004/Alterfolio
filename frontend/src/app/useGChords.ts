import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

const TARGETS: Record<string, string> = { h: "/holdings", t: "/trips", c: "/costs", a: "/ask", u: "/upload" };
const WINDOW_MS = 1000;

/** `g` then h/t/c/a/u jumps to a screen. Optional: the rail links are always the primary path, and typing in a field is ignored. */
export function useGChords(enabled = true) {
  const navigate = useNavigate();
  useEffect(() => {
    if (!enabled) return;
    let armedAt = 0;
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (e.ctrlKey || e.metaKey || e.altKey || target?.closest("input, textarea, select, [contenteditable]")) return;
      if (e.key === "g") {
        armedAt = Date.now();
        return;
      }
      const to = TARGETS[e.key];
      if (to && Date.now() - armedAt < WINDOW_MS) navigate(to);
      armedAt = 0;
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled, navigate]);
}
