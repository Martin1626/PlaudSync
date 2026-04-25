import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import {
  fetchConfig,
  fetchState,
  postAuthVerify,
  postStartSync,
  putConfig,
} from "./client";
import type {
  AuthVerifyResponse,
  ConfigResponse,
  ConfigSaveSuccess,
  StartSyncResponse,
  StateResponse,
} from "./types";

export const STATE_QUERY_KEY = ["state"] as const;
export const CONFIG_QUERY_KEY = ["config"] as const;

export function useStateQuery() {
  return useQuery<StateResponse>({
    queryKey: STATE_QUERY_KEY,
    queryFn: fetchState,
    refetchInterval: (query) => {
      const data = query.state.data;
      return data?.sync.status === "running" ? 1500 : 5000;
    },
    placeholderData: (prev) => prev,
    retry: 3,
    retryDelay: (attempt) => 100 * 2 ** attempt,
  });
}

export function useStartSync() {
  const qc = useQueryClient();
  return useMutation<StartSyncResponse, Error, void>({
    mutationFn: postStartSync,
    onSettled: () => {
      // Always invalidate state — happy path picks up running stav,
      // 409 ConflictError still wants a fresh state read to show running.
      void qc.invalidateQueries({ queryKey: STATE_QUERY_KEY });
    },
  });
}

export function useConfig() {
  return useQuery<ConfigResponse>({
    queryKey: CONFIG_QUERY_KEY,
    queryFn: fetchConfig,
    retry: 3,
    retryDelay: (attempt) => 100 * 2 ** attempt,
    // No refetchInterval — config is fetched on mount + reload click.
  });
}

export function useSaveConfig() {
  const qc = useQueryClient();
  return useMutation<ConfigSaveSuccess, Error, string>({
    mutationFn: putConfig,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: CONFIG_QUERY_KEY });
    },
  });
}

export function useVerifyAuth() {
  return useMutation<AuthVerifyResponse, Error, void>({
    mutationFn: postAuthVerify,
  });
}
