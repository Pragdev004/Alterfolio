import { createBrowserRouter, createMemoryRouter, Navigate, type RouteObject } from "react-router-dom";

import { TripDetailScreen } from "../features/trips/TripDetailScreen";
import { TripListScreen } from "../features/trips/TripListScreen";
import { AppShell } from "./AppShell";
import { NotBuilt, NotFound } from "./Placeholders";

export const routes: RouteObject[] = [
  {
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/trips" replace /> },
      { path: "trips", element: <TripListScreen /> },
      { path: "trips/:tripId", element: <TripDetailScreen /> },
      { path: "holdings", element: <NotBuilt name="Holdings" /> },
      { path: "costs", element: <NotBuilt name="Costs" /> },
      { path: "ask", element: <NotBuilt name="Ask" /> },
      { path: "upload", element: <NotBuilt name="Upload" /> },
      { path: "*", element: <NotFound /> },
    ],
  },
];

const future = { v7_relativeSplatPath: true, v7_fetcherPersist: true, v7_normalizeFormMethod: true, v7_partialHydration: true, v7_skipActionErrorRevalidation: true };
export const routerProviderFuture = { v7_startTransition: true };

export const createAppRouter = () => createBrowserRouter(routes, { future });
export const createTestRouter = (initial: string) => createMemoryRouter(routes, { initialEntries: [initial], future });
