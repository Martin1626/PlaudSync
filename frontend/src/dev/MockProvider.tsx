import {
  createContext,
  useContext,
  useEffect,
  useState,
  type PropsWithChildren,
} from "react";
import { useQueryClient } from "@tanstack/react-query";

import { CONFIG_QUERY_KEY, STATE_QUERY_KEY } from "@/api/hooks";
import type { ConfigResponse } from "@/api/types";

import { MOCK_CONFIG_RAW, SCENARIOS, type ScenarioKey } from "./mockState";

interface MockContextValue {
  scenario: ScenarioKey;
  setScenario: (key: ScenarioKey) => void;
  showOverlay: boolean;
  setShowOverlay: (v: boolean) => void;
}

const MockContext = createContext<MockContextValue | null>(null);

export function useMockContext(): MockContextValue | null {
  // Returns null in production (provider not mounted) so consumers can early-return.
  return useContext(MockContext);
}

export default function MockProvider({ children }: PropsWithChildren) {
  if (!import.meta.env.DEV) return <>{children}</>;
  return <DevImpl>{children}</DevImpl>;
}

function DevImpl({ children }: PropsWithChildren) {
  const qc = useQueryClient();
  const [scenario, setScenario] = useState<ScenarioKey>("idle");
  const [showOverlay, setShowOverlay] = useState(false);

  // Pre-populate TanStack cache with the chosen scenario state + mock config.
  useEffect(() => {
    qc.setQueryData(STATE_QUERY_KEY, SCENARIOS[scenario].state);
    const mockConfig: ConfigResponse = {
      raw_yaml: MOCK_CONFIG_RAW,
      parsed: null,
      parse_error: null,
    };
    qc.setQueryData(CONFIG_QUERY_KEY, mockConfig);
  }, [qc, scenario]);

  const value: MockContextValue = {
    scenario,
    setScenario,
    showOverlay,
    setShowOverlay,
  };
  return <MockContext.Provider value={value}>{children}</MockContext.Provider>;
}
