import type { ReactNode } from "react";

import type { SyncState } from "@/api/types";
import { phaseLabel, relativeTime } from "@/utils/format";

interface Props {
  sync: SyncState;
}

export default function SyncStatusBadge({ sync }: Props) {
  let dot: ReactNode;
  let label: string;

  if (sync.status === "running") {
    dot = <span className="w-2 h-2 rounded-full bg-blue-500 animate-ps-pulse" />;
    label = phaseLabel(sync.progress);
  } else if (sync.last_run_outcome === "failed") {
    dot = <span className="w-2 h-2 rounded-full bg-red-500" />;
    label = "Poslední synchronizace selhala";
  } else if (sync.last_run_outcome === "partial_failure") {
    dot = <span className="w-2 h-2 rounded-full bg-amber-500" />;
    label = `Poslední sync ${relativeTime(sync.last_run_at) ?? "—"} — částečný`;
  } else if (sync.last_run_outcome === "success") {
    dot = <span className="w-2 h-2 rounded-full bg-green-500" />;
    label = `Poslední sync ${relativeTime(sync.last_run_at) ?? "—"}`;
  } else {
    dot = <span className="w-2 h-2 rounded-full bg-gray-300" />;
    label = "Nečinný";
  }

  return (
    <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-gray-50 border border-gray-200">
      {dot}
      <span className="text-[13px] text-gray-700 font-medium">{label}</span>
    </div>
  );
}
