import type {
  ClassificationSource,
  ClassificationStatus,
  RecordingStatus,
} from "@/api/types";
import { classNames } from "@/utils/format";

interface Props {
  project: string | null;
  classification: ClassificationStatus;
  source: ClassificationSource | null;
  folderName: string | null;
  status: RecordingStatus;
}

const PILL_BASE =
  "inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium border";

const BLUE = "bg-blue-100 text-blue-700 border-blue-200";
const GREEN = "bg-green-100 text-green-700 border-green-200";
const GRAY = "bg-gray-100 text-gray-600 border-gray-200";

const IGNORED_TOOLTIP =
  "Nahrávka neodpovídá žádné klasifikační strategii. Možnosti:\n" +
  "• přidat KOD: do názvu na Plaude\n" +
  "• přesunout nahrávku do mapované Plaud složky\n" +
  "• zapnout „Synchronizovat i to, co nelze roztřídit\" v Settings";

export default function ProjectBadge({
  project,
  classification,
  source,
  folderName,
  status,
}: Props) {
  // BL-7: skip-source → šedá "ignorováno" pilulka s tooltipem vysvětlujícím,
  // proč PlaudSync nahrávku nestáhl + jak ji obnovit. Tato větev musí být
  // PŘED kontrolou status/classification, protože skip rows mají
  // status='skipped' a classification='unclassified'.
  if (source === "skip") {
    return (
      <span className={classNames(PILL_BASE, GRAY)} title={IGNORED_TOOLTIP}>
        ignorováno
      </span>
    );
  }

  // Badge se zobrazuje jen pro nahrávky úspěšně zařazené do projektu (v configu)
  // nebo do Plaud složky. Skipped (vč. skipped_unknown_project — projekt
  // detekován z titulu, ale není v configu) a failed nedostávají badge.
  if (status !== "downloaded") return null;
  if (classification === "unclassified" || source === "none") return null;

  // folder-classified → zelený badge s názvem Plaud složky.
  // Cache miss (folder přejmenován/smazán v Plaud) → "(neznámá složka)".
  if (source === "folder") {
    const text = folderName ? folderName : "(neznámá složka)";
    return <span className={classNames(PILL_BASE, GREEN)}>{text}</span>;
  }

  // name-classified nebo legacy null → modrý badge s project codem.
  // Legacy fallback: rec stažena před BL-X → classification_source NULL,
  // ale label v configu existuje (jinak by nebyla downloaded).
  if (!project) return null;
  return <span className={classNames(PILL_BASE, BLUE)}>{project}</span>;
}
