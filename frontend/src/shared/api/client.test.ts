import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "../../test/server";
import { getJson } from "./client";
import { ApiError, errorCopy } from "./errors";

const fail = async (path: string): Promise<ApiError> => {
  try {
    await getJson(path);
  } catch (e) {
    return e as ApiError;
  }
  throw new Error("expected a failure");
};

describe("getJson", () => {
  it("returns the body", async () => {
    server.use(http.get("*/x", () => HttpResponse.json({ ok: 1 })));
    expect(await getJson("/x")).toEqual({ ok: 1 });
  });
  it("sends as_of only when set", async () => {
    let seen = "";
    server.use(http.get("*/x", ({ request }) => { seen = new URL(request.url).search; return HttpResponse.json({}); }));
    await getJson("/x", { as_of: null });
    expect(seen).toBe("");
    await getJson("/x", { as_of: "2026-11-10" });
    expect(seen).toBe("?as_of=2026-11-10");
  });
  it("tells network, 4xx and 5xx apart and keeps the server's code and message", async () => {
    server.use(
      http.get("*/net", () => HttpResponse.error()),
      http.get("*/four", () => HttpResponse.json({ detail: { code: "as_of_not_sealed", message: "nope" } }, { status: 422 })),
      http.get("*/five", () => HttpResponse.json({ detail: "boom" }, { status: 503 })),
    );
    const net = await fail("/net");
    const four = await fail("/four");
    const five = await fail("/five");
    expect([net.kind, four.kind, five.kind]).toEqual(["network", "client", "server"]);
    expect([four.status, four.code, four.message]).toEqual([422, "as_of_not_sealed", "nope"]);
    expect(five.message).toBe("boom");
  });
});

describe("errorCopy", () => {
  it("maps known codes to plain language", () => {
    expect(errorCopy(new ApiError("client", 422, "as_of_not_sealed", "")).title).toBe("Data for that date isn't final yet.");
    expect(errorCopy(new ApiError("client", 422, "oversell", "")).body).toContain("Upload your oldest tradebook first");
    expect(errorCopy(new ApiError("client", 409, "ledger_busy", "")).retry).toBe(true);
  });
  it("shows the server's message for an unknown 4xx", () => {
    expect(errorCopy(new ApiError("client", 400, "weird", "Bad thing")).body).toBe("Bad thing");
  });
});
