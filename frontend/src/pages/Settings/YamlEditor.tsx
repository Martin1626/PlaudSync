import { useRef, type KeyboardEvent, type UIEvent } from "react";

import type { ConfigParseError } from "@/api/types";
import { classNames } from "@/utils/format";

import InlineConfigErrors from "./InlineConfigErrors";

interface Props {
  value: string;
  onChange: (next: string) => void;
  errors: ConfigParseError[];
  /** Index into `errors` for gutter highlight + inline footer. -1 if no current. */
  currentErrorIndex: number;
  onSelectError: (index: number) => void;
}

const TAB_INSERT = "  "; // 2 spaces, matches Settings D5 tab-size: 2.

export default function YamlEditor({
  value,
  onChange,
  errors,
  currentErrorIndex,
  onSelectError,
}: Props) {
  const taRef = useRef<HTMLTextAreaElement>(null);
  const lineNumsRef = useRef<HTMLDivElement>(null);
  const lines = value.split("\n");

  const onScroll = (e: UIEvent<HTMLTextAreaElement>) => {
    if (lineNumsRef.current) {
      lineNumsRef.current.scrollTop = e.currentTarget.scrollTop;
    }
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    const ta = e.currentTarget;
    // Esc — blur to release focus trap (Settings Gap 9 escape hatch).
    if (e.key === "Escape") {
      e.preventDefault();
      ta.blur();
      return;
    }
    if (e.key !== "Tab") return;

    e.preventDefault();
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    const before = value.slice(0, start);
    const selection = value.slice(start, end);
    const after = value.slice(end);

    if (selection.includes("\n")) {
      // Multi-line indent / dedent.
      const lineStart = before.lastIndexOf("\n") + 1;
      const block = value.slice(lineStart, end);
      if (e.shiftKey) {
        const dedented = block
          .split("\n")
          .map((ln) => (ln.startsWith(TAB_INSERT) ? ln.slice(TAB_INSERT.length) : ln))
          .join("\n");
        const next = value.slice(0, lineStart) + dedented + after;
        onChange(next);
        const removed = block.length - dedented.length;
        requestAnimationFrame(() => {
          ta.selectionStart = Math.max(lineStart, start - TAB_INSERT.length);
          ta.selectionEnd = end - removed;
        });
      } else {
        const indented = block
          .split("\n")
          .map((ln) => TAB_INSERT + ln)
          .join("\n");
        const next = value.slice(0, lineStart) + indented + after;
        onChange(next);
        const added = indented.length - block.length;
        requestAnimationFrame(() => {
          ta.selectionStart = start + TAB_INSERT.length;
          ta.selectionEnd = end + added;
        });
      }
      return;
    }

    // Caret-only: insert 2 spaces (or, with Shift, dedent the current line).
    if (e.shiftKey) {
      const lineStart = before.lastIndexOf("\n") + 1;
      const lineHead = value.slice(lineStart, start);
      if (lineHead.startsWith(TAB_INSERT)) {
        const next =
          value.slice(0, lineStart) +
          lineHead.slice(TAB_INSERT.length) +
          value.slice(start);
        onChange(next);
        requestAnimationFrame(() => {
          ta.selectionStart = ta.selectionEnd = start - TAB_INSERT.length;
        });
      }
      return;
    }
    const next = before + TAB_INSERT + after;
    onChange(next);
    requestAnimationFrame(() => {
      ta.selectionStart = ta.selectionEnd = start + TAB_INSERT.length;
    });
  };

  const currentLine =
    currentErrorIndex >= 0 && currentErrorIndex < errors.length
      ? errors[currentErrorIndex]!.line
      : -1;

  const hasError = errors.length > 0;

  return (
    <div
      className={classNames(
        "rounded-md border bg-white overflow-hidden",
        hasError ? "border-red-300" : "border-gray-200",
      )}
    >
      <div className="flex">
        <div
          ref={lineNumsRef}
          aria-hidden="true"
          className="yaml-line-numbers flex-shrink-0 bg-gray-50 border-r border-gray-100 text-right pr-3 pl-3 py-3 select-none overflow-hidden"
          style={{ height: 400, width: 48 }}
        >
          {lines.map((_, i) => (
            <div
              key={i}
              className={classNames(
                "transition-colors",
                currentLine === i + 1
                  ? "text-red-600 font-semibold bg-red-50 -mx-3 px-3"
                  : "text-gray-400",
              )}
            >
              {i + 1}
            </div>
          ))}
        </div>
        <textarea
          ref={taRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onScroll={onScroll}
          onKeyDown={onKeyDown}
          spellCheck={false}
          aria-label="Konfigurace YAML"
          className="yaml-textarea flex-1 py-3 px-3 outline-none resize-none text-gray-800 bg-white"
          style={{ height: 400 }}
        />
      </div>
      <InlineConfigErrors
        errors={errors}
        currentIndex={currentErrorIndex}
        onSelect={onSelectError}
      />
      {/* Tab/Esc helper hint per Settings Gap 9 */}
      <div className="px-4 py-2 border-t border-gray-100 text-[11px] text-gray-400 bg-gray-50/40">
        Tab pro odsazení • Shift+Tab pro zúžení • Esc pro opuštění editoru
      </div>
    </div>
  );
}
