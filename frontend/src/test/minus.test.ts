// Every figure the server sends for people uses the true minus sign (U+2212), never a hyphen-minus.
import { describe, expect, it } from "vitest";

import { recordedAsk, scenarios } from "./fixtures";

function displays(node: unknown, path = "", out: [string, string][] = []): [string, string][] {
  if (Array.isArray(node)) node.forEach((v, i) => displays(v, `${path}[${i}]`, out));
  else if (node && typeof node === "object") {
    for (const [k, v] of Object.entries(node)) {
      if (typeof v === "string" && /display|text$/.test(k)) out.push([`${path}.${k}`, v]);
      else displays(v, `${path}.${k}`, out);
    }
  }
  return out;
}

describe("displayed figures", () => {
  it("never use a hyphen-minus as a sign", () => {
    const all = [...Object.values(scenarios).flatMap((s) => displays(s)), ...displays(recordedAsk)];
    expect(all.length).toBeGreaterThan(100);
    for (const [path, text] of all) expect(text, path).not.toMatch(/(^|[\s(])-[₹\d.]/);
  });

  it("do contain the true minus sign somewhere (the fixtures include a loss)", () => {
    const all = Object.values(scenarios).flatMap((s) => displays(s));
    expect(all.some(([, t]) => t.includes("−"))).toBe(true);
  });
});
