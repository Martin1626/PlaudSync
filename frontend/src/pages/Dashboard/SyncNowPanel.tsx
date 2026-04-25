import type { SyncState } from "@/api/types";
import { classNames, formatExactTime, phaseLabel, relativeTime } from "@/utils/format";

interface Props {
  sync: SyncState;
  onSync: () => void;
  startSyncDisabled?: boolean;
}

export default function SyncNowPanel({
  sync,
  onSync,
  startSyncDisabled = false,
}: Props) {
  const isRunning = sync.status === "running";
  const isTaskScheduler = sync.trigger === "task_scheduler";
  const p = sync.progress;
  const hasCounts =
    p !== null && p.processed_count !== null && p.total_count !== null;
  const pct = hasCounts
    ? Math.max(4, Math.round((p.processed_count! / p.total_count!) * 100))
    : null;

  return (
    <section className="bg-white rounded-lg border border-gray-200 shadow-sm p-6">
      <div className="flex items-start gap-6 flex-wrap">
        <div className="flex-1 min-w-0">
          <h2 className="text-sm font-semibold text-gray-900">Synchronizace</h2>
          <p className="text-[13px] text-gray-500 mt-1">
            Ruční stažení nahrávek z Plaud cloudu do místní složky.
          </p>
          {!isRunning && (
            <div className="mt-3 text-[13px] text-gray-600">
              {sync.last_run_at ? (
                <>
                  Poslední běh{" "}
                  <span className="text-gray-900 font-medium">
                    {relativeTime(sync.last_run_at) ?? "—"}
                  </span>{" "}
                  · {formatExactTime(sync.last_run_at)}
                </>
              ) : (
                <>Ještě nikdy neproběhla.</>
              )}
            </div>
          )}
        </div>
        <div className="flex-shrink-0">
          <button
            type="button"
            disabled={isRunning || startSyncDisabled}
            onClick={onSync}
            className={classNames(
              "inline-flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium shadow-sm transition-colors",
              isRunning
                ? "bg-blue-50 text-blue-700 border border-blue-200 cursor-not-allowed"
                : "bg-blue-600 text-white hover:bg-blue-700 border border-blue-600 disabled:opacity-60",
            )}
          >
            {isRunning ? (
              <>
                <svg
                  viewBox="0 0 24 24"
                  className="w-4 h-4 animate-spin"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.4"
                  strokeLinecap="round"
                  aria-hidden="true"
                >
                  <path d="M21 12a9 9 0 1 1-6.2-8.55" />
                </svg>
                <span>
                  {hasCounts
                    ? `Synchronizace… ${p!.processed_count} / ${p!.total_count}`
                    : "Synchronizace…"}
                </span>
              </>
            ) : (
              <>
                <svg
                  viewBox="0 0 24 24"
                  className="w-4 h-4"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.4"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <path d="M3 12a9 9 0 0 1 15.5-6.3L21 8" />
                  <path d="M21 4v4h-4" />
                  <path d="M21 12a9 9 0 0 1-15.5 6.3L3 16" />
                  <path d="M3 20v-4h4" />
                </svg>
                <span>Synchronizovat</span>
              </>
            )}
          </button>
        </div>
      </div>

      {isRunning && (
        <div className="mt-5">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[13px] font-medium text-gray-700">
              {phaseLabel(p)}
            </span>
            {hasCounts && (
              <span className="text-[13px] text-gray-500 font-mono">
                {p!.processed_count} / {p!.total_count}
              </span>
            )}
          </div>
          <div className="h-1.5 w-full bg-gray-100 rounded-full overflow-hidden relative">
            {hasCounts ? (
              <div
                className="h-full bg-blue-500 rounded-full transition-all duration-500"
                style={{ width: `${pct}%` }}
              />
            ) : (
              <div className="h-full bg-blue-500 rounded-full animate-ps-indeterminate w-1/4" />
            )}
          </div>
          {isTaskScheduler && (
            <div className="mt-2 text-xs text-gray-500 flex items-center gap-1.5">
              <svg
                viewBox="0 0 24 24"
                className="w-3.5 h-3.5"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <circle cx="12" cy="12" r="9" />
                <path d="M12 7v5l3 2" />
              </svg>
              Spuštěno Plánovačem úloh Windows
            </div>
          )}
        </div>
      )}
    </section>
  );
}
