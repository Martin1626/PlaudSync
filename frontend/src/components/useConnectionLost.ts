import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { STATE_QUERY_KEY } from "@/api/hooks";

interface ConnectionLost {
  visible: boolean;
  lastError: string | undefined;
}

/**
 * Watch the state query for a "connection lost" condition: 3 consecutive fetch
 * failures with no successful refetch in between. Resolves automatically when
 * the next fetch succeeds.
 *
 * Why a hook + queryCache.subscribe instead of returning isError from
 * useStateQuery: a single failure that recovers shouldn't trigger the
 * full-page overlay; only persistent failure should.
 */
export function useConnectionLost(): ConnectionLost {
  const qc = useQueryClient();
  const [state, setState] = useState<ConnectionLost>({
    visible: false,
    lastError: undefined,
  });

  useEffect(() => {
    const cache = qc.getQueryCache();
    const recompute = () => {
      const query = cache.find({ queryKey: STATE_QUERY_KEY });
      if (!query) return;
      const failureCount = query.state.fetchFailureCount;
      const errorMessage =
        query.state.error instanceof Error
          ? query.state.error.message
          : undefined;
      if (failureCount >= 3 && query.state.fetchStatus === "idle") {
        setState({ visible: true, lastError: errorMessage });
      } else if (query.state.status === "success") {
        setState({ visible: false, lastError: undefined });
      }
    };
    recompute();
    const unsub = cache.subscribe(recompute);
    return () => unsub();
  }, [qc]);

  return state;
}
