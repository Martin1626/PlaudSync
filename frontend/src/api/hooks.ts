import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import {
  fetchConfig,
  fetchFolders,
  fetchSchedule,
  fetchSpeakers,
  fetchState,
  postAuthVerify,
  postFoldersRefresh,
  postSpeakerAction,
  postSpeakerRename,
  postStartSync,
  putConfig,
  putSchedule,
} from "./client";
import type {
  AuthVerifyResponse,
  ConfigResponse,
  ConfigSaveSuccess,
  FoldersResponse,
  Schedule,
  SpeakersFilter,
  SpeakersResponse,
  StartSyncResponse,
  StateResponse,
} from "./types";

export const STATE_QUERY_KEY = ["state"] as const;
export const CONFIG_QUERY_KEY = ["config"] as const;
export const SCHEDULE_QUERY_KEY = ["schedule"] as const;
export const FOLDERS_QUERY_KEY = ["folders"] as const;

export function useStateQuery() {
  return useQuery<StateResponse>({
    queryKey: STATE_QUERY_KEY,
    queryFn: fetchState,
    refetchInterval: (query) => {
      // Pause polling když okno není visible (minimalizované / skryté)
      // — WebView2 idle CPU klesne na ~0 %. Refresh při návratu fokusu
      // pak interval znovu nastartuje (refetchOnWindowFocus níže).
      if (typeof document !== "undefined" && document.hidden) return false;
      const data = query.state.data;
      return data?.sync.status === "running" ? 1500 : 30000;
    },
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    placeholderData: (prev) => prev,
    retry: 3,
    retryDelay: (attempt) => 100 * 2 ** attempt,
  });
}

export function useStartSync() {
  const qc = useQueryClient();
  return useMutation<StartSyncResponse, Error, void>({
    mutationFn: postStartSync,
    onSuccess: (data) => {
      // Optimistic update: sync subprocess might not have inserted the
      // sync_run row yet by the time we refetch /api/state. Force the cache
      // to status="running" so the polling loop kicks into 1.5s cadence
      // immediately and catches progress.json updates.
      qc.setQueryData<StateResponse>(STATE_QUERY_KEY, (prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          sync: {
            ...prev.sync,
            status: "running",
            started_at: data.started_at,
            trigger: "ui_sync_now",
          },
        };
      });
      // Delayed invalidate: start_sync_subprocess returns 202 within 500ms
      // of spawning, but the subprocess hasn't reached start_sync_run() yet.
      // An immediate refetch would see no open sync_run row and overwrite
      // our optimistic 'running' back to 'idle' — UI would flash idle until
      // the next 30s poll. 2s gives the subprocess time to INSERT.
      window.setTimeout(() => {
        void qc.invalidateQueries({ queryKey: STATE_QUERY_KEY });
      }, 2000);
    },
    onError: () => {
      // ConflictError (409) or spawn failure: refetch immediately so UI
      // reflects the actual server state (sync may already be running by
      // another trigger; spawn failure should reset optimistic running).
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

export function useSchedule() {
  return useQuery<Schedule>({
    queryKey: SCHEDULE_QUERY_KEY,
    queryFn: fetchSchedule,
    retry: 3,
    retryDelay: (attempt) => 100 * 2 ** attempt,
  });
}

export function useSaveSchedule() {
  const qc = useQueryClient();
  return useMutation<Schedule, Error, Schedule>({
    mutationFn: putSchedule,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: SCHEDULE_QUERY_KEY });
    },
  });
}

// ---------------- BL-X folder catalog ----------------

export function useFolders() {
  return useQuery<FoldersResponse>({
    queryKey: FOLDERS_QUERY_KEY,
    queryFn: fetchFolders,
    retry: 2,
    retryDelay: (attempt) => 200 * 2 ** attempt,
    // No automatic refetch — UI Settings refresh button + 1h TTL on disk
    // cache is sufficient. Stale flag from server signals when refresh is
    // worth doing.
  });
}

export function useRefreshFolders() {
  const qc = useQueryClient();
  return useMutation<FoldersResponse, Error, void>({
    mutationFn: postFoldersRefresh,
    onSuccess: (data) => {
      qc.setQueryData<FoldersResponse>(FOLDERS_QUERY_KEY, data);
    },
  });
}

// ---------------- Speaker review ----------------

export const SPEAKERS_QUERY_KEY = ["speakers"] as const;

export function useSpeakersQuery(filter: SpeakersFilter) {
  return useQuery<SpeakersResponse>({
    queryKey: [...SPEAKERS_QUERY_KEY, filter],
    queryFn: () => fetchSpeakers(filter),
    refetchInterval: () => {
      if (typeof document !== "undefined" && document.hidden) return false;
      return 30000;
    },
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    placeholderData: (prev) => prev,
    retry: 3,
    retryDelay: (attempt) => 100 * 2 ** attempt,
  });
}

function useSpeakerMutation<V>(fn: (v: V) => Promise<void>) {
  const qc = useQueryClient();
  return useMutation<void, Error, V>({
    mutationFn: fn,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: SPEAKERS_QUERY_KEY });
    },
  });
}

export function useConfirmSample() {
  return useSpeakerMutation<number>((id) => postSpeakerAction(id, "confirm"));
}

export function useExcludeSample() {
  return useSpeakerMutation<number>((id) => postSpeakerAction(id, "exclude"));
}

export function useRenameSample() {
  return useSpeakerMutation<{ id: number; name: string }>(({ id, name }) =>
    postSpeakerRename(id, name),
  );
}
