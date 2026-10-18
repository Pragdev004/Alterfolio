import { fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { describe, expect, it } from "vitest";

import metaNoBars from "../../test/fixtures/meta_no_bars.json";
import { scenarios } from "../../test/fixtures";
import type { MetaOut } from "../api/types";
import { ChartHeader } from "./ChartHeader";

const meta = scenarios.full.meta;
const asOf = meta.latest_sealed_as_of;

describe("ChartHeader", () => {
  it("shows the sealed date, the latest bar and the cut-off sentence", () => {
    render(<ChartHeader meta={meta} asOf={asOf} selected={null} onChange={() => {}} />);
    const header = screen.getByRole("group", { name: "Data as of" });
    expect(header).toHaveTextContent(`Chart prepared${asOf.display}`);
    expect(header).toHaveTextContent(`Latest bar${meta.last_bar_date!.display}`);
    expect(header).toHaveTextContent("Data after this date is not used.");
  });

  it("when there is no last bar date it says so in the server's words instead of leaving the figure out", () => {
    const m = metaNoBars as MetaOut;
    expect(m.last_bar_date).toBeNull();
    render(<ChartHeader meta={m} asOf={m.latest_sealed_as_of} selected={null} onChange={() => {}} />);
    expect(screen.getByRole("group", { name: "Data as of" })).toHaveTextContent(`Latest bar${m.last_bar_date_reason_text}`);
    expect(m.last_bar_date_reason_text).toBe("No price data yet.");
  });

  it("shows the server's formatted date beside the native input, whatever format the browser uses", () => {
    render(<ChartHeader meta={meta} asOf={asOf} selected={null} onChange={() => {}} />);
    expect(screen.getByLabelText("Change date")).toHaveValue(asOf.iso);
    expect(screen.getByTestId("picked-date")).toHaveTextContent(asOf.display);
  });

  it("keeps what the user is typing: only a complete date that is not after the last final day is sent on", () => {
    const onChange = vi.fn();
    render(<ChartHeader meta={meta} asOf={asOf} selected={null} onChange={onChange} />);
    const input = screen.getByLabelText("Change date");
    fireEvent.change(input, { target: { value: "0002-11-30" } });
    fireEvent.change(input, { target: { value: "2026-12-05" } }); // after the last final day
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: "2026-11-10" } });
    expect(onChange).toHaveBeenCalledExactlyOnceWith("2026-11-10");
  });

  it("while a chosen date is loading the header does not claim the latest date", () => {
    render(<ChartHeader meta={meta} asOf={undefined} selected="2026-11-10" onChange={() => {}} />);
    expect(screen.getByRole("group", { name: "Data as of" })).toHaveTextContent("Chart prepared…");
    expect(screen.getByLabelText("Change date")).toHaveValue("2026-11-10");
  });
});
