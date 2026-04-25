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
  last_error_summary: string | null;
  progress: SyncProgress | null;
}

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

export interface ConfigResponse {
  raw_yaml: string;
  /** Schema-shaped: { unclassified_dir: string, projects: Record<string, string> }. */
  parsed: Record<string, unknown> | null;
  /** Present when GET reads an existing-but-invalid config.yaml from disk. */
  parse_error: ConfigParseError | null;
}

export interface ConfigSaveSuccess {
  ok: true;
  parsed: Record<string, unknown>;
}

export interface ConfigSaveErrors {
  ok: false;
  errors: ConfigParseError[];
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
