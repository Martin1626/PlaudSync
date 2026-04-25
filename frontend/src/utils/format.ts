import type { SyncProgress } from "@/api/types";

export function classNames(
  ...xs: Array<string | false | null | undefined>
): string {
  return xs.filter(Boolean).join(" ");
}

/**
 * Relative time in Czech. Mirrors prototype proto:264-278 exactly.
 * Returns null when iso is null/undefined so callers can short-circuit.
 */
export function relativeTime(
  iso: string | null | undefined,
  now: Date = new Date(),
): string | null {
  if (!iso) return null;
  const a = new Date(iso).getTime();
  const b = now.getTime();
  const diffMin = Math.round((b - a) / 60000);
  if (diffMin < 1) return "právě teď";
  if (diffMin < 60) return `před ${diffMin} min`;
  const hours = Math.round(diffMin / 60);
  if (hours < 24) return `před ${hours} h`;
  const days = Math.round(hours / 24);
  if (days === 1) return "včera";
  if (days < 7) return `před ${days} dny`;
  const d = new Date(iso);
  return d.toLocaleDateString("cs-CZ", { month: "short", day: "numeric" });
}

/**
 * Exact local time, Czech locale. Prototype proto:280-287.
 * Format: "23. dub 14:32".
 */
export function formatExactTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("cs-CZ", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * Czech sync phase label. Prototype proto:289-299.
 */
export function phaseLabel(p: SyncProgress | null | undefined): string {
  if (!p) return "Pracuji…";
  const { phase, processed_count, total_count } = p;
  switch (phase) {
    case "listing":
      return "Načítám seznam nahrávek…";
    case "downloading":
      return `Stahuji ${processed_count} z ${total_count}`;
    case "categorizing":
      return `Kategorizuji ${processed_count} z ${total_count}`;
    case "finalizing":
      return "Ukládám metadata…";
    default:
      return "Pracuji…";
  }
}
