import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { recordedImports, scenarios } from "../../test/fixtures";
import { failWith, serve, serveImport } from "../../test/handlers";
import { renderApp } from "../../test/render";
import { server } from "../../test/server";

const csv = (name = "tradebook.csv") => new File(["a,b\n1,2\n"], name, { type: "text/csv" });
async function pick(file: File) {
  const input = screen.getByLabelText("Tradebook CSV") as HTMLInputElement;
  await userEvent.upload(input, file);
}
const importNow = () => userEvent.click(screen.getByRole("button", { name: "Import tradebook" }));

describe("Upload", () => {
  it("opens with the oldest-tradebook-first sentence and a disabled button", () => {
    renderApp("/upload");
    expect(screen.getByText("Upload your oldest tradebook first.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import tradebook" })).toBeDisabled();
  });

  it("shows the chosen file's name and size", async () => {
    renderApp("/upload");
    await pick(csv("zerodha.csv"));
    expect(screen.getByText(/Selected: zerodha\.csv · 8 bytes/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import tradebook" })).toBeEnabled();
  });

  it("rejects a file over 2 MiB in the browser, before any request", async () => {
    renderApp("/upload");
    const big = csv("big.csv");
    Object.defineProperty(big, "size", { value: 2 * 1024 * 1024 + 1 });
    await pick(big);
    expect(screen.getByRole("alert")).toHaveTextContent("larger than 2 MiB");
    expect(screen.getByRole("button", { name: "Import tradebook" })).toBeDisabled();
  });

  it("says Importing while it works and disables the button", async () => {
    server.use(http.post("*/imports/tradebook", async () => {
      await new Promise((r) => setTimeout(r, 60));
      return HttpResponse.json(recordedImports.ok!.body, { status: 201 });
    }));
    renderApp("/upload");
    await pick(csv());
    await importNow();
    expect(await screen.findAllByText("Importing…")).not.toHaveLength(0);
    expect(screen.getByRole("button", { name: "Importing…" })).toBeDisabled();
    await screen.findByRole("heading", { name: /Import result/ });
  });

  it("shows a ruled summary, the rejected rows table and that charges are unknown, not zero", async () => {
    serveImport("ok");
    renderApp("/upload");
    await pick(csv("tradebook_synthetic.csv"));
    await importNow();
    const result = recordedImports.ok!.body as { total_rows: number; imported: number; rejected: { row: number; code: string; message: string }[] };
    const summary = (await screen.findByRole("heading", { name: /Import result/ })).closest("section")!;
    expect(within(summary).getByRole("rowheader", { name: "Imported" }).closest("tr")).toHaveTextContent(String(result.imported));
    expect(within(summary).getByRole("rowheader", { name: "Rows in the file" }).closest("tr")).toHaveTextContent(String(result.total_rows));
    const rejected = within(summary).getByRole("table", { name: /Rejected rows/ });
    const row = result.rejected[0]!;
    expect(rejected).toHaveTextContent(String(row.row));
    expect(within(rejected).getByText(row.code)).toBeInTheDocument();
    expect(within(rejected).getByText(row.message)).toBeInTheDocument();
    expect(summary).toHaveTextContent("Charges are unknown, not zero");
    expect(within(summary).getByRole("link", { name: "See your trips" })).toBeInTheDocument();
  });

  it("an upload with no rejected rows has no rejected table", async () => {
    serveImport("ok");
    const body = { ...recordedImports.ok!.body, rejected: [], rejected_total: 0, imported: 7 };
    server.use(http.post("*/imports/tradebook", () => HttpResponse.json(body, { status: 201 })));
    renderApp("/upload");
    await pick(csv());
    await importNow();
    await screen.findByRole("heading", { name: /Import result/ });
    expect(screen.queryByRole("table", { name: /Rejected rows/ })).toBeNull();
  });

  it("explains oversell in plain words and lists the set-aside ISIN", async () => {
    serveImport("oversell");
    renderApp("/upload");
    await pick(csv("sells_first.csv"));
    await importNow();
    expect(await screen.findByText("A sell in this file has no earlier buy.")).toBeInTheDocument();
    expect(screen.getByText("Upload your oldest tradebook first, then upload this one again.")).toBeInTheDocument();
    expect(screen.getAllByText(/ZZ0ALPHA0001/).length).toBeGreaterThan(0);
    expect(screen.getByText("oversell")).toBeInTheDocument();
  });

  it("a file the server cannot read shows its message and keeps the file selected", async () => {
    serveImport("invalid");
    renderApp("/upload");
    await pick(csv("notes.csv"));
    await importNow();
    expect(await screen.findByText("That file could not be read.")).toBeInTheDocument();
    expect(screen.getByText(/the header does not match/)).toBeInTheDocument();
    expect(screen.getByText(/Selected: notes\.csv/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import tradebook" })).toBeEnabled();
  });

  it("a busy ledger (409) offers a retry that works", async () => {
    serveImport("ok");
    server.use(http.post("*/imports/tradebook", () => HttpResponse.json({ detail: { code: "ledger_busy", message: "busy" } }, { status: 409 }), { once: true }));
    renderApp("/upload");
    await pick(csv());
    await importNow();
    expect(await screen.findByText("Your ledger is busy.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: /Import result/ })).toBeInTheDocument();
  });

  it("an unreachable server is its own message", async () => {
    server.use(http.post("*/imports/tradebook", failWith.network));
    renderApp("/upload");
    await pick(csv());
    await importNow();
    expect(await screen.findByText("Cannot reach the server.")).toBeInTheDocument();
  });

  it("after an import, the trip list is refetched", async () => {
    serve("empty");
    const { router } = renderApp("/trips");
    expect(await screen.findByText("No trades yet.")).toBeInTheDocument();
    serveImport("ok");
    serve("full");
    await router.navigate("/upload");
    await screen.findByLabelText("Tradebook CSV");
    await pick(csv());
    await importNow();
    await screen.findByRole("heading", { name: /Import result/ });
    fireEvent.click(screen.getByRole("link", { name: "See your trips" }));
    await waitFor(() => expect(screen.getAllByRole("link", { name: /·\s+NSE/ }).length).toBeGreaterThan(0));
  });

  it("the 'first X of N' caption is the server's rejected_text, not composed here", async () => {
    const ok = recordedImports.ok!.body as { rejected: unknown[] };
    server.use(http.post("*/imports/tradebook", () => HttpResponse.json({ ...ok, rejected_text: "The first 200 of 350 rejected rows" })));
    renderApp("/upload");
    await pick(csv());
    await importNow();
    expect(await screen.findByRole("table", { name: "Rejected rows: The first 200 of 350 rejected rows" })).toBeInTheDocument();
  });

  it("lists previous uploads with their rejected counts, as the target of the warning link", async () => {
    serve("imported");
    renderApp("/upload#previous");
    const section = (await screen.findByRole("heading", { name: /Previous uploads/ })).closest("section")!;
    expect(section).toHaveAttribute("id", "previous");
    expect(section).toHaveTextContent("1 row was rejected at import; figures may be wrong");
    const row = within(section).getByRole("rowheader", { name: "sept.csv" }).closest("tr")!;
    expect(row).toHaveTextContent(scenarios.imported.status!.batches[0]!.created_at_display);
  });
});
