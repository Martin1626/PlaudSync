export type SyncStatus = "idle" | "running";
export type SyncTrigger = "task_scheduler" | "ui_sync_now" | "manual";
export type SyncOutcome = "success" | "partial_failure" | "failed";
export type SyncPhase = "listing" | "downloading" | "categorizing" | "finalizing";
export type ClassificationStatus = "matched" | "unclassified";
export type RecordingStatus = "downloaded" | "failed" | "skipped";

export interface SyncProgress {
  phase: SyncPhase | null;
  processed_count: number | null;
  total_count: number | null;
}

export interface SyncState {
  status: SyncStatus;
  trigger: SyncTrigger | null;
  started_at: string | null;
  last_run_at: string | null;
  last_run_outcome: SyncOutcome | null;
  last_run_exit_code: number | null;
  last_run_new_count: number | null;
  last_run_skipped_count: number | null;
  last_run_failed_count: number | null;
  last_error_summary: string | null;
  progress: SyncProgress | null;
}

export type ClassificationSource = "name" | "folder" | "none" | "skip";

export interface RecordingRow {
  plaud_id: string;
  title: string;
  created_at: string;
  downloaded_at: string;
  plaud_folder: string;
  classification_status: ClassificationStatus;
  project: string | null;
  target_dir: string;
  status: RecordingStatus;
  /** BL-6 / BL-7: source-aware project badge.
   *  - "name"   → matched by title regex; badge shows project code (blue)
   *  - "folder" → matched by Plaud folder fallback; badge shows folderName (green)
   *  - "none"   → unclassified catch-all (gray)
   *  - "skip"   → BL-7: ignored (no strategy matched + sync_unclassified=false);
   *               badge shows "ignorováno" (gray) with tooltip explaining recovery
   *  - null     → legacy pre-BL-X row; render as "name" fallback */
  classification_source: ClassificationSource | null;
  /** BL-6: resolved Plaud folder name (FiletagCache lookup).
   *  - string   → folder found in cache
   *  - ""       → folder ID present but missing in cache (renamed/deleted in Plaud)
   *  - null     → no folder ID persisted (e.g., name-classified or legacy) */
  plaud_folder_name: string | null;
}

export interface StateResponse {
  sync: SyncState;
  recordings: RecordingRow[];
}

// ---------------- Auth ----------------

export type AuthFailureReason = "PlaudTokenExpired" | "PlaudTokenMissing";

export interface AuthVerifyResponse {
  ok: boolean;
  reason: AuthFailureReason | null;
  /**
   * Server-provided human-readable message (Czech), surfaced verbatim into
   * a UI banner when verify fails. Per Settings spec D11 privacy discipline,
   * the backend MUST NOT embed filesystem paths, project names, recording
   * titles, token bytes, or other business identifiers in this string —
   * only static labels and (optionally) numeric values.
   */
  message: string | null;
  /**
   * Server-rendered mask (first_8 + 15 dots + last_4) per Settings spec v0.1
   * Gap 2 Option A. `null` only when the token is literally absent
   * (`PlaudTokenMissing`).
   */
  masked_token: string | null;
}

// ---------------- Config ----------------

export interface ConfigParseError {
  line: number;
  message: string;
}

/**
 * Per-project entry shape (v0.4 — BL-4/BL-X). Backend serializes
 * `projects[name]` as `{ path, plaud_folder_id }` since v0.4. Older
 * single-string shape only appears in raw YAML the user typed manually
 * (loader normalizes to dict on first save).
 */
export interface ProjectEntry {
  path: string;
  plaud_folder_id: string | null;
}

/**
 * Typed projection of the parsed config. Mirrors plaudsync.ui.config_io
 * `_config_to_dict` output shape (v0.4). All BL-X flags optional with
 * defaults — read missing flags as their default to be tolerant against
 * partial-write configs.
 */
export interface ConfigParsedV4 {
  unclassified_dir: string;
  projects: Record<string, ProjectEntry>;
  download_audio?: boolean;
  download_content?: boolean;
  classify_by_name?: boolean;
  classify_by_name_require_folder?: boolean;
  classify_by_folder?: boolean;
  sync_unclassified?: boolean;
}

export interface ConfigResponse {
  raw_yaml: string;
  /** Schema-shaped per ConfigParsedV4 — but typed as Record for tolerance to
   * legacy single-string project values still on disk. Use parseConfigV4()
   * helper to coerce to ConfigParsedV4. */
  parsed: Record<string, unknown> | null;
  /** Present when GET reads an existing-but-invalid config.yaml from disk. */
  parse_error: ConfigParseError | null;
}

export interface ConfigSaveSuccess {
  ok: true;
  parsed: Record<string, unknown>;
  /** X-Plaudsync-Warning header values (BL-X spec §3): 'no-artifacts',
   * 'folder-not-in-catalog'. Empty array when no warnings. */
  warnings: string[];
}

export interface ConfigSaveErrors {
  ok: false;
  errors: ConfigParseError[];
}

// ---------------- Folder catalog (BL-X) ----------------

export interface FolderItem {
  id: string;
  name: string;
}

export interface FoldersResponse {
  folders: FolderItem[];
  fetched_at: string | null;
  stale: boolean;
}

// ---------------- Schedule ----------------

export interface Schedule {
  work_hours_interval_minutes: number;
  off_hours_interval_minutes: number;
  /** ISO weekdays: 1=Mon..7=Sun. */
  work_days: number[];
  /** "HH:MM" 24h, local time. */
  work_from: string;
  work_to: string;
}

export interface ScheduleSaveError {
  /** Free-form field-level message returned by parse_schedule. */
  message: string;
}

// ---------------- Sync trigger ----------------

export interface StartSyncResponse {
  sync_id: string;
  started_at: string;
}

export interface StartSyncConflict {
  ok: false;
  reason: "already_running";
  started_at: string;
  by: SyncTrigger;
}

export interface StartSyncFailure {
  ok: false;
  reason: "spawn_failed";
  message: string;
  exit_code?: number;
}
