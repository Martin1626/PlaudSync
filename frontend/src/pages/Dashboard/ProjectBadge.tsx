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

const IGNORED_TOOLTIP_NO_STRATEGY =
  "Nahrávka neodpovídá žádné klasifikační strategii. Možnosti:\n" +
  "• přidat KOD: do názvu na Plaude\n" +
  "• přesunout nahrávku do mapované Plaud složky\n" +
  "• zapnout „Synchronizovat i to, co nelze roztřídit\" v Settings";

const IGNORED_TOOLTIP_AUDIO_OFF =
  "Stahování audio je vypnuté v Settings → zapni \"Stahovat audio\" "
  + "a další sync nahrávku stáhne.";

function ignoredTooltip(
  source: ClassificationSource | null,
  project: string | null,
): string {
  // BL-7 skip-source: žádná strategie nematchla. Recovery = title rename /
  // folder mapping / sync_unclassified flip.
  if (source === "skip") return IGNORED_TOOLTIP_NO_STRATEGY;
  // BL-3 skipped_unknown_project (wire collapses to status='skipped',
  // source='name', project=<title-extracted-code>): projekt je v titulu,
  // ale chybí v configu. Recovery = přidat project do Settings.
  if (source === "name" && project) {
    return (
      "Projekt \"" + project + "\" není v Settings configu — přidej ho "
      + "v Settings a další sync nahrávku stáhne."
    );
  }
  // download_audio=false na matched row (name/folder/none) → status='skipped',
  // ale source je už klasifikační. Source 'folder'/'none' nebo 'name' bez
  // projectu padá sem; recovery = zapnout audio download.
  return IGNORED_TOOLTIP_AUDIO_OFF;
}

export default function ProjectBadge({
  project,
  classification,
  source,
  folderName,
  status,
}: Props) {
  // Sjednocený "ignorováno" badge pro všechny skipped rows (BL-7 follow-up
  // 2026-05-03): ať už source='skip' (BL-7), 'name'+project (BL-3
  // skipped_unknown_project), nebo audio-gate-off, user vidí konzistentní
  // šedou pilulku se source-specifickým tooltipem vysvětlujícím recovery.
  // Pre-fix: jen source='skip' měla badge — ostatní skipped rows neměly
  // žádný visual signal a user nevěděl proč PlaudSync nahrávku nestáhl.
  // Failed rows zůstávají bez badge — mají vlastní červenou status ikonu.
  if (status === "skipped") {
    return (
      <span
        className={classNames(PILL_BASE, GRAY)}
        title={ignoredTooltip(source, project)}
      >
        ignorováno
      </span>
    );
  }

  // Badge se zobrazuje jen pro nahrávky úspěšně zařazené do projektu (v configu)
  // nebo do Plaud složky. Failed rows mají vlastní červenou status ikonu.
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
