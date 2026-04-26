import { useState } from "react";

import type { ConfigParseError } from "@/api/types";
import { classNames } from "@/utils/format";

interface Props {
  errors: ConfigParseError[];
  /** Index into errors array — which one is "current" (gutter highlight + footer). */
  currentIndex: number;
  onSelect: (index: number) => void;
}

export default function InlineConfigErrors({
  errors,
  currentIndex,
  onSelect,
}: Props) {
  const [expanded, setExpanded] = useState(false);
  if (errors.length === 0) return null;

  // currentIndex bounds-checked at call site; we still defend.
  const current = errors[currentIndex] ?? errors[0]!;
  const remaining = errors.length - 1;

  return (
    <div className="border-t border-red-200 bg-red-50">
      <div className="px-4 py-2 text-[13px] text-red-800 flex items-center gap-2">
        <svg
          viewBox="0 0 24 24"
          className="w-4 h-4 text-red-600 flex-shrink-0"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <circle cx="12" cy="12" r="9" />
          <path d="M12 8v4M12 16h.01" />
        </svg>
        <span className="flex-1">
          {current.line > 0 && (
            <>
              <span className="font-mono font-semibold">
                Řádek {current.line}:
              </span>{" "}
            </>
          )}
          {current.message}
        </span>
        {remaining > 0 && (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="text-red-700 underline text-[13px] font-medium"
          >
            {expanded ? "Skrýt seznam" : `(+${remaining} dalších chyb)`}
          </button>
        )}
      </div>
      {expanded && remaining > 0 && (
        <ul className="border-t border-red-200 bg-red-50/60 px-4 py-2 space-y-1">
          {errors.map((err, idx) => (
            <li key={`${err.line}-${idx}`}>
              <button
                type="button"
                onClick={() => {
                  onSelect(idx);
                  setExpanded(false);
                }}
                className={classNames(
                  "w-full text-left text-[13px] px-2 py-1 rounded hover:bg-red-100",
                  idx === currentIndex
                    ? "text-red-900 font-medium bg-red-100"
                    : "text-red-800",
                )}
              >
                {err.line > 0 && (
                  <>
                    <span className="font-mono font-semibold">
                      Řádek {err.line}:
                    </span>{" "}
                  </>
                )}
                {err.message}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
