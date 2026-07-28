import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { App } from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { GlobalLoader } from "./components/GlobalLoader";
import { LoadingProvider } from "./context/LoadingContext";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <LoadingProvider>
        <BrowserRouter>
          <App />
          <GlobalLoader />
        </BrowserRouter>
      </LoadingProvider>
    </ErrorBoundary>
  </React.StrictMode>
);
