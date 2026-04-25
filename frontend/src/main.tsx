import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import App from "./App";
import MockProvider from "./dev/MockProvider";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 3,
      retryDelay: (attempt) => 100 * 2 ** attempt,
      refetchOnWindowFocus: false,
      // In dev mock mode, disable real fetching — MockProvider seeds setQueryData.
      // staleTime: Infinity prevents auto refetch on mount/focus; refetchInterval
      // override per-hook still drives polling, but mock mode resets it implicitly.
      staleTime: import.meta.env.DEV ? Infinity : 0,
    },
    mutations: {
      retry: 0,
    },
  },
});

const rootElement = document.getElementById("root");
if (!rootElement) throw new Error("Missing #root element in index.html");

createRoot(rootElement).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <MockProvider>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </MockProvider>
    </QueryClientProvider>
  </StrictMode>,
);
