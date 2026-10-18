// Spec 013 A1: no money or percentage is formatted in frontend code. Two guards: a source scan and the ESLint rule itself.
import { ESLint } from "eslint";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(process.cwd(), "src");
const FORBIDDEN = [/\.toFixed\(/, /\.toLocaleString\(/, /\.toPrecision\(/, /Intl\.NumberFormat/, /\bparseFloat\(/, /\bparseInt\(/];

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === "test" || name === "fixtures" ? [] : sources(path);
    return /\.(ts|tsx)$/.test(name) && !/\.test\.|schema\.d\.ts$/.test(name) ? [path] : [];
  });
}

describe("no number formatting in the frontend", () => {
  it("no source file formats or parses a number", () => {
    for (const file of sources(SRC)) {
      const text = readFileSync(file, "utf8");
      for (const pattern of FORBIDDEN) expect(text, `${file} matches ${pattern}`).not.toMatch(pattern);
    }
  });

  it("Number() is confined to the geometry module", () => {
    for (const file of sources(SRC).filter((f) => !f.endsWith("geometry.ts"))) {
      expect(readFileSync(file, "utf8"), file).not.toMatch(/\bNumber\(/);
    }
  });

  it("the ESLint rule rejects each forbidden call", async () => {
    const eslint = new ESLint({ cwd: process.cwd() });
    for (const code of ["const a = x.toFixed(2);", "const a = new Intl.NumberFormat('en-IN');", "const a = parseFloat(x);", "const a = x.toLocaleString();", "const a = Number(x);"]) {
      const [result] = await eslint.lintText(code, { filePath: "src/features/example.ts" });
      expect(result?.messages.some((m) => m.ruleId === "no-restricted-syntax"), code).toBe(true);
    }
    const [geometry] = await eslint.lintText("const a = Number(x);", { filePath: "src/shared/ui/geometry.ts" });
    expect(geometry?.messages.filter((m) => m.ruleId === "no-restricted-syntax")).toHaveLength(0);
  });
});
