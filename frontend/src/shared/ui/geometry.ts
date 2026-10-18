/** The only place a response `value` becomes a number: to place a mark. Text beside a mark is always the server's `display`. */

export const toCoordinate = (value: string): number => Number(value);

/** Position of `value` between `lo` and `hi`, 0..width. */
export function place(value: string, lo: string, hi: string, width: number): number {
  const a = toCoordinate(lo);
  const span = toCoordinate(hi) - a;
  return span === 0 ? 0 : ((toCoordinate(value) - a) / span) * width;
}

/** Bar height for a count, 0..max height. */
export const barHeight = (count: number, maxCount: number, maxHeight: number): number => (maxCount === 0 ? 0 : (count / maxCount) * maxHeight);

export interface BandSegments {
  low: [number, number];
  normal: [number, number];
  high: [number, number];
  marker: number;
}

/** Volatility band layout: LOW below the low threshold, HIGH above the high one; the scale ends at 1.5x the high threshold. */
export function band(volatility: string, low: string, high: string, width: number): BandSegments {
  const top = toCoordinate(high) * 1.5;
  const x = (v: number) => (Math.min(v, top) / top) * width;
  const lo = x(toCoordinate(low));
  const hi = x(toCoordinate(high));
  return { low: [0, lo], normal: [lo, hi], high: [hi, width], marker: x(toCoordinate(volatility)) };
}
