import { useConfig } from "@/api/hooks";

import ConfigPanel from "./ConfigPanel";
import ConnectionPanel from "./ConnectionPanel";

export default function Settings() {
  const { data, isPending, error } = useConfig();

  return (
    <div className="space-y-5">
      <ConnectionPanel />
      {isPending && !data ? (
        <div className="flex items-center justify-center py-12 bg-white rounded-lg border border-gray-200 shadow-sm">
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
          <span className="ml-3 text-sm text-gray-500">
            Načítám konfiguraci…
          </span>
        </div>
      ) : data ? (
        <ConfigPanel config={data} />
      ) : (
        <div className="bg-white rounded-lg border border-red-200 shadow-sm p-5 text-sm text-red-800">
          Konfiguraci se nepodařilo načíst.
          {error instanceof Error ? "" : null}
        </div>
      )}
    </div>
  );
}
