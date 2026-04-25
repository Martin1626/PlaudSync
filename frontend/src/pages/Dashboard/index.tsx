import { useEffect, useRef } from "react";

import { ConflictError } from "@/api/client";
import { useStartSync, useStateQuery } from "@/api/hooks";
import type { SyncState } from "@/api/types";
import { useBanners } from "@/context/BannersContext";
import { useToasts } from "@/context/ToastsContext";

import RecordingsList from "./RecordingsList";
import SyncNowPanel from "./SyncNowPanel";

export default function Dashboard() {
  const { data, isPending } = useStateQuery();
  const startSync = useStartSync();
  const { pushToast } = useToasts();
  const { pushBanner, syncFromState } = useBanners();

  // Push success toast on sync transition running -> idle + outcome=success.
  // Track previous status in a ref so we fire exactly once per transition.
  const prevStatusRef = useRef<SyncState["status"] | undefined>(undefined);

  useEffect(() => {
    if (!data) return;
    syncFromState(data.sync);
    const prev = prevStatusRef.current;
    if (prev === "running" && data.sync.status === "idle") {
      if (data.sync.last_run_outcome === "success") {
        const newCount = data.recordings.length;
        pushToast(
          "success",
          `Synchronizace dokončena — ${newCount} nových nahrávek`,
        );
      }
      // failed / partial_failure cases surface via syncFromState banner.
    }
    prevStatusRef.current = data.sync.status;
  }, [data, syncFromState, pushToast]);

  const handleSync = () => {
    startSync.mutate(undefined, {
      onError: (err) => {
        if (err instanceof ConflictError) {
          // Transparent: no toast / banner. invalidateQueries in onSettled
          // will pick up the running stav from backend.
          return;
        }
        pushBanner({
          id: "sync-spawn-failed",
          variant: "error",
          title: "Synchronizaci se nepodařilo spustit",
          message: "Spuštění sync subprocesu selhalo. Zkontroluj log.",
          actionLabel: "Zobrazit log",
        });
      },
    });
  };

  if (isPending && !data) {
    return (
      <div className="flex items-center justify-center py-12">
        <svg
          viewBox="0 0 24 24"
          className="w-6 h-6 text-gray-400 animate-spin"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.4"
          strokeLinecap="round"
          aria-hidden="true"
        >
          <path d="M21 12a9 9 0 1 1-6.2-8.55" />
        </svg>
        <span className="ml-3 text-sm text-gray-500">Načítám…</span>
      </div>
    );
  }

  if (!data) return null; // Should not happen if !isPending; safety net.

  return (
    <div className="space-y-5">
      <SyncNowPanel
        sync={data.sync}
        onSync={handleSync}
        startSyncDisabled={startSync.isPending}
      />
      <RecordingsList recordings={data.recordings} />
    </div>
  );
}
