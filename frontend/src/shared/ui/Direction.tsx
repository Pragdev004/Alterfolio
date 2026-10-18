/** Direction as a word and a drawn mark; colour is never the only carrier. "inconclusive" and "level" get no arrow and no colour. */
export function Direction({ direction, text }: { direction: string | null; text?: string | null }) {
  if (direction === null) return null;
  if (direction === "ahead" || direction === "behind") {
    const up = direction === "ahead";
    return (
      <span className={`dir ${direction}`}>
        <svg viewBox="0 0 10 10" aria-hidden="true">
          <path d={up ? "M5 1 L9.5 9 L0.5 9 Z" : "M5 9 L9.5 1 L0.5 1 Z"} fill="currentColor" />
        </svg>
        {text ?? direction}
      </span>
    );
  }
  return <span className="dir">{text ?? direction}</span>;
}
