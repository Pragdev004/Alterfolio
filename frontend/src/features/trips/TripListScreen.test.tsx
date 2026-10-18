import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { describe, expect, it } from "vitest";

import { failWith, serve } from "../../test/handlers";
import { renderApp } from "../../test/render";
import { scenarios } from "../../test/fixtures";
import { server } from "../../test/server";

describe("Trip list", () => {
  it("shows the chart header with the sealed date and the last bar, from the server's strings", async () => {
    serve("full");
    renderApp("/trips");
    const sealed = scenarios.full.meta.latest_sealed_as_of.display;
    const header = await screen.findByRole("group", { name: "Data as of" });
    await waitFor(() => expect(header).toHaveTextContent(`Chart prepared${sealed}`));
    expect(header).toHaveTextContent(`Latest bar${scenarios.full.meta.last_bar_date?.display}`);
    expect(header).toHaveTextContent("Data after this date is not used.");
  });

  it("lists one row per trip with the server's display strings and the alternatives label", async () => {
    serve("full");
    renderApp("/trips");
    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(scenarios.full.trips.trips.length);
    const first = scenarios.full.trips.trips[0]!;
    const row = rows[0]!;
    expect(within(row).getByRole("link", { name: `${first.symbol}\u00a0·\u00a0${first.exchange}` })).toBeInTheDocument();
    expect(row).toHaveTextContent(first.open_session.display);
    expect(row).toHaveTextContent(first.actual_return.display);
    expect(row).toHaveTextContent(first.alt!.percentile.display);
    expect(row).toHaveTextContent(first.alternatives_label!);
    expect(within(row).getAllByText("EVALUATED").length).toBeGreaterThan(0);
  });

  it("shows a loading skeleton with a label while the data arrives", async () => {
    serve("full");
    renderApp("/trips");
    expect(screen.getByRole("status")).toHaveTextContent("Fetching market data and computing");
    await screen.findByRole("table");
  });

  it("with too few trips shows the server's sample text and no verdict", async () => {
    serve("few");
    renderApp("/trips");
    expect(await screen.findByText("7 trips · 10 needed")).toBeInTheDocument();
    expect(screen.getByText("Not enough closed trips to say anything yet.")).toBeInTheDocument();
    expect(screen.queryByText(/lucky|unlucky|skill|significant/i)).toBeNull();
  });

  it("keeps trips on an excluded listing in the list with the word Unavailable, its reason, and the listing's trip count", async () => {
    serve("excluded");
    renderApp("/trips");
    const table = await screen.findByRole("table");
    const row = within(table).getAllByRole("row")[1]!;
    expect(within(row).getByText("Unavailable")).toBeInTheDocument();
    expect(within(row).getByText("LISTING EXCLUDED")).toBeInTheDocument();
    const reason = scenarios.excluded.trips.excluded_listings[0]!.reason_text;
    expect(within(row).getByText(reason!)).toBeInTheDocument();
    expect(within(row).queryByText(/^0/)).toBeNull();
    expect(screen.getByRole("heading", { name: /Listings left out/ })).toBeInTheDocument();
    expect(screen.getByText("(14 trips)", { exact: false })).toBeInTheDocument();
  });

  it("with no trades teaches the next step: upload", async () => {
    serve("empty");
    renderApp("/trips");
    expect(await screen.findByText("No trades yet.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Upload your first tradebook/ })).toHaveAttribute("href", "/upload");
  });

  it("with trades but no closed trips says trips appear when a position is fully sold", async () => {
    serve("open");
    renderApp("/trips");
    expect(await screen.findByText("Trips appear when a position is fully sold.")).toBeInTheDocument();
  });

  it("tells an unreachable server apart from a server error, and offers a retry for both", async () => {
    serve("full");
    server.use(http.get("*/api/analysis/trips", failWith.network));
    const first = renderApp("/trips");
    expect(await screen.findByText("Cannot reach the server.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    first.unmount();
    server.use(http.get("*/api/analysis/trips", failWith.server));
    renderApp("/trips");
    expect(await screen.findByText("The server hit a problem.")).toBeInTheDocument();
  });

  it("422 as_of_not_sealed says the data isn't final and offers the latest final date", async () => {
    serve("full");
    server.use(http.get("*/api/analysis/trips", failWith.notSealed));
    renderApp("/trips?as_of=2026-12-01");
    expect(await screen.findByText("Data for that date isn't final yet.")).toBeInTheDocument();
    const button = screen.getByRole("button", { name: /Use the latest final date/ });
    serve("full");
    await userEvent.click(button);
    expect(await screen.findByRole("table")).toBeInTheDocument();
  });

  it("keeps ?as_of= in the URL: the request carries it, and links to a trip keep it", async () => {
    const seen = serve("full");
    renderApp("/trips?as_of=2026-11-20");
    const link = await screen.findAllByRole("link", { name: /·\s+NSE/ });
    expect(seen.asOf).toContain("2026-11-20");
    expect(link[0]).toHaveAttribute("href", expect.stringContaining("as_of=2026-11-20"));
  });

  it("changing the date puts it in the URL and asks the server for it", async () => {
    const seen = serve("full");
    const { router } = renderApp("/trips");
    await screen.findByRole("table");
    const input = screen.getByLabelText("Change date");
    expect(input).toHaveAttribute("max", scenarios.full.meta.latest_sealed_as_of.iso);
    fireEvent.change(input, { target: { value: "2026-11-10" } });
    await waitFor(() => expect(router.state.location.search).toBe("?as_of=2026-11-10"));
    await waitFor(() => expect(seen.asOf).toContain("2026-11-10"));
  });

  it("arrow keys move between rows", async () => {
    serve("full");
    renderApp("/trips");
    const links = await screen.findAllByRole("link", { name: /·\s+NSE/ });
    links[0]!.focus();
    await userEvent.keyboard("{ArrowDown}");
    expect(links[1]).toHaveFocus();
    await userEvent.keyboard("{ArrowUp}");
    expect(links[0]).toHaveFocus();
  });
});
