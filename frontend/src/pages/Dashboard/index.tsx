import { useEffect } from "react";

import { ConflictError } from "@/api/client";
import { useStartSync, useStateQuery } from "@/api/hooks";
import { useBanners } from "@/context/BannersContext";

import RecordingsList from "./RecordingsList";
import SyncNowPanel from "./SyncNowPanel";

export default function Dashboard() {
  const { data, isPending } = useStateQuery();
  const startSync = useStartSync();
  const { pushBanner, syncFromState } = useBanners();

  // Sync state → BannersContext (failed / partial_failure surface as banners).
  // Post-sync toast lives in AppShell (always-mounted, single source of truth).
  useEffect(() => {
    if (!data) return;
    syncFromState(data.sync);
  }, [data, syncFromState]);

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
