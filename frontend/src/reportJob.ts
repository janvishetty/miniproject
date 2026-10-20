// Start a report job and poll it to the end. Shared by IncidentsPage and ReportDetailPage.
// ApiErrors (start/poll failures, 429) are thrown to the caller; job failures come back as `failed`.
import * as api from "./api";

const REPORT_POLL_MS = 2_000;
const REPORT_POLL_MAX_MS = 10 * 60_000;
const REPORT_POLL_MAX_FAILS = 3;
const REPORT_ERRORS: Record<string, string> = {
  ai_unavailable: "AI service unavailable. Start Ollama.",
  unverified: "Report could not be verified",
  timeout: "Report generation timed out",
  stale_run: "Data changed, reload the page",
};

export type ReportRun = { kind: "done" } | { kind: "cancelled" } | { kind: "failed"; message: string };

export async function runReportJob(id: string, alive: () => boolean): Promise<ReportRun> {
  const started = Date.now();
  const job = await api.startReport(id);
  let cur = job;
  let fails = 0;
  while (cur.status === "running") {
    if (Date.now() - started > REPORT_POLL_MAX_MS) return { kind: "failed", message: REPORT_ERRORS.timeout };
    await new Promise(r => setTimeout(r, REPORT_POLL_MS));
    if (!alive()) return { kind: "cancelled" };
    try {
      cur = await api.getReportJob(job.job_id);
      fails = 0;
    } catch (e) {
      // Tolerate short network/timeout blips (status 0); anything else, or too many in a row, gives up.
      if (!alive()) return { kind: "cancelled" };
      if (e instanceof api.ApiError && e.status === 0 && ++fails < REPORT_POLL_MAX_FAILS) continue;
      throw e;
    }
    if (!alive()) return { kind: "cancelled" };
  }
  if (cur.status === "failed") {
    const e = cur.error;
    return { kind: "failed", message: (e && REPORT_ERRORS[e.code]) || e?.message || "Report generation failed" };
  }
  return { kind: "done" };
}
