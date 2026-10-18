import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { RouterProvider } from "react-router-dom";

import { createTestRouter, routerProviderFuture } from "../app/router";

export function renderApp(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createTestRouter(path);
  const view = render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} future={routerProviderFuture} />
    </QueryClientProvider>,
  );
  return { ...view, router, client };
}
