import { useLayoutEffect, useRef, useState } from "react";

import type { RegimeTag } from "../api/types";
import { band } from "./geometry";

/** Low / normal / high volatility with the trip's own reading marked. Only drawn when the server has a regime for the trip. */
export function VolatilityBand({ regime }: { regime: RegimeTag }) {
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

  const { volatility, low_threshold: low, high_threshold: high } = regime;
  if (!regime.regime || volatility.value === null || low.value === null || high.value === null) return null;
  const b = band(volatility.value, low.value, high.value, width);
  const segments: [string, [number, number]][] = [["LOW", b.low], ["NORMAL", b.normal], ["HIGH", b.high]];
  return (
    <div ref={host}>
      <svg className="band" viewBox={`0 0 ${width} 84`} role="img" aria-label={`Volatility ${volatility.display}; low below ${low.display}, high above ${high.display}; regime ${regime.regime}`}>
        {segments.map(([name, [from, to]]) => (
          <g key={name}>
            <rect className={name === regime.regime ? "seg on" : "seg"} x={from} y={30} width={to - from} height={16} />
            <text x={(from + to) / 2} y={62} textAnchor="middle">{name}</text>
          </g>
        ))}
        <text x={b.normal[0]} y={80} textAnchor="middle">{low.display}</text>
        <text x={b.normal[1]} y={80} textAnchor="middle">{high.display}</text>
        <line className="mk" x1={b.marker} x2={b.marker} y1={22} y2={50} />
        <text className="lbl" x={b.marker} y={14} textAnchor="middle">{`Trip opened at ${volatility.display}`}</text>
      </svg>
    </div>
  );
}
