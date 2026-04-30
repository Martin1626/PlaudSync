import type {
  ClassificationSource,
  ClassificationStatus,
} from "@/api/types";
import { classNames } from "@/utils/format";

interface Props {
  project: string | null;
  classification: ClassificationStatus;
  source: ClassificationSource | null;
  folderName: string | null;
}

const PILL_BASE =
  "inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium border";

const GRAY = "bg-gray-100 text-gray-600 border-gray-200";
const BLUE = "bg-blue-100 text-blue-700 border-blue-200";
const GREEN = "bg-green-100 text-green-700 border-green-200";

export default function ProjectBadge({
  project,
  classification,
  source,
  folderName,
}: Props) {
  // Render decision tree (BL-6 spec §4.2 — top to bottom, first match wins).
  // 1) unclassified or source='none' → gray "nezatříděno".
  if (classification === "unclassified" || source === "none") {
    return <span className={classNames(PILL_BASE, GRAY)}>nezatříděno</span>;
  }

  // 2) folder-classified → green pill with folder NAME.
  //    Empty-string sentinel from backend = folder ID present but missing in
  //    FiletagCache (renamed/deleted in Plaud) → render placeholder so the
  //    user knows to refresh the catalog.
  if (source === "folder") {
    const text = folderName ? folderName : "(neznámá složka)";
    return <span className={classNames(PILL_BASE, GREEN)}>{text}</span>;
  }

  // 3) name-classified OR legacy null source → blue pill with project code.
  //    Legacy fallback covers pre-BL-X recordings where classification_source
  //    column was unpopulated; preserves the old "matched → colored badge"
  //    behavior except palette is now a fixed blue rather than per-project hash.
  return (
    <span className={classNames(PILL_BASE, BLUE)}>{project ?? "—"}</span>
  );
}
