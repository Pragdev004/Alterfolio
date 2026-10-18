import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

// Spec 013 A1 / design section 7: the frontend never formats or computes a number. Render the server's `display` string.
const FORMAT = "Numbers are formatted by the server: render the response's `display` field instead.";
const noFormatting = [
  { selector: "CallExpression[callee.property.name='toFixed']", message: FORMAT },
  { selector: "CallExpression[callee.property.name='toLocaleString']", message: FORMAT },
  { selector: "CallExpression[callee.property.name='toPrecision']", message: FORMAT },
  { selector: "MemberExpression[object.name='Intl'][property.name='NumberFormat']", message: FORMAT },
  { selector: "CallExpression[callee.name='parseFloat']", message: FORMAT },
  { selector: "CallExpression[callee.name='parseInt']", message: FORMAT },
  { selector: "CallExpression[callee.object.name='Number'][callee.property.name='parseFloat']", message: FORMAT },
  { selector: "CallExpression[callee.name='Number']", message: "Number() may only place marks, in src/shared/ui/geometry.ts." },
];

export default tseslint.config(
  { ignores: ["dist", "src/shared/api/schema.d.ts", "test-results", "playwright-report"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx,mjs}"],
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
    plugins: { "react-hooks": reactHooks },
    rules: { ...reactHooks.configs.recommended.rules, "no-restricted-syntax": ["error", ...noFormatting] },
  },
  // Geometry places marks from a `value`; the text beside every mark is still the server's `display`.
  { files: ["src/shared/ui/geometry.ts"], rules: { "no-restricted-syntax": ["error", ...noFormatting.slice(0, -1)] } },
  // Tests may read numbers to assert on them.
  { files: ["**/*.test.{ts,tsx}", "src/test/**", "e2e/**", "scripts/**"], rules: { "no-restricted-syntax": "off" } },
);
