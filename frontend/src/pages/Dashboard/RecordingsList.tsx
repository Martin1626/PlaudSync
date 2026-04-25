import type { RecordingRow } from "@/api/types";
import { relativeTime } from "@/utils/format";

import ProjectBadge from "./ProjectBadge";
import StatusIcon from "./StatusIcon";

interface Props {
  recordings: RecordingRow[];
}

export default function RecordingsList({ recordings }: Props) {
  if (recordings.length === 0) {
    return (
      <section className="bg-white rounded-lg border border-gray-200 shadow-sm">
        <div className="p-12 text-center">
          <div className="mx-auto w-12 h-12 rounded-full bg-gray-100 text-gray-400 flex items-center justify-center mb-4">
            <svg
              viewBox="0 0 24 24"
              className="w-6 h-6"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M12 2a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z" />
              <path d="M19 10v1a7 7 0 0 1-14 0v-1" />
              <path d="M12 18v4M8 22h8" />
            </svg>
          </div>
          <h3 className="text-sm font-semibold text-gray-900">
            Ještě nemáš žádné nahrávky
          </h3>
          <p className="text-[13px] text-gray-500 mt-1 max-w-xs mx-auto">
            Klikni na{" "}
            <span className="font-medium text-gray-700">Synchronizovat</span> a
            stáhneš nahrávky z Plaud cloudu.
          </p>
        </div>
      </section>
    );
  }

  return (
    <section className="bg-white rounded-lg border border-gray-200 shadow-sm overflow-hidden">
      <div className="px-5 py-3 flex items-center justify-between border-b border-gray-100">
        <h3 className="text-sm font-semibold text-gray-900">Nahrávky</h3>
        <span className="text-xs text-gray-500 font-mono">
          {recordings.length} položek
        </span>
      </div>
      <ul className="divide-y divide-gray-100">
        {recordings.map((r) => (
          <li
            key={r.plaud_id}
            className="group flex items-center gap-4 px-5 py-3 hover:bg-gray-50 cursor-default"
          >
            <StatusIcon status={r.status} />
            <div className="flex-1 min-w-0">
              <div className="text-sm text-gray-900 truncate font-medium">
                {r.title}
              </div>
              <div className="text-xs text-gray-500 mt-1 flex items-center gap-2 font-mono">
                <span
                  className="inline-flex items-center gap-1 truncate"
                  title="Plaud složka"
                >
                  <svg
                    viewBox="0 0 24 24"
                    className="w-3 h-3 text-gray-400 flex-shrink-0"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                  >
                    <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z" />
                  </svg>
                  <span className="truncate">{r.plaud_folder || "—"}</span>
                </span>
                <span className="text-gray-300">·</span>
                <span>{relativeTime(r.downloaded_at) ?? "—"}</span>
              </div>
            </div>
            <ProjectBadge
              project={r.project}
              classification={r.classification_status}
            />
          </li>
        ))}
      </ul>
    </section>
  );
}
