import { createBrowserRouter, createMemoryRouter, Navigate, type RouteObject } from "react-router-dom";

import { TripDetailScreen } from "../features/trips/TripDetailScreen";
import { TripListScreen } from "../features/trips/TripListScreen";
import { AskScreen } from "../features/ask/AskScreen";
import { CostsScreen } from "../features/costs/CostsScreen";
import { HoldingsScreen } from "../features/holdings/HoldingsScreen";
import { UploadScreen } from "../features/upload/UploadScreen";
import { AppShell } from "./AppShell";
import { NotFound } from "./Placeholders";

export const routes: RouteObject[] = [
  {
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/trips" replace /> },
      { path: "trips", element: <TripListScreen /> },
      { path: "trips/:tripId", element: <TripDetailScreen /> },
      { path: "holdings", element: <HoldingsScreen /> },
      { path: "costs", element: <CostsScreen /> },
      { path: "ask", element: <AskScreen /> },
      { path: "upload", element: <UploadScreen /> },
      { path: "*", element: <NotFound /> },
    ],
  },
];

const future = { v7_relativeSplatPath: true, v7_fetcherPersist: true, v7_normalizeFormMethod: true, v7_partialHydration: true, v7_skipActionErrorRevalidation: true };
export const routerProviderFuture = { v7_startTransition: true };

export const createAppRouter = () => createBrowserRouter(routes, { future });
export const createTestRouter = (initial: string) => createMemoryRouter(routes, { initialEntries: [initial], future });
