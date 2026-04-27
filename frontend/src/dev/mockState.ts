import type { RecordingRow, StateResponse } from "@/api/types";

export const NOW_ISO = "2026-04-25T13:05:30+02:00";

export const SAMPLE_RECORDINGS_FULL: RecordingRow[] = [
  {
    plaud_id: "rec_012",
    title: "04-25 ProjektAlfa: Kickoff sync s týmem",
    created_at: "2026-04-25T12:58:00+02:00",
    downloaded_at: "2026-04-25T13:00:30+02:00",
    plaud_folder: "Meetings/ProjektAlfa",
    classification_status: "matched",
    project: "ProjektAlfa",
    target_dir: "C:\\Projects\\Alpha\\Recordings",
    status: "downloaded",
  },
  {
    plaud_id: "rec_011",
    title: "04-25 1:1 s Honzou — roadmap Q3",
    created_at: "2026-04-25T11:30:00+02:00",
    downloaded_at: "2026-04-25T13:00:25+02:00",
    plaud_folder: "Meetings/Interní",
    classification_status: "matched",
    project: "Interní",
    target_dir: "E:\\Work\\Interni",
    status: "downloaded",
  },
  {
    plaud_id: "rec_010",
    title: "04-25 Klient Beta — review specifikace",
    created_at: "2026-04-25T09:15:00+02:00",
    downloaded_at: "2026-04-25T13:00:20+02:00",
    plaud_folder: "Klienti/Beta",
    classification_status: "matched",
    project: "KlientBeta",
    target_dir: "D:\\Clients\\Beta\\Audio",
    status: "downloaded",
  },
  {
    plaud_id: "rec_009",
    title: "04-24 Voice memo — nápady na onboarding",
    created_at: "2026-04-24T18:42:00+02:00",
    downloaded_at: "2026-04-25T13:00:18+02:00",
    plaud_folder: "Inbox",
    classification_status: "unclassified",
    project: null,
    target_dir: "D:\\Recordings\\Unclassified\\Inbox",
    status: "downloaded",
  },
  {
    plaud_id: "rec_008",
    title: "04-24 Standup — backend tým",
    created_at: "2026-04-24T09:00:00+02:00",
    downloaded_at: "2026-04-24T17:00:12+02:00",
    plaud_folder: "Meetings/Interní",
    classification_status: "matched",
    project: "Interní",
    target_dir: "E:\\Work\\Interni",
    status: "downloaded",
  },
  {
    plaud_id: "rec_003",
    title: "04-21 Voice memo — nepodařilo se stáhnout",
    created_at: "2026-04-21T19:11:00+02:00",
    downloaded_at: "2026-04-21T17:00:04+02:00",
    plaud_folder: "Inbox",
    classification_status: "unclassified",
    project: null,
    target_dir: "D:\\Recordings\\Unclassified\\Inbox",
    status: "failed",
  },
  {
    plaud_id: "rec_001",
    title: "04-20 Onboarding — nový kolega",
    created_at: "2026-04-20T10:00:00+02:00",
    downloaded_at: "2026-04-20T17:00:01+02:00",
    plaud_folder: "Meetings/Interní",
    classification_status: "matched",
    project: "Interní",
    target_dir: "E:\\Work\\Interni",
    status: "skipped",
  },
];

export type ScenarioKey =
  | "idle"
  | "running"
  | "running_by_task_scheduler"
  | "partial_failure"
  | "failed"
  | "empty";

export interface Scenario {
  label: string;
  desc: string;
  state: StateResponse;
}

export const SCENARIOS: Record<ScenarioKey, Scenario> = {
  idle: {
    label: "Idle",
    desc: "Last run succeeded; no banner",
    state: {
      sync: {
        status: "idle",
        trigger: null,
        started_at: null,
        last_run_at: "2026-04-25T12:00:00+02:00",
        last_run_outcome: "success",
        last_run_exit_code: 0,
        last_run_new_count: null,
        last_run_skipped_count: null,
        last_run_failed_count: null,
        last_error_summary: null,
        progress: null,
      },
      recordings: SAMPLE_RECORDINGS_FULL,
    },
  },
  running: {
    label: "Running (UI)",
    desc: "UI-spawned sync, downloading 3/12",
    state: {
      sync: {
        status: "running",
        trigger: "ui_sync_now",
        started_at: "2026-04-25T13:05:00+02:00",
        last_run_at: "2026-04-25T12:00:00+02:00",
        last_run_outcome: "success",
        last_run_exit_code: 0,
        last_run_new_count: null,
        last_run_skipped_count: null,
        last_run_failed_count: null,
        last_error_summary: null,
        progress: { phase: "downloading", processed_count: 3, total_count: 12 },
      },
      recordings: SAMPLE_RECORDINGS_FULL.slice(0, 3),
    },
  },
  running_by_task_scheduler: {
    label: "Running (Task Scheduler)",
    desc: "Spawned by Windows Task Scheduler",
    state: {
      sync: {
        status: "running",
        trigger: "task_scheduler",
        started_at: "2026-04-25T13:00:00+02:00",
        last_run_at: "2026-04-25T12:00:00+02:00",
        last_run_outcome: "success",
        last_run_exit_code: 0,
        last_run_new_count: null,
        last_run_skipped_count: null,
        last_run_failed_count: null,
        last_error_summary: null,
        progress: {
          phase: "categorizing",
          processed_count: 8,
          total_count: 12,
        },
      },
      recordings: SAMPLE_RECORDINGS_FULL.slice(0, 5),
    },
  },
  partial_failure: {
    label: "Partial failure",
    desc: "Last run exit 4 — orange banner",
    state: {
      sync: {
        status: "idle",
        trigger: null,
        started_at: null,
        last_run_at: "2026-04-25T13:05:00+02:00",
        last_run_outcome: "partial_failure",
        last_run_exit_code: 4,
        last_run_new_count: null,
        last_run_skipped_count: null,
        last_run_failed_count: null,
        last_error_summary: "2 recordings failed to download",
        progress: null,
      },
      recordings: SAMPLE_RECORDINGS_FULL,
    },
  },
  failed: {
    label: "Failed",
    desc: "Last run exit 1 — red banner",
    state: {
      sync: {
        status: "idle",
        trigger: null,
        started_at: null,
        last_run_at: "2026-04-25T13:05:00+02:00",
        last_run_outcome: "failed",
        last_run_exit_code: 1,
        last_run_new_count: null,
        last_run_skipped_count: null,
        last_run_failed_count: null,
        last_error_summary: "Network unreachable while listing recordings",
        progress: null,
      },
      recordings: SAMPLE_RECORDINGS_FULL.slice(2),
    },
  },
  empty: {
    label: "Empty (fresh install)",
    desc: "No recordings, never synced",
    state: {
      sync: {
        status: "idle",
        trigger: null,
        started_at: null,
        last_run_at: null,
        last_run_outcome: null,
        last_run_exit_code: null,
        last_run_new_count: null,
        last_run_skipped_count: null,
        last_run_failed_count: null,
        last_error_summary: null,
        progress: null,
      },
      recordings: [],
    },
  },
};

export const MOCK_CONFIG_RAW = `unclassified_dir: \${STATE_ROOT}\\Recordings\\Unclassified

projects:
  ProjektAlfa: \${STATE_ROOT}\\Recordings\\ProjektAlfa
  KlientBeta: \${STATE_ROOT}\\Recordings\\KlientBeta
  Interní: \${STATE_ROOT}\\Recordings\\Interní
`;
