import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import metaNoBars from "../../test/fixtures/meta_no_bars.json";
import { scenarios } from "../../test/fixtures";
import type { MetaOut } from "../api/types";
import { ChartHeader } from "./ChartHeader";

const meta = scenarios.full.meta;
const asOf = meta.latest_sealed_as_of;

describe("ChartHeader", () => {
  it("shows the sealed date, the latest bar and the cut-off sentence", () => {
    render(<ChartHeader meta={meta} asOf={asOf} onChange={() => {}} />);
    const header = screen.getByRole("group", { name: "Data as of" });
    expect(header).toHaveTextContent(`Chart prepared${asOf.display}`);
    expect(header).toHaveTextContent(`Latest bar${meta.last_bar_date!.display}`);
    expect(header).toHaveTextContent("Data after this date is not used.");
  });

  it("when there is no last bar date it says so in the server's words instead of leaving the figure out", () => {
    const m = metaNoBars as MetaOut;
    expect(m.last_bar_date).toBeNull();
    render(<ChartHeader meta={m} asOf={m.latest_sealed_as_of} onChange={() => {}} />);
    expect(screen.getByRole("group", { name: "Data as of" })).toHaveTextContent(`Latest bar${m.last_bar_date_reason_text}`);
    expect(m.last_bar_date_reason_text).toBe("No price data yet.");
  });

  it("shows the server's formatted date beside the native input, whatever format the browser uses", () => {
    render(<ChartHeader meta={meta} asOf={asOf} onChange={() => {}} />);
    expect(screen.getByLabelText("Change date")).toHaveValue(asOf.iso);
    expect(screen.getByTestId("picked-date")).toHaveTextContent(asOf.display);
  });
});
