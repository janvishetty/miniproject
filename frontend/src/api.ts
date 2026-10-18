// Typed client for the FSIA backend (see docs/API_CONTRACT.md).
// The token lives in this module variable only: never in localStorage / sessionStorage.
// Nothing here logs tokens, request bodies or response bodies.

const BASE_URL: string =
  ((import.meta.env.VITE_API_URL as string | undefined) || "http://127.0.0.1:8000").replace(/\/+$/, "");

const DEFAULT_TIMEOUT_MS = 15_000;
const COPILOT_TIMEOUT_MS = 150_000;

// ─── Errors ───────────────────────────────────────────────────────────────────
export class ApiError extends Error {
  status: number;
  code: string;
  details?: unknown;
  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

// ─── Token (memory only) + 401 callback ───────────────────────────────────────
let token: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function setToken(value: string | null) { token = value; }
export function hasToken() { return token !== null; }
export function setUnauthorizedHandler(fn: (() => void) | null) { onUnauthorized = fn; }

// ─── Types (shapes from docs/API_CONTRACT.md) ─────────────────────────────────
export type Severity = "critical" | "high" | "medium" | "low";
export type Status = "OPEN" | "INVESTIGATING" | "CONTAINED" | "RESOLVED";

export type Profile = {
  id: string;
  name: string | null;
  username: string | null;
  email: string | null;
  position: string | null;
  role: string;
};

export type LoginResponse = { access_token: string; token_type: string; expires_in: number | null; profile: Profile };

export type RecentItem = { id: string; sev: Severity; title: string; time: string | null; status: Status; started_at: string | null };

export type RiskNode = {
  id: string; score: number; tag: string; alerts: number; risk: Severity;
  endpoint?: string; incidents?: string[]; by_type?: Record<string, number>;
};

export type LiveEvent = { ts?: string; node?: string; msg?: string; type?: string; [k: string]: unknown };

export type Dashboard = {
  run: { id: string; fingerprint: string | null; loaded_at: string | null };
  active_incidents: number;
  critical_open: number;
  platform_risk_score: number;
  by_severity: Record<Severity, number>;
  by_status: Record<Status, number>;
  by_type: Record<string, number>;
  recent: RecentItem[];
  events_analysed: number | null;
  events_analysed_sub: string | null;
  anomalous_events: number | null;
  event_funnel: Record<string, number> | null;
  amount_at_risk: number | null;
  risk_map_title: string | null;
  risk_map: RiskNode[] | null;
  live_events: LiveEvent[] | null;
  model: Record<string, unknown> | null;
  avg_response_time: number | null;
};

export type IncidentItem = {
  id: string; sev: Severity; status: Status; title: string; asset: string | null; ip: string | null;
  analyst: string | null; vector: string | null; created: string | null; confidence: number | null;
  impact: number | null; started_at: string | null; risk_score: number | null;
};

export type Page<T> = { items: T[]; total: number; page: number; page_size: number };

export type TimelineEntry = { time?: string; actor?: string; msg?: string; color?: string };
export type Reason = { feature?: string; impact?: number; text?: string };

export type ReportSummary = { summary: string | null; source: string | null; grounded: boolean | null; created_at: string | null };

export type IncidentDetail = IncidentItem & {
  ended_at: string | null; event_count: number | null; amount_total: number | null;
  ip_threat_level: string | null; users: string[]; ips: string[]; ip_details: unknown[];
  reasons: Reason[]; sequence: unknown; timeline: TimelineEntry[]; detected_by: string | null;
  ml_severity: string | null; rule_severity: string | null; rule_hits: unknown[]; rule_mitre: string[];
  threat_actor: string | null; threat_intel: unknown; ai_summary: string | null;
  event_ids: string[]; report: ReportSummary | null;
};

export type EventRow = {
  event_id: string; event_kind: string | null; source_type: string | null; ts: string | null;
  user_id: string | null; ip_address: string | null; device_id: string | null; location: string | null;
  status: string | null; mfa_status: string | null; endpoint: string | null; http_method: string | null;
  status_code: number | null; amount: number | null; merchant: string | null;
};

export type Report = {
  id: string; title: string; sev: Severity; summary: string | null; five_ws: Record<string, string> | null;
  mitre: string[]; containment_actions: string[]; investigation_steps: string[];
  source: string | null; grounded: boolean | null; unverified: unknown[]; created_at: string | null;
};

export type CopilotAnswer = {
  answer: string | null; incidents: string[]; source: string | null; grounding: unknown; seconds: number | null;
};

export type IncidentQuery = {
  status?: Status; severity?: Severity; vector?: string; search?: string;
  sort?: "risk_score" | "started_at" | "confidence"; order?: "asc" | "desc";
  page?: number; page_size?: number;
};

// ─── Core request ─────────────────────────────────────────────────────────────
type Options = { body?: unknown; timeoutMs?: number; auth?: boolean };

async function request<T>(method: string, path: string, opts: Options = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (token && opts.auth !== false) headers["Authorization"] = `Bearer ${token}`;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), opts.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  let res: Response;
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      method, headers, signal: controller.signal,
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiError(0, "timeout", "The server took too long to respond");
    }
    throw new ApiError(0, "network", "Cannot reach the server");
  } finally {
    clearTimeout(timer);
  }

  let data: unknown = null;
  try { data = await res.json(); } catch { data = null; }

  if (!res.ok) {
    const e = (data as { error?: { code?: string; message?: string; details?: unknown } } | null)?.error;
    if (res.status === 401 && path !== "/auth/login") {
      token = null;
      onUnauthorized?.();
    }
    throw new ApiError(res.status, e?.code ?? "error", e?.message ?? `Request failed (${res.status})`, e?.details);
  }
  return data as T;
}

