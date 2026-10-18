import "@fontsource-variable/source-sans-3";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/components.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router-dom";

import { createAppRouter, routerProviderFuture } from "./app/router";
import { retryOnce } from "./shared/api/queries";

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: retryOnce } } });
const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={createAppRouter()} future={routerProviderFuture} />
      </QueryClientProvider>
    </StrictMode>,
  );
}
