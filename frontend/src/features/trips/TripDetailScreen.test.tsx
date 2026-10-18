import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { http, HttpResponse } from "msw";

import { failWith, serve } from "../../test/handlers";
import { server } from "../../test/server";
import { renderApp } from "../../test/render";
import { scenarios } from "../../test/fixtures";

const full = scenarios.full.trip!;
const path = (id: string) => `/trips/${id}`;

describe("Trip detail", () => {
  it("states the result in the server's words and shows the histogram with its text equivalent", async () => {
    serve("full");
    renderApp(path(full.trip.trip_id));
    const t = full.trip;
    const result = await screen.findByText(/Your return of/);
    expect(result).toHaveTextContent(`Your return of ${t.actual_return.display} was higher than ${t.alt!.percentile.display} of the ${t.alt!.portfolios_text}.`);
    const hist = t.histograms.ALT!;
    const img = screen.getByRole("img", { name: new RegExp(`Histogram of ${hist.portfolio_count} drawn portfolio returns`) });
    expect(img).toHaveAccessibleName(expect.stringContaining(hist.text));
    expect(screen.getAllByText(hist.text).length).toBeGreaterThan(0); // the visible text equivalent under the chart
    expect(img.querySelectorAll("rect")).toHaveLength(hist.bins.length);
    expect(img.querySelectorAll("rect title")).toHaveLength(hist.bins.length);
    expect(img.querySelector("rect.bar.you")).not.toBeNull();
  });

  it("shows the alternatives note on the luck view (A6) and the server caveats", async () => {
    serve("full");
    renderApp(path(full.trip.trip_id));
    await screen.findByText(/Your return of/);
    expect(screen.getAllByText("Same-sector or same-universe alternatives, not a prediction.").length).toBeGreaterThanOrEqual(2);
    for (const c of full.caveats) expect(screen.getByText(c)).toBeInTheDocument();
  });

  it("renders the Unavailable word and its reason for the Nifty baseline, never 0 or blank (A2)", async () => {
    serve("full");
    renderApp(path(full.trip.trip_id));
    const row = (await screen.findByRole("rowheader", { name: "Nifty 50 random portfolios" })).closest("tr")!;
    expect(within(row).getByText("Unavailable", { selector: ".na-span" })).toBeInTheDocument();
    expect(within(row).getByText(full.trip.nifty!.reason_text!)).toBeInTheDocument();
    expect(row).not.toHaveTextContent(/\b0(\.0+)?%/);
  });

  it("shows the alternatives row with excess, its direction word and the portfolios text", async () => {
    serve("full");
    renderApp(path(full.trip.trip_id));
    const o = full.trip.alt!;
    const row = (await screen.findByRole("rowheader", { name: full.trip.alternatives_label! })).closest("tr")!;
    expect(row).toHaveTextContent(o.excess.display);
    expect(within(row).getAllByText(o.excess_direction!).length).toBeGreaterThan(0);
    expect(row).toHaveTextContent(o.portfolios_text!);
  });

  it("lists picks and the alternatives left out with ticker and plain reason", async () => {
    serve("full");
    renderApp(path(full.trip.trip_id));
    await screen.findByRole("heading", { name: /Alternatives picked/ });
    for (const p of full.trip.picks) expect(screen.getByRole("rowheader", { name: new RegExp(`${p.symbol} · ${p.exchange}`) })).toBeInTheDocument();
    for (const e of full.trip.exclusions) expect(screen.getAllByText(e.reason_text!).length).toBeGreaterThan(0);
  });

  it("shows the volatility band for the trip's regime", async () => {
    serve("full");
    renderApp(path(full.trip.trip_id));
    const regime = full.trip.regime;
    const band = await screen.findByRole("img", { name: /Volatility/ });
    expect(band).toHaveAccessibleName(expect.stringContaining(`regime ${regime.regime}`));
    expect(screen.getByText(`Regime ${regime.regime}`)).toBeInTheDocument();
  });

  it("with enough trips: an interval across zero is 'not distinguishable from zero', with no arrow and no colour", async () => {
    serve("full");
    renderApp(path(full.trip.trip_id));
    const section = (await screen.findByRole("heading", { name: "Across all your trips" })).closest("section")!;
    const summary = scenarios.full.trips.summary.ALT;
    expect(summary.mean_excess_direction).toBe("inconclusive");
    const word = await within(section).findByText("not distinguishable from zero");
    expect(word.querySelector("svg")).toBeNull();
    expect(word).not.toHaveClass("ahead");
    expect(word).not.toHaveClass("behind");
    expect(section).toHaveTextContent(summary.ci_lower.display);
    expect(section).toHaveTextContent(summary.ci_upper.display);
    expect(section).toHaveTextContent("not proof of skill or luck");
  });

  it("with too few trips shows the server's sample text instead of an interval (A3)", async () => {
    serve("few");
    renderApp(path(scenarios.few.trip!.trip.trip_id));
    const section = (await screen.findByRole("heading", { name: "Across all your trips" })).closest("section")!;
    expect(await within(section).findByText("Not enough closed trips to say anything yet.")).toBeInTheDocument();
    expect(section).toHaveTextContent("7 trips · 10 needed");
    expect(within(section).queryByText(/Interval/)).toBeNull();
  });

  it("says the regime sentence from the server when no regime has enough trips", async () => {
    serve("full");
    server.use(http.get("*/api/analysis/regimes", () => HttpResponse.json(scenarios.open.regimes)));
    renderApp(path(full.trip.trip_id));
    expect(await screen.findByText(scenarios.open.regimes.none_ready_text!)).toBeInTheDocument();
  });

  it("with an analysis that could not run shows Unavailable with the server's reasons in every section", async () => {
    serve("excluded");
    renderApp(path(scenarios.excluded.trip!.trip.trip_id));
    const across = (await screen.findByRole("heading", { name: "Across all your trips" })).closest("section")!;
    expect(await within(across).findByText("Unavailable")).toBeInTheDocument();
    expect(across).toHaveTextContent(scenarios.excluded.trips.summary.trip_count_reason_text!);
    const regime = screen.getByRole("heading", { name: /Volatility regime/ }).closest("section")!;
    expect(within(regime).getByText("Unavailable")).toBeInTheDocument();
  });

  it("always has one h1: while loading, on a missing trip and on a server error", async () => {
    serve("full");
    const first = renderApp(path(full.trip.trip_id));
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    await screen.findByText(/Your return of/);
    first.unmount();
    renderApp(path("no-such-trip"));
    await screen.findByText("That trip is not in your analysis.");
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    server.use(http.get("*/api/analysis/trips/:id", failWith.server));
    renderApp(path("another"));
    await screen.findAllByText("The server hit a problem.");
    expect(screen.getAllByRole("heading", { level: 1 }).length).toBeGreaterThanOrEqual(1);
  });

  it("on an excluded listing: Unavailable and the reason, no chart", async () => {
    serve("excluded");
    const trip = scenarios.excluded.trip!.trip;
    renderApp(path(trip.trip_id));
    await screen.findByRole("heading", { level: 1, name: trip.symbol });
    expect(screen.getAllByText("Unavailable").length).toBeGreaterThan(0);
    expect(screen.getAllByText(trip.reason_text!).length).toBeGreaterThan(0);
    expect(screen.queryByRole("img", { name: /Histogram/ })).toBeNull();
    expect(screen.getByText("Not evaluated")).toBeInTheDocument();
  });

  it("an unknown trip goes back to the list", async () => {
    serve("full");
    renderApp(path("no-such-trip"));
    expect(await screen.findByText("That trip is not in your analysis.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to the list" })).toHaveAttribute("href", "/trips");
  });

  it("Escape returns to the list", async () => {
    serve("full");
    const { router } = renderApp(path(full.trip.trip_id));
    await screen.findByText(/Your return of/);
    await userEvent.keyboard("{Escape}");
    expect(router.state.location.pathname).toBe("/trips");
  });

  it("every screen has one h1 and landmarks", async () => {
    serve("full");
    renderApp(path(full.trip.trip_id));
    await screen.findByText(/Your return of/);
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("main")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Screens" })).toBeInTheDocument();
    expect(screen.getAllByRole("complementary").length).toBeGreaterThan(0);
  });
});
