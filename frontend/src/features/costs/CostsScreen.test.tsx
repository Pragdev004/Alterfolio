import { screen, within } from "@testing-library/react";
import { http } from "msw";
import { describe, expect, it } from "vitest";

import { failWith, serve } from "../../test/handlers";
import { renderApp } from "../../test/render";
import { scenarios } from "../../test/fixtures";
import { server } from "../../test/server";

describe("Costs", () => {
  it("shows the three habits with the server's display strings and the unknown-fee count", async () => {
    serve("full");
    renderApp("/costs");
    const table = await screen.findByRole("table");
    for (const b of scenarios.full.biases.biases) {
      const name = { DISPOSITION: "Disposition", CHASING: "Chasing", OVERTRADING: "Overtrading" }[b.kind]!;
      const row = within(table).getByRole("rowheader", { name }).closest("tr")!;
      expect(row).toHaveTextContent(b.cost_inr.display);
      expect(within(row).getAllByRole("cell").some((c) => c.textContent === String(b.unknown_fee_trade_count))).toBe(true);
    }
  });

  it("an Unavailable gross cost is the word with its reason, never 0 (A2)", async () => {
    serve("full");
    renderApp("/costs");
    const row = (await screen.findByRole("rowheader", { name: "Chasing" })).closest("tr")!;
    expect(within(row).getAllByText("Unavailable", { selector: ".na" }).length).toBeGreaterThan(0);
    expect(row).toHaveTextContent(scenarios.full.biases.biases[1]!.gross_cost_inr.reason_text!);
  });

  it("explains every Unavailable figure in a row, including the fees known", async () => {
    serve("full");
    renderApp("/costs");
    const row = (await screen.findByRole("rowheader", { name: "Chasing" })).closest("tr")!;
    expect(row).toHaveTextContent(scenarios.full.biases.biases[1]!.fees_known.reason_text!);
    expect(row).toHaveTextContent("This habit's cost has no separate fee part.");
  });

  it("shows the archetype as a status code and its metrics labelled unitless", async () => {
    serve("full");
    renderApp("/costs");
    const section = (await screen.findByRole("heading", { name: "Habit profile" })).closest("section")!;
    expect(within(section).getByText("CHURNER")).toHaveClass("code");
    const metrics = scenarios.full.biases.profile.supporting_metrics;
    expect(within(section).getAllByText("(unitless)")).toHaveLength(metrics.length);
    expect(section).toHaveTextContent(metrics[0]!.display);
  });

  it("with no archetype shows Unavailable and the server's reason", async () => {
    serve("few");
    renderApp("/costs");
    const section = (await screen.findByRole("heading", { name: "Habit profile" })).closest("section")!;
    expect(within(section).getByText("Unavailable")).toBeInTheDocument();
    expect(section).toHaveTextContent(scenarios.few.biases.profile.reason_text!);
    expect(screen.getByText("7 trips · 10 needed")).toBeInTheDocument();
  });

  it("uses no advice wording", async () => {
    serve("full");
    renderApp("/costs");
    await screen.findByRole("table");
    expect(screen.queryByText(/\b(buy|sell|should|recommend)\b/i)).toBeNull();
  });

  it("422 not final offers the latest date; a server error offers retry", async () => {
    serve("full");
    server.use(http.get("*/api/analysis/biases", failWith.notSealed));
    const first = renderApp("/costs?as_of=2026-12-01");
    expect(await screen.findByText("Data for that date isn't final yet.")).toBeInTheDocument();
    first.unmount();
    server.use(http.get("*/api/analysis/biases", failWith.server));
    renderApp("/costs");
    expect(await screen.findByText("The server hit a problem.")).toBeInTheDocument();
  });

  it("shows the chart header and keeps ?as_of= for the request", async () => {
    const seen = serve("full");
    renderApp("/costs?as_of=2026-11-20");
    await screen.findByRole("table");
    expect(seen.asOf).toContain("2026-11-20");
    expect(screen.getByRole("group", { name: "Data as of" })).toBeInTheDocument();
  });
});
