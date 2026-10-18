import { useLayoutEffect, useRef, useState } from "react";

import type { Histogram as HistogramData } from "../api/types";
import { Unavailable } from "./Figure";
import { barHeight, place } from "./geometry";

const HEIGHT = 170, TOP = 28, BASE = 128;

/** Hand-built SVG of the drawn portfolios' returns in the server's bins. Bar heights are counts; the dashed line is the trip's
 *  own return. The server's text equivalent is visible under the chart, and every bar has a title. */
export function Histogram({ data }: { data: HistogramData }) {
  const host = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(680);
  useLayoutEffect(() => {
    const el = host.current;
    if (!el) return;
    const fit = () => setWidth(Math.min(680, Math.max(280, el.clientWidth || 680)));
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const lo = data.lower.value, hi = data.upper.value, actual = data.actual_return.value;
  if (lo === null || hi === null || actual === null || data.bins.length === 0) {
    const why = data.actual_return.reason_text ?? data.lower.reason_text ?? data.upper.reason_text ?? "The chart could not be drawn.";
    return <p><Unavailable /> <span className="reason">{why}</span></p>;
  }
  const n = data.bins.length;
  const bw = width / n;
  const maxCount = Math.max(...data.bins.map((b) => b.count));
  const mx = Math.min(width, Math.max(0, place(actual, lo, hi, width)));
  const anchor = mx > width - 110 ? "end" : mx < 90 ? "start" : "middle";
  return (
    <div ref={host}>
      <svg className="hist" viewBox={`0 0 ${width} ${HEIGHT}`} role="img" aria-label={`Histogram of ${data.portfolio_count} drawn portfolio returns from ${data.lower.display} to ${data.upper.display}. ${data.text}`}>
        {data.bins.map((b, i) => {
          const h = barHeight(b.count, maxCount, BASE - TOP);
          const cls = i < data.marker_bin ? "bar less" : i === data.marker_bin ? "bar you" : "bar";
          return (
            <rect key={i} className={cls} x={i * bw + 0.5} y={BASE - h} width={bw - 1} height={h}>
              <title>{`${b.lower.display} to ${b.upper.display}: ${b.count} portfolios`}</title>
            </rect>
          );
        })}
        <line className="base" x1={0} x2={width} y1={BASE} y2={BASE} />
        <line className="you-line" x1={mx} x2={mx} y1={TOP - 8} y2={BASE + 6} />
        <text className="you-lbl" x={mx} y={TOP - 12} textAnchor={anchor}>{`Your trip ${data.actual_return.display}`}</text>
        <text x={0} y={BASE + 22} textAnchor="start">{data.lower.display}</text>
        <text x={width / 2} y={BASE + 22} textAnchor="middle">Return of a random portfolio</text>
        <text x={width} y={BASE + 22} textAnchor="end">{data.upper.display}</text>
      </svg>
      <ul className="legend">
        <li><i />Portfolios that returned less than your trip</li>
        <li><i className="you" />The bin holding your trip</li>
        <li><i className="rest" />Portfolios that returned more</li>
      </ul>
      <p className="strip-note">{data.text}</p>
    </div>
  );
}
