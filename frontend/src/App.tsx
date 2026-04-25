import { Route, Routes } from "react-router-dom";

import AppShell from "./components/AppShell";
import { BannersProvider } from "./context/BannersContext";
import { ToastsProvider } from "./context/ToastsContext";
import Dashboard from "./pages/Dashboard";
import Settings from "./pages/Settings";

export default function App() {
  return (
    <ToastsProvider>
      <BannersProvider>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/settings" element={<Settings />} />
          </Route>
        </Routes>
      </BannersProvider>
    </ToastsProvider>
  );
}
