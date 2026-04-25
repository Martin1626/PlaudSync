export interface BadgeColor {
  bg: string;
  text: string;
  border: string;
}

const PALETTE: readonly BadgeColor[] = [
  { bg: "bg-blue-50", text: "text-blue-700", border: "border-blue-200" },
  { bg: "bg-indigo-50", text: "text-indigo-700", border: "border-indigo-200" },
  { bg: "bg-sky-50", text: "text-sky-700", border: "border-sky-200" },
  { bg: "bg-violet-50", text: "text-violet-700", border: "border-violet-200" },
];

/**
 * Stable hash → palette pick. Same project name always yields the same color.
 * Mirrors prototype proto:840-841 hash function exactly so existing visual
 * snapshots remain valid.
 */
export function projectBadgeColor(projectName: string): BadgeColor {
  let h = 0;
  for (let i = 0; i < projectName.length; i++) {
    h = (h * 31 + projectName.charCodeAt(i)) >>> 0;
  }
  // PALETTE has length 4 > 0, so non-null assertion is safe.
  return PALETTE[h % PALETTE.length]!;
}
