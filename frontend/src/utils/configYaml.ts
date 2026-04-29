/**
 * Minimal YAML round-trip helpers for ConfigParsedV4.
 *
 * Scope is intentionally narrow: our config has a bounded shape (one
 * top-level mapping with known keys), so a hand-rolled serializer is
 * preferable to a 150 KB js-yaml dependency. Bundle size budget is
 * tight per SPEC.md.
 *
 * Coercer: tolerates legacy v0.3 layout (`projects: {KOD: <path-string>}`)
 * by normalising to v0.4 ProjectEntry shape on read. Backend's load_config
 * does the same on its side.
 *
 * Serializer: emits canonical v0.4 YAML — every project as a sub-mapping
 * with `path` + `plaud_folder_id` keys. Strings with YAML-special chars
 * (`:`, `#`, leading/trailing whitespace) are double-quoted with backslash
 * escaping.
 */
import type { ConfigParsedV4, ProjectEntry } from "@/api/types";

/** YAML reserved tokens that force quoting if present in a scalar. */
const _NEEDS_QUOTING = /[:#&*!|>'"%@`,\[\]\{\}]|^\s|\s$/;

function _quote(s: string): string {
  if (!_NEEDS_QUOTING.test(s) && s.length > 0) {
    return s;
  }
  // Double-quote with JSON-compatible escaping. yaml.safe_load accepts.
  return JSON.stringify(s);
}

/**
 * Coerce loose `parsed` from /api/config into typed ConfigParsedV4.
 *
 * - Legacy `projects[k]: string` → `{ path: string, plaud_folder_id: null }`.
 * - Missing flags → undefined (consumer reads with defaults).
 * - Returns null if the shape is fundamentally unrecognisable.
 */
export function coerceConfigV4(
  parsed: Record<string, unknown> | null | undefined,
): ConfigParsedV4 | null {
  if (!parsed || typeof parsed !== "object") return null;
  const unclassified = parsed["unclassified_dir"];
  if (typeof unclassified !== "string") return null;

  const projectsRaw = parsed["projects"];
  if (projectsRaw == null || typeof projectsRaw !== "object") {
    return null;
  }

  const projects: Record<string, ProjectEntry> = {};
  for (const [key, value] of Object.entries(projectsRaw as Record<string, unknown>)) {
    if (typeof value === "string") {
      projects[key] = { path: value, plaud_folder_id: null };
    } else if (value != null && typeof value === "object") {
      const obj = value as Record<string, unknown>;
      const path = obj["path"];
      const folderId = obj["plaud_folder_id"];
      if (typeof path !== "string") continue;
      projects[key] = {
        path,
        plaud_folder_id: typeof folderId === "string" ? folderId : null,
      };
    }
  }

  // exactOptionalPropertyTypes: omit keys whose value would be undefined
  // rather than assigning undefined (which is not the same shape).
  const result: ConfigParsedV4 = {
    unclassified_dir: unclassified,
    projects,
  };
  for (const k of [
    "download_audio",
    "download_content",
    "classify_by_name",
    "classify_by_name_require_folder",
    "classify_by_folder",
    "sync_unclassified",
  ] as const) {
    const v = parsed[k];
    if (typeof v === "boolean") {
      result[k] = v;
    }
  }
  return result;
}

/** Default values for BL-X flags (mirrors backend Config dataclass). */
export const CONFIG_DEFAULTS = {
  download_audio: true,
  download_content: true,
  classify_by_name: true,
  classify_by_name_require_folder: false,
  classify_by_folder: false,
  sync_unclassified: false,
} as const;

/** Read a flag with default fallback. */
export function flagOrDefault(
  config: ConfigParsedV4,
  key: keyof typeof CONFIG_DEFAULTS,
): boolean {
  const raw = config[key];
  return typeof raw === "boolean" ? raw : CONFIG_DEFAULTS[key];
}

/**
 * Serialize ConfigParsedV4 to canonical v0.4 YAML.
 *
 * Format:
 *   unclassified_dir: "C:\\..."
 *   projects:
 *     KOD:
 *       path: "C:\\..."
 *       plaud_folder_id: "abc123"   # or null
 *   download_audio: true
 *   download_content: true
 *   classify_by_name: true
 *   classify_by_name_require_folder: false
 *   classify_by_folder: false
 *   sync_unclassified: false
 *
 * Always emits all 6 BL-X flags explicitly (no implicit defaults) so a
 * reader can see the full configuration without consulting backend code.
 */
export function serializeConfigV4(config: ConfigParsedV4): string {
  const lines: string[] = [];
  lines.push(`unclassified_dir: ${_quote(config.unclassified_dir)}`);

  const projectKeys = Object.keys(config.projects);
  if (projectKeys.length === 0) {
    lines.push("projects: {}");
  } else {
    lines.push("projects:");
    for (const key of projectKeys) {
      const entry = config.projects[key];
      if (!entry) continue;  // type-narrow for noUncheckedIndexedAccess
      lines.push(`  ${_quote(key)}:`);
      lines.push(`    path: ${_quote(entry.path)}`);
      const folderId = entry.plaud_folder_id;
      lines.push(
        `    plaud_folder_id: ${folderId == null ? "null" : _quote(folderId)}`,
      );
    }
  }

  lines.push(`download_audio: ${flagOrDefault(config, "download_audio")}`);
  lines.push(`download_content: ${flagOrDefault(config, "download_content")}`);
  lines.push(`classify_by_name: ${flagOrDefault(config, "classify_by_name")}`);
  lines.push(
    `classify_by_name_require_folder: ${flagOrDefault(config, "classify_by_name_require_folder")}`,
  );
  lines.push(`classify_by_folder: ${flagOrDefault(config, "classify_by_folder")}`);
  lines.push(`sync_unclassified: ${flagOrDefault(config, "sync_unclassified")}`);

  return lines.join("\n") + "\n";
}
