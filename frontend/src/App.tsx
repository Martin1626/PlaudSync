import { Route, Routes } from "react-router-dom";

import AppShell from "./components/AppShell";
import { BannersProvider } from "./context/BannersContext";
import { ToastsProvider } from "./context/ToastsContext";
import Dashboard from "./pages/Dashboard";
import Settings from "./pages/Settings";
import Speakers from "./pages/Speakers";

export default function App() {
  return (
    <ToastsProvider>
      <BannersProvider>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/speakers" element={<Speakers />} />
            <Route path="/settings" element={<Settings />} />
          </Route>
        </Routes>
      </BannersProvider>
    </ToastsProvider>
  );
}
