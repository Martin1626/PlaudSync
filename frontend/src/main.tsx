import { createRoot } from "react-dom/client";
import { createHashRouter, RouterProvider } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import AppShell from "./components/AppShell";
import { BannersProvider } from "./context/BannersContext";
import { ToastsProvider } from "./context/ToastsContext";
import MockProvider from "./dev/MockProvider";
import Dashboard from "./pages/Dashboard";
import Settings from "./pages/Settings";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import "@fontsource/jetbrains-mono/600.css";
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

// React Router 7 data-router pattern: createHashRouter + RouterProvider.
// Switched from <HashRouter> component because the component variant did not
// re-render Routes on hashchange under PyWebView/WebView2 + React 19 production
// build (Playwright reproduced the same bug in headless Chromium — initial
// render correct, subsequent navigation does not update). The data-router
// pattern uses an internal subscription model that works reliably.
const router = createHashRouter([
  {
    element: <AppShell />,
    children: [
      { path: "/", element: <Dashboard /> },
      { path: "/settings", element: <Settings /> },
    ],
  },
]);

const rootElement = document.getElementById("root");
if (!rootElement) throw new Error("Missing #root element in index.html");

createRoot(rootElement).render(
  <QueryClientProvider client={queryClient}>
    <MockProvider>
      <ToastsProvider>
        <BannersProvider>
          <RouterProvider router={router} />
        </BannersProvider>
      </ToastsProvider>
    </MockProvider>
  </QueryClientProvider>,
);
