import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

/** Every screen that can warn about rejected rows asks for the import status; unless a test says otherwise, nothing was rejected. */
export const noRejections = { batches: [], rejected_rows_total: 0, warning: null };

export const server = setupServer(http.get("*/imports/status", () => HttpResponse.json(noRejections)));
