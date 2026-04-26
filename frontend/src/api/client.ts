import type {
  AuthVerifyResponse,
  ConfigParseError,
  ConfigResponse,
  ConfigSaveSuccess,
  Schedule,
  StartSyncResponse,
  StartSyncConflict,
  StateResponse,
  SyncTrigger,
} from "./types";

// ---------------- Error taxonomy ----------------

export class ApiNetworkError extends Error {
  constructor(message: string, public readonly cause?: unknown) {
    super(message);
    this.name = "ApiNetworkError";
  }
}

export class ApiHttpError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: unknown,
    message?: string,
  ) {
    super(message ?? `HTTP ${status}`);
    this.name = "ApiHttpError";
  }
}

export class ValidationError extends ApiHttpError {
  public readonly errors: ConfigParseError[];
  constructor(body: { ok: false; errors: ConfigParseError[] }) {
    super(422, body, "Configuration validation failed");
    this.name = "ValidationError";
    this.errors = body.errors;
  }
}

export class ScheduleValidationError extends ApiHttpError {
  public readonly errors: string[];
  constructor(body: { ok: false; errors: string[] }) {
    super(422, body, "Schedule validation failed");
    this.name = "ScheduleValidationError";
    this.errors = body.errors;
  }
}

export class ConflictError extends ApiHttpError {
  public readonly startedAt: string;
  public readonly by: SyncTrigger;
  constructor(body: StartSyncConflict) {
    super(409, body, "Sync already running");
    this.name = "ConflictError";
    this.startedAt = body.started_at;
    this.by = body.by;
  }
}

// ---------------- Low-level fetch ----------------

async function fetchJson<T>(input: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(input, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.headers ?? {}),
      },
    });
  } catch (err) {
    throw new ApiNetworkError("Network request failed", err);
  }

  let body: unknown = null;
  const text = await response.text();
  if (text.length > 0) {
    try {
      body = JSON.parse(text);
    } catch {
      // Non-JSON body (e.g. HTML error page) — keep as text on body field.
      body = { raw: text };
    }
  }

  if (!response.ok) {
    throw new ApiHttpError(response.status, body);
  }
  return body as T;
}

// ---------------- Endpoint methods ----------------

export function fetchState(): Promise<StateResponse> {
  return fetchJson<StateResponse>("/api/state");
}

export function fetchConfig(): Promise<ConfigResponse> {
  return fetchJson<ConfigResponse>("/api/config");
}

export async function putConfig(rawYaml: string): Promise<ConfigSaveSuccess> {
  try {
    return await fetchJson<ConfigSaveSuccess>("/api/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ raw_yaml: rawYaml }),
    });
  } catch (err) {
    if (err instanceof ApiHttpError && err.status === 422) {
      // FastAPI HTTPException(detail={...}) wraps the payload as
      // { detail: { ok, errors } }. Backwards-compatible: also accept the
      // unwrapped shape if a future handler returns the body directly.
      const raw = err.body as
        | { detail?: { ok: false; errors: ConfigParseError[] } }
        | { ok: false; errors: ConfigParseError[] }
        | null;
      const payload =
        raw && "detail" in raw && raw.detail ? raw.detail : (raw as { ok: false; errors: ConfigParseError[] } | null);
      if (payload && Array.isArray(payload.errors)) {
        throw new ValidationError(payload);
      }
    }
    throw err;
  }
}

export function fetchSchedule(): Promise<Schedule> {
  return fetchJson<Schedule>("/api/schedule");
}

export async function putSchedule(schedule: Schedule): Promise<Schedule> {
  try {
    return await fetchJson<Schedule>("/api/schedule", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(schedule),
    });
  } catch (err) {
    if (err instanceof ApiHttpError && err.status === 422) {
      const raw = err.body as
        | { detail?: { ok: false; errors: string[] } }
        | { ok: false; errors: string[] }
        | null;
      const payload =
        raw && "detail" in raw && raw.detail ? raw.detail : (raw as { ok: false; errors: string[] } | null);
      if (payload && Array.isArray(payload.errors)) {
        throw new ScheduleValidationError(payload);
      }
    }
    throw err;
  }
}

export function postAuthVerify(): Promise<AuthVerifyResponse> {
  // Auth verify uses 200-with-ok-flag convention (umbrella spec B2).
  // Component branches on response.ok rather than catching HTTP error.
  return fetchJson<AuthVerifyResponse>("/api/auth/verify", { method: "POST" });
}

export async function postStartSync(): Promise<StartSyncResponse> {
  try {
    return await fetchJson<StartSyncResponse>("/api/sync/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
  } catch (err) {
    if (err instanceof ApiHttpError && err.status === 409) {
      // FastAPI emits 409 conflict with `detail: { ok, reason, started_at, by }`.
      const detail = (err.body as { detail?: StartSyncConflict } | null)?.detail;
      if (detail && detail.reason === "already_running") {
        throw new ConflictError(detail);
      }
    }
    throw err;
  }
}
