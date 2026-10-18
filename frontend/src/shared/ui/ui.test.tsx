import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { NumberOut } from "../api/types";
import { AnalystOffline, ErrorState, NotFinal, Skeleton } from "./States";
import { Direction } from "./Direction";
import { Figure, Reason } from "./Figure";
import { band, place } from "./geometry";

const num = (value: string | null, display: string, reason_text: string | null = null): NumberOut => ({ value, display, unavailable_reason: reason_text && "CODE", reason_text });

describe("Figure", () => {
  it("renders the server's display for a value", () => {
    render(<Figure n={num("0.0410256", "4.10% (fees excluded)")} />);
    expect(screen.getByText("4.10% (fees excluded)")).toBeInTheDocument();
  });
  it("a genuine zero renders as the server's text, not as Unavailable", () => {
    render(<Figure n={num("0", "0.00%")} />);
    expect(screen.getByText("0.00%")).toBeInTheDocument();
    expect(screen.queryByText("Unavailable")).toBeNull();
  });
  it("a null value is the word Unavailable and its reason hangs beside it", () => {
    const n = num(null, "Unavailable", "No price history is available for it.");
    render(<><Figure n={n} /><Reason n={n} /></>);
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
    expect(screen.getByText("No price history is available for it.")).toBeInTheDocument();
  });
});

describe("Direction", () => {
  it("ahead and behind carry a word and a drawn mark", () => {
    const { container, rerender } = render(<Direction direction="ahead" />);
    expect(screen.getByText("ahead")).toHaveClass("dir", "ahead");
    expect(container.querySelector("svg")).not.toBeNull();
    rerender(<Direction direction="behind" />);
    expect(screen.getByText("behind")).toHaveClass("behind");
  });
  it("inconclusive and level have neither arrow nor colour", () => {
    const { container, rerender } = render(<Direction direction="inconclusive" text="not distinguishable from zero" />);
    expect(screen.getByText("not distinguishable from zero")).not.toHaveClass("ahead", "behind");
    expect(container.querySelector("svg")).toBeNull();
    rerender(<Direction direction="level" />);
    expect(container.querySelector("svg")).toBeNull();
  });
  it("renders nothing without a direction", () => {
    const { container } = render(<Direction direction={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("states", () => {
  it("skeleton is labelled, never a bare spinner", () => {
    render(<Skeleton />);
    expect(screen.getByRole("status")).toHaveTextContent("Fetching market data and computing");
  });
  it("analyst offline is one line that leaves everything else alone", () => {
    render(<AnalystOffline />);
    expect(screen.getByText("Analyst offline — your numbers are still here.")).toBeInTheDocument();
  });
  it("not final offers the latest sealed date", () => {
    render(<NotFinal onUseLatest={() => {}} latestDisplay="30 Nov 2026" />);
    expect(screen.getByText("Data for that date isn't final yet.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /30 Nov 2026/ })).toBeInTheDocument();
  });
  it("an unknown error still renders something honest", () => {
    render(<ErrorState error={new Error("x")} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Something went wrong.");
  });
});

describe("geometry", () => {
  it("places a value between two bounds", () => {
    expect(place("5", "0", "10", 200)).toBe(100);
    expect(place("0", "0", "0", 200)).toBe(0);
  });
  it("lays out the volatility band on the server's thresholds", () => {
    const b = band("0.0184", "0.0131", "0.0227", 300);
    expect(b.low[0]).toBe(0);
    expect(b.normal[0]).toBeCloseTo(b.low[1]);
    expect(b.high[1]).toBe(300);
    expect(b.marker).toBeGreaterThan(b.normal[0]);
    expect(b.marker).toBeLessThan(b.normal[1]);
  });
});
