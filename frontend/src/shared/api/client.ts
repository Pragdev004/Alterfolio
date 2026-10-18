import { ApiError } from "./errors";

type Params = Record<string, string | null | undefined>;

interface ErrorBody {
  detail?: { code?: string; message?: string } | { msg?: string }[] | string;
}

function detailOf(body: unknown): { code: string | null; message: string } {
  const detail = (body as ErrorBody | null)?.detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail) && "code" in detail) {
    return { code: detail.code ?? null, message: detail.message ?? "" };
  }
  if (typeof detail === "string") return { code: null, message: detail };
  if (Array.isArray(detail)) return { code: null, message: detail.map((d) => d.msg ?? "").join("; ") };
  return { code: null, message: "" };
}

/** GET a JSON body. Network failure, 4xx and 5xx become distinct ApiError kinds; the user is the server's local user. */
export async function getJson<T>(path: string, params: Params = {}, signal?: AbortSignal): Promise<T> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value) query.set(key, value);
  const url = query.size ? `${path}?${query}` : path;
  let response: Response;
  try {
    response = await fetch(url, { headers: { Accept: "application/json" }, signal });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new ApiError("network", null, null, "The server did not answer.");
  }
  if (response.ok) return (await response.json()) as T;
  const body = await response.json().catch(() => null);
  const { code, message } = detailOf(body);
  throw new ApiError(response.status >= 500 ? "server" : "client", response.status, code, message);
}
