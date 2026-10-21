import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "./styles/tokens.css";
import "./styles/app.css";
import "./ui/ui.css";

import { ApiError } from "./api/client";
import { App } from "./App";
import { keepFieldsInView } from "./lib/keyboard";
import { start } from "./telegram";
import { applyTheme, savedThemeMode } from "./theme";

start();
applyTheme(savedThemeMode());
keepFieldsInView();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      refetchOnWindowFocus: true,
      // Retry flaky networks, not requests the server refused.
      retry: (failures, error) => !(error instanceof ApiError && error.status < 500) && failures < 2,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
