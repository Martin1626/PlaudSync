import type { ClassificationStatus } from "@/api/types";
import { classNames } from "@/utils/format";
import { projectBadgeColor } from "@/utils/colors";

interface Props {
  project: string | null;
  classification: ClassificationStatus;
}

export default function ProjectBadge({ project, classification }: Props) {
  if (classification === "unclassified" || !project) {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium bg-gray-100 text-gray-600 border border-gray-200">
        nezatříděno
      </span>
    );
  }
  const c = projectBadgeColor(project);
  return (
    <span
      className={classNames(
        "inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium border",
        c.bg,
        c.text,
        c.border,
      )}
    >
      {project}
    </span>
  );
}
