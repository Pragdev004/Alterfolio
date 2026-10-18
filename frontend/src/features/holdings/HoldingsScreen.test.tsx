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

  it("incomplete cost basis: P&L is the word Unavailable with the server's reason, and the chip is not COMPLETE", async () => {
    serve("imported");
    renderApp("/holdings");
    const table = await screen.findByRole("table");
    const imported = scenarios.imported.summary!;
    expect(imported.valuation_status).toBe("COMPLETE"); // prices are all there; it is the cost basis that is not
    expect(screen.queryByText("COMPLETE")).toBeNull();
    expect(screen.getByText("PARTIAL")).toBeInTheDocument();
    expect(screen.getByText(imported.status_text)).toBeInTheDocument();
    const h = imported.holdings[0]!;
    const row = within(table).getByRole("rowheader", { name: /TEST1/ }).closest("tr")!;
    expect(row).toHaveTextContent(h.market_value_display);
    expect(within(row).getAllByText("Unavailable").length).toBe(1); // P&L only
    expect(row).toHaveTextContent(h.unrealized_pnl_unavailable_reason!);
    const total = within(table).getByRole("rowheader", { name: "Total" }).closest("tr")!;
    expect(total).toHaveTextContent(imported.total_unrealized_pnl_unavailable_reason!);
  });

  it("rejected import rows are never silent: a warning that links to the upload results", async () => {
    serve("imported");
    renderApp("/holdings");
    const warning = await screen.findByRole("alert");
    expect(warning).toHaveTextContent("1 row was rejected at import; figures may be wrong");
    expect(within(warning).getByRole("link", { name: "See the upload results" })).toHaveAttribute("href", "/upload#previous");
  });

  it("no warning when nothing was rejected", async () => {
    serve("valued");
    renderApp("/holdings");
    await screen.findByRole("table");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("a failed refresh with figures on screen says when they are from, not 'Cannot reach the server'", async () => {
    serve("valued");
    const { client } = renderApp("/holdings");
    const table = await screen.findByRole("table");
    server.use(http.get("*/portfolio/summary", failWith.network));
    await client.refetchQueries({ queryKey: ["portfolio", "summary"] });
    const notice = await screen.findByText(/Couldn.t refresh\. Showing figures from \d\d:\d\d\./);
    expect(notice).toBeInTheDocument();
    expect(screen.queryByText("Cannot reach the server.")).toBeNull();
    expect(screen.getByRole("table")).toBe(table);
    expect(table).toHaveTextContent(valued.total_market_value_display);
  });

  it("with zero holdings there is no valuation status line", async () => {
    serve("empty");
    renderApp("/holdings");
    await screen.findByText("Nothing is held right now.");
    for (const word of ["COMPLETE", "PARTIAL", "UNAVAILABLE"]) expect(screen.queryByText(word)).toBeNull();
    expect(screen.queryByText(/holdings valued/)).toBeNull();
  });

  it("stacked mobile tables keep explicit table, row and cell roles", async () => {
    serve("valued");
    renderApp("/holdings");
    const table = await screen.findByRole("table");
    expect(within(table).getAllByRole("columnheader").length).toBeGreaterThan(0);
    expect(within(table).getAllByRole("row").length).toBeGreaterThan(1);
    expect(within(table).getAllByRole("cell").length).toBeGreaterThan(0);
    expect(table.querySelectorAll("tr:not([role=row]), td:not([role=cell]), th:not([role])").length).toBe(0);
  });
});
