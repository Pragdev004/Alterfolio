import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { failWith, serve } from "../../test/handlers";
import { renderApp } from "../../test/render";
import { scenarios } from "../../test/fixtures";
import { server } from "../../test/server";

const partial = scenarios.holdings.summary!;
const valued = scenarios.valued.summary!;

describe("Holdings", () => {
  it("shows every figure as the server's display string", async () => {
    serve("valued");
    renderApp("/holdings");
    const table = await screen.findByRole("table");
    for (const h of valued.holdings) {
      const row = within(table).getByRole("rowheader", { name: new RegExp(h.listings[0]!.symbol) }).closest("tr")!;
      for (const text of [h.quantity_display, h.average_buy_price_display, h.invested_amount_display, h.market_value_display, h.unrealized_pnl_display]) {
        expect(row).toHaveTextContent(text);
      }
    }
    expect(within(table).getByText(valued.total_market_value_display, { selector: ".fig" })).toBeInTheDocument();
    expect(screen.getByText("COMPLETE")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Valuation" })).toHaveTextContent(valued.valuation_time_display);
  });

  it("a PARTIAL valuation says so in the totals, with the missing holding as the word Unavailable and its reason (A2)", async () => {
    serve("holdings");
    renderApp("/holdings");
    const table = await screen.findByRole("table");
    expect(screen.getByText("PARTIAL")).toBeInTheDocument();
    expect(screen.getAllByText(partial.valuation_text).length).toBeGreaterThanOrEqual(2); // the status line and the totals note
    const total = within(table).getByRole("rowheader", { name: "Total" }).closest("tr")!;
    expect(total).toHaveTextContent("(partial: 1 of 2 holdings valued)");
    const missing = partial.holdings.find((h) => h.market_value === null)!;
    const row = within(table).getByRole("rowheader", { name: new RegExp(missing.listings[0]!.symbol) }).closest("tr")!;
    expect(within(row).getAllByText("Unavailable").length).toBe(2);
    expect(row).toHaveTextContent(missing.market_value_unavailable_reason!);
    expect(row).not.toHaveTextContent(/₹0\.00/);
  });

  it("while prices load it shows the labelled skeleton, not an Unavailable table", async () => {
    serve("holdings");
    server.use(http.get("*/portfolio/summary", async () => {
      await new Promise((r) => setTimeout(r, 60));
      return HttpResponse.json(partial);
    }));
    renderApp("/holdings");
    expect(screen.getByRole("status")).toHaveTextContent("Fetching prices");
    expect(screen.queryByText("Prices have not loaded.")).toBeNull();
    await screen.findByRole("table");
    expect(screen.queryByText("Prices have not loaded.")).toBeNull();
  });

  it("no holdings teaches the next step", async () => {
    serve("empty");
    renderApp("/holdings");
    expect(await screen.findByText("Nothing is held right now.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "upload a tradebook" })).toHaveAttribute("href", "/upload");
  });

  it("when prices fail the ledger rows still show, with Unavailable valuation cells and an error that offers a retry", async () => {
    serve("holdings");
    server.use(http.get("*/portfolio/summary", failWith.server));
    renderApp("/holdings");
    expect(await screen.findByText("The server hit a problem.")).toBeInTheDocument();
    const table = await screen.findByRole("table");
    expect(within(table).getAllByText("Unavailable").length).toBe(scenarios.holdings.holdings!.length * 2);
    expect(table).toHaveTextContent("Prices have not loaded.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("an unreachable backend is the offline message", async () => {
    server.use(http.get("*/portfolio/summary", failWith.network), http.get("*/portfolio/holdings", failWith.network));
    renderApp("/holdings");
    expect(await screen.findByText("Cannot reach the server.")).toBeInTheDocument();
  });
});
