import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { serve } from "../test/handlers";
import { renderApp } from "../test/render";

beforeEach(() => window.localStorage.clear());

describe("app shell", () => {
  it("has the footer disclaimer and no disclaimer in the rail", async () => {
    serve("full");
    renderApp("/trips");
    expect(screen.getByRole("contentinfo")).toHaveTextContent("Educational, not financial advice.");
    expect(screen.getByRole("navigation", { name: "Screens" })).not.toHaveTextContent("Educational");
  });

  it("g then a letter jumps to a screen", async () => {
    serve("full");
    const { router } = renderApp("/trips");
    await userEvent.keyboard("gu");
    expect(router.state.location.pathname).toBe("/upload");
    await userEvent.keyboard("gc");
    expect(router.state.location.pathname).toBe("/costs");
  });

  it("the setting turns the shortcuts off, and the choice is remembered", async () => {
    serve("full");
    const { router } = renderApp("/trips");
    await userEvent.click(screen.getByRole("checkbox", { name: /Keyboard shortcuts/ }));
    await userEvent.keyboard("gu");
    expect(router.state.location.pathname).toBe("/trips");
    expect(window.localStorage.getItem("alterfolio.gShortcuts")).toBe("off");
  });

  it("the shortcuts stay off on the next visit", async () => {
    window.localStorage.setItem("alterfolio.gShortcuts", "off");
    serve("full");
    const { router } = renderApp("/trips");
    expect(screen.getByRole("checkbox", { name: /Keyboard shortcuts/ })).not.toBeChecked();
    await userEvent.keyboard("ga");
    expect(router.state.location.pathname).toBe("/trips");
  });

  it("typing in a field never triggers a shortcut", async () => {
    const { router } = renderApp("/ask");
    serve("full");
    await userEvent.type(await screen.findByLabelText("Your question"), "gu");
    expect(router.state.location.pathname).toBe("/ask");
  });

  it("serves html with lang en-IN", async () => {
    const { readFileSync } = await import("node:fs");
    expect(readFileSync("index.html", "utf8")).toContain('<html lang="en-IN">');
  });
});
