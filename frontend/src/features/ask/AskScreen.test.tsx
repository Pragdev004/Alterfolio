import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { recordedAsk } from "../../test/fixtures";
import { failWith, serve, serveAsk } from "../../test/handlers";
import { renderApp } from "../../test/render";
import { server } from "../../test/server";

async function askSomething(question = "What did my behaviour cost me?") {
  serve("full");
  await screen.findByLabelText("As of");
  await waitFor(() => expect(screen.getByLabelText("As of")).toHaveValue("2026-11-30"));
  await userEvent.type(screen.getByLabelText("Your question"), question);
  await userEvent.click(screen.getByRole("button", { name: "Ask" }));
}

describe("Ask", () => {
  it("defaults the date to the latest sealed day and needs a question", async () => {
    serve("full");
    renderApp("/ask");
    await waitFor(() => expect(screen.getByLabelText("As of")).toHaveValue("2026-11-30"));
    expect(screen.getByLabelText("As of")).toHaveAttribute("max", "2026-11-30");
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
  });

  it("labels a template answer and keeps the text as the server sent it", async () => {
    serve("full");
    serveAsk("template");
    renderApp("/ask");
    await askSomething();
    expect(await screen.findByText("Template answer")).toBeInTheDocument();
    const text = (recordedAsk.template!.body as { text: string }).text;
    expect(screen.getByText(/bias\.CHASING\.cost_inr/)).toHaveTextContent(text.split("\n")[1]!);
    expect(screen.queryByText(/Unverified/)).toBeNull();
  });

  it("citation chips link to the screen that shows the fact", async () => {
    serve("full");
    serveAsk("template");
    renderApp("/ask");
    await askSomething();
    const cited = await screen.findByRole("complementary", { name: "Facts cited" });
    const link = within(cited).getByRole("link", { name: "006:CHASING.cost_inr" });
    expect(link).toHaveAttribute("href", "/costs");
  });

  it("an unverified answer is labelled and never presented as a normal answer", async () => {
    serve("full");
    serveAsk("unverified");
    renderApp("/ask");
    await askSomething();
    expect(await screen.findByText("Unverified: showing the raw facts")).toBeInTheDocument();
    expect(screen.queryByText("Numbers checked")).toBeNull();
    expect(screen.queryByText(/99\.5%/)).toBeNull();
  });

  it("says Fetching market data and computing while it waits, and disables the form", async () => {
    server.use(http.post("*/api/analyst/ask", async () => {
      await new Promise((r) => setTimeout(r, 60));
      return HttpResponse.json(recordedAsk.template!.body);
    }));
    serve("full");
    renderApp("/ask");
    await askSomething();
    expect(await screen.findAllByText("Fetching market data and computing…")).not.toHaveLength(0);
    expect(screen.getByLabelText("Your question")).toBeDisabled();
    await screen.findByText("Template answer");
  });

  it("an unconfigured analyst (503) is one line, and the other screens still work (A4)", async () => {
    serve("full");
    serveAsk("offline");
    const { router } = renderApp("/ask");
    await askSomething();
    expect(await screen.findByText("Analyst offline — your numbers are still here.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    await router.navigate("/trips");
    expect(await screen.findAllByRole("link", { name: /·\s+NSE/ })).not.toHaveLength(0);
  });

  it("a network failure and a 500 are also just the offline line", async () => {
    serve("full");
    server.use(http.post("*/api/analyst/ask", failWith.network));
    const first = renderApp("/ask");
    await askSomething();
    expect(await screen.findByText("Analyst offline — your numbers are still here.")).toBeInTheDocument();
    first.unmount();
    server.use(http.post("*/api/analyst/ask", failWith.server));
    renderApp("/ask");
    await askSomething();
    expect(await screen.findByText("Analyst offline — your numbers are still here.")).toBeInTheDocument();
  });

  it("a date that is not final shows the specified copy with a way to the latest date", async () => {
    serve("full");
    serveAsk("not_sealed");
    renderApp("/ask");
    await askSomething();
    expect(await screen.findByText("Data for that date isn't final yet.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Use the latest final date/ })).toBeInTheDocument();
  });

  it("limits the question to 2000 characters", async () => {
    serve("full");
    renderApp("/ask");
    expect(await screen.findByLabelText("Your question")).toHaveAttribute("maxlength", "2000");
  });
});
