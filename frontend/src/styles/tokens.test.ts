import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(join(process.cwd(), "src/styles/tokens.css"), "utf8");

function block(selector: string): Record<string, string> {
  const start = css.indexOf(selector + " {");
  const body = css.slice(css.indexOf("{", start) + 1, css.indexOf("}", start));
  return Object.fromEntries([...body.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-f]{6})/gi)].map((m) => [m[1]!, m[2]!]));
}

const channel = (v: number) => (v /= 255) <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
function luminance(hex: string) {
  const [r, g, b] = [1, 3, 5].map((i) => channel(parseInt(hex.slice(i, i + 2), 16)));
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
}
const ratio = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi! + 0.05) / (lo! + 0.05);
};

const light = block(":root");
const dark = { ...light, ...block(':root[data-theme="dark"]') };

// [foreground, background, minimum]: text >= 4.5, UI marks >= 3 (WCAG AA).
const PAIRS: [string, string, number][] = [
  ["ink", "paper", 4.5], ["ink-2", "paper", 4.5], ["ink-3", "paper", 4.5], ["ink-3", "paper-2", 4.5], ["ink-2", "paper-2", 4.5],
  ["ahead", "paper", 4.5], ["behind", "paper", 4.5], ["hold", "hold-wash", 4.5], ["ink", "hold-wash", 4.5], ["ahead", "ahead-wash", 4.5],
  ["behind", "behind-wash", 4.5], ["rule-ink", "paper", 3], ["focus", "paper", 3], ["ahead", "paper-2", 4.5],
];

describe.each([["light", light], ["dark", dark]] as const)("%s tokens meet WCAG AA", (_name, tokens) => {
  it.each(PAIRS)("%s on %s is at least %s:1", (fg, bg, min) => {
    expect(ratio(tokens[fg]!, tokens[bg]!)).toBeGreaterThanOrEqual(min);
  });
});