function qs(params: Record<string, string | number | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") sp.set(k, String(v));
  const s = sp.toString();
  return s ? `?${s}` : "";
}

// ─── Typed helpers ────────────────────────────────────────────────────────────
export async function login(email: string, password: string): Promise<Profile> {
  const res = await request<LoginResponse>("POST", "/auth/login", { body: { email, password }, auth: false });
  token = res.access_token;
  return res.profile;
}

export async function logout(): Promise<void> {
  try { await request<unknown>("POST", "/auth/logout"); } catch { /* best effort */ }
  token = null;
}

export const me = () => request<Profile>("GET", "/auth/me");
export const health = () => request<{ status: string }>("GET", "/health", { auth: false });
export const dashboard = () => request<Dashboard>("GET", "/dashboard");

export const listIncidents = (q: IncidentQuery = {}) =>
  request<Page<IncidentItem>>("GET", `/incidents${qs({ ...q })}`);
export const getIncident = (id: string) =>
  request<IncidentDetail>("GET", `/incidents/${encodeURIComponent(id)}`);
export const incidentEvents = (id: string, page = 1, pageSize = 50) =>
  request<Page<EventRow>>("GET", `/incidents/${encodeURIComponent(id)}/events${qs({ page, page_size: pageSize })}`);
export const patchIncident = (id: string, body: { status?: Status; analyst_id?: string | null }) =>
  request<IncidentItem>("PATCH", `/incidents/${encodeURIComponent(id)}`, { body });

export const listReports = (page = 1, pageSize = 20) =>
  request<Page<Report>>("GET", `/reports${qs({ page, page_size: pageSize })}`);
export const getReport = (id: string) =>
  request<Report>("GET", `/reports/${encodeURIComponent(id)}`);

export const copilot = (question: string) =>
  request<CopilotAnswer>("POST", "/copilot", { body: { question }, timeoutMs: COPILOT_TIMEOUT_MS });
export const welcome = () => request<CopilotAnswer>("GET", "/copilot/welcome");
