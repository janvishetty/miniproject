import { useState, useEffect, useRef } from "react";
import * as api from "./api";
import { type Theme, sevColor } from "./theme";
import { Card, Btn, SevBadge, StatusBadge, EmptyState, Icons, sourceLabel } from "./ui";
import { Skeleton, ImpactBars, hasImpacts } from "./charts";
import { runReportJob } from "./reportJob";

// ─── URL hash: #report=INC-2026-0081 ──────────────────────────────────────────
const ID_RE = /^INC-\d{4}-\d{4}$/;   // same pattern as the backend's EXTERNAL_ID_PATTERN
export function reportIdFromHash(): string | null {
  const m = /^#report=(.+)$/.exec(window.location.hash);
  return m && ID_RE.test(m[1]) ? m[1] : null;
}
// True once a report was opened from inside the app (card, "View full report", ...): the previous
// history entry is then the list/incident, so Back can pop it instead of pushing another entry.
let openedInApp = false;
export function openReportHash(id: string) { openedInApp = true; window.location.hash = `report=${id}`; }
export function closeReportHash() {
  if (openedInApp && window.history.length > 1) window.history.back();
  else window.location.hash = "";   // pasted/refreshed link: nothing of ours to go back to
}
// Silent (fires no hashchange): used when leaving the Reports tab.
export function clearReportHash() {
  if (window.location.hash.startsWith("#report=")) history.replaceState(null, "", window.location.pathname + window.location.search);
}

const EVENT_PAGE = 10;
const NOT_RECORDED = "Not recorded for this report";
const WS_ROWS: [string, string][] = [["who", "Who"], ["what", "What"], ["when", "When"], ["where", "Where"], ["why_flagged", "Why flagged"]];

const PRINT_CSS = `@media print {
  #root > div > nav, .no-print { display: none !important; }
  #root > div, #root > div > div { height: auto !important; overflow: visible !important; display: block !important; }
  #root > div > div[style*="position: fixed"] { display: none !important; }
  .report-print-root { padding: 0 !important; overflow: visible !important; }
  .report-aside { position: static !important; }
}`;

type RepState =
  | { status: "loading" }
  | { status: "ok"; report: api.Report }
  | { status: "missing" }       // 404 "No report for this incident yet"
  | { status: "gone" }          // any other 404 (incident not in the current run)
  | { status: "error"; message: string };

const strs = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string" && x.trim() !== "") : []);
const money = (n: number | null) => (n == null ? "—" : `₹${Math.round(n).toLocaleString()}`);
const stamp = (s: string | null | undefined) => (s ? s.slice(0, 16).replace("T", " ") : "—");

interface Props {
  t: Theme; id: string;
  showToast: (msg: string, type?: string) => void;
  onBack: () => void;
  onOpenIncident: (id: string) => void;
}

export default function ReportDetailPage({ t, id, showToast, onBack, onOpenIncident }: Props) {
  const [rep, setRep] = useState<RepState>({ status: "loading" });
  const [repTry, setRepTry] = useState(0);
  const [inc, setInc] = useState<api.IncidentDetail | null>(null);
  const [incError, setIncError] = useState("");
  const [incTry, setIncTry] = useState(0);
  const [evPage, setEvPage] = useState(1);
  const [ev, setEv] = useState<api.Page<api.EventRow> | null>(null);
  const [evError, setEvError] = useState("");
  const [evTry, setEvTry] = useState(0);
  const [generating, setGenerating] = useState(false);
  const [genSecs, setGenSecs] = useState(0);
  const genRun = useRef(0);

  // 1. The report itself: shown as soon as it arrives.
  useEffect(() => {
    let alive = true;
    setRep({ status: "loading" });
    api.getReport(id)
      .then(r => { if (alive) setRep({ status: "ok", report: r }); })
      .catch(err => {
        if (!alive) return;
        if (err instanceof api.ApiError && err.status === 404) {
          setRep({ status: err.message === "No report for this incident yet" ? "missing" : "gone" });
        } else {
          setRep({ status: "error", message: err instanceof api.ApiError ? err.message : "Could not load this report" });
        }
      });
    return () => { alive = false; };
  }, [id, repTry]);

  // 2. The incident (evidence + sidebar): separate, so it never delays the report text.
  useEffect(() => {
    let alive = true;
    setInc(null);
    setIncError("");
    api.getIncident(id)
      .then(d => { if (alive) setInc(d); })
      .catch(err => { if (alive) setIncError(err instanceof api.ApiError ? err.message : "Could not load the incident"); });
    return () => { alive = false; };
  }, [id, incTry]);

  // 3. Affected events, 10 per page.
  useEffect(() => {
    let alive = true;
    setEv(null);
    setEvError("");
    api.incidentEvents(id, evPage, EVENT_PAGE)
      .then(p => { if (alive) setEv(p); })
      .catch(err => { if (alive) setEvError(err instanceof api.ApiError ? err.message : "Could not load the events"); });
    return () => { alive = false; };
  }, [id, evPage, evTry]);

  // Generate (404 state): same job flow as the Incidents page via runReportJob.
  useEffect(() => {
    if (!generating) return;
    const t0 = Date.now();
    setGenSecs(0);
    const iv = setInterval(() => setGenSecs(Math.floor((Date.now() - t0) / 1000)), 1000);
    return () => clearInterval(iv);
  }, [generating]);
  useEffect(() => () => { genRun.current++; }, []);

  async function generate() {
    if (generating) return;
    const run = ++genRun.current;
    const alive = () => run === genRun.current;
    setGenerating(true);
    try {
      const out = await runReportJob(id, alive);
      if (out.kind === "cancelled") return;
      if (out.kind === "failed") { showToast(out.message, "error"); return; }
      showToast("Report generated and verified");
      setRepTry(n => n + 1);
    } catch (err) {
      if (!alive()) return;
      if (err instanceof api.ApiError && err.status === 429) showToast("Another report is being generated, try again shortly", "warning");
      else showToast(err instanceof api.ApiError ? err.message : "Could not generate the report", "error");
    } finally {
      if (alive()) setGenerating(false);
    }
  }

  // ─── small render helpers (inline-style convention) ─────────────────────────
  const h = { fontSize: 14, fontWeight: 700, color: t.text, marginBottom: 10 } as const;
  const label = { fontSize: 11, fontWeight: 600, color: t.textMuted, textTransform: "uppercase", letterSpacing: "0.04em" } as const;
  const body = { fontSize: 13, color: t.textSub, lineHeight: 1.6 } as const;
  const mono = { fontFamily: "'DM Mono',monospace" } as const;
  const none = (text = NOT_RECORDED) => <div style={{ fontSize: 12, color: t.textMuted, fontStyle: "italic" }}>{text}</div>;
  const retry = (msg: string, fn: () => void) => (
    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
      <span style={{ fontSize: 13, color: t.red }}>{msg}</span>
      <Btn t={t} variant="ghost" size="sm" onClick={fn}>Retry</Btn>
    </div>
  );
  const bullets = (items: string[], ordered: boolean) => {
    const L = ordered ? "ol" : "ul";
    return <L style={{ margin: 0, paddingLeft: 20, listStyle: ordered ? "decimal" : "disc", ...body }}>{items.map((x, i) => <li key={i} style={{ marginBottom: 4 }}>{x}</li>)}</L>;
  };
  const section = (title: string, children: React.ReactNode) => (
    <Card t={t} style={{ padding: "16px 20px", marginBottom: 16 }}><div style={h}>{title}</div>{children}</Card>
  );
  const glance = (k: string, v: React.ReactNode) => (
    <div style={{ marginBottom: 12 }}><div style={{ ...label, marginBottom: 3 }}>{k}</div><div style={{ fontSize: 13, fontWeight: 600, color: t.text }}>{v}</div></div>
  );

  const backBtn = <div className="no-print" style={{ marginBottom: 16 }}><Btn t={t} variant="ghost" size="sm" onClick={onBack}>← Back to reports</Btn></div>;

  // ─── states other than "ok" ─────────────────────────────────────────────────
  let content: React.ReactNode;
  if (rep.status === "loading") {
    content = (
      <div aria-label="Loading report">
        <Skeleton t={t} w={220} h={14} style={{ marginBottom: 12 }}/>
        <Skeleton t={t} w="60%" h={24} style={{ marginBottom: 24 }}/>
        <Skeleton t={t} h={90} r={12} style={{ marginBottom: 16 }}/>
        <Skeleton t={t} h={160} r={12} style={{ marginBottom: 16 }}/>
        <Skeleton t={t} h={120} r={12}/>
      </div>
    );
  } else if (rep.status === "error") {
    content = retry(rep.message, () => setRepTry(n => n + 1));
  } else if (rep.status === "gone") {
    content = <Card t={t}><EmptyState icon={Icons.incidents} title={`${id} is not in the current pipeline run`} sub="The data may have been reloaded since this link was made." t={t}/></Card>;
  } else if (rep.status === "missing") {
    content = (
      <Card t={t}>
        <EmptyState icon={Icons.reports} title="No report has been generated for this incident yet" sub={`${id} has no stored report.`} t={t}/>
        <div style={{ display: "flex", justifyContent: "center", gap: 10, paddingBottom: 28 }}>
          <Btn t={t} variant="primary" disabled={generating} onClick={generate}>{generating ? `Generating… (${genSecs}s)` : "Generate Report"}</Btn>
          <Btn t={t} variant="ghost" onClick={() => onOpenIncident(id)}>Open incident</Btn>
        </div>
      </Card>
    );
  } else {
    const r = rep.report;
    const ws = r.five_ws && typeof r.five_ws === "object" ? r.five_ws : null;
    const steps = strs(r.investigation_steps), actions = strs(r.containment_actions), mitre = strs(r.mitre), unverified = strs(r.unverified);
    const verified = r.grounded === true;
    const evTotalPages = Math.max(1, Math.ceil((ev?.total ?? 0) / EVENT_PAGE));
    const th = { textAlign: "left", padding: "6px 8px", fontSize: 11, fontWeight: 600, color: t.textMuted, textTransform: "uppercase", letterSpacing: "0.04em", borderBottom: `1px solid ${t.border}`, whiteSpace: "nowrap" } as const;
    const td = { padding: "7px 8px", fontSize: 12, color: t.textSub, borderBottom: `1px solid ${t.border}` } as const;

    content = (
      <>
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, flexWrap: "wrap", marginBottom: 20 }}>
          <div style={{ flex: "1 1 360px", minWidth: 0, borderLeft: `3px solid ${sevColor(r.sev, t).text}`, paddingLeft: 14 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 8 }}>
              <span style={{ ...mono, fontSize: 13, color: t.blue, fontWeight: 500 }}>{r.id}</span>
              <SevBadge level={r.sev} t={t}/>
              <span style={{ background: t.badge, border: `1px solid ${t.border}`, borderRadius: 4, padding: "1px 7px", fontSize: 11, fontWeight: 600, color: t.textSub }}>{sourceLabel(r.source)}</span>
              <span style={{ background: verified ? t.greenDim : t.amberDim, color: verified ? t.green : t.amber, border: `1px solid ${verified ? t.greenBorder : t.amberBorder}`, borderRadius: 99, padding: "3px 10px", fontSize: 11, fontWeight: 600 }}>{verified ? "Verified" : "Unverified"}</span>
              <span style={{ fontSize: 12, color: t.textMuted }}>Created {stamp(r.created_at)}</span>
            </div>
            <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: t.text, lineHeight: 1.3 }}>{r.title}</h1>
          </div>
          <div className="no-print"><Btn t={t} variant="secondary" icon={Icons.download} onClick={() => window.print()}>Print / Save as PDF</Btn></div>
        </div>

        {/* Verification banners */}
        {!verified && (
          <div role="alert" style={{ background: t.amberDim, border: `1px solid ${t.amberBorder}`, borderRadius: t.radiusSm, padding: "12px 16px", marginBottom: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: t.amber, marginBottom: unverified.length ? 6 : 0 }}>This report could not be fully verified against the incident data.</div>
            {unverified.length > 0 && <ul style={{ margin: 0, paddingLeft: 20, listStyle: "disc", fontSize: 12, color: t.textSub, lineHeight: 1.5 }}>{unverified.map((x, i) => <li key={i}>{x}</li>)}</ul>}
          </div>
        )}
        {r.source === "template" && (
          <div style={{ background: t.blueDim, border: `1px solid ${t.blueBorder}`, borderRadius: t.radiusSm, padding: "10px 16px", marginBottom: 16, fontSize: 13, color: t.textSub }}>
            This report was built directly from the incident data (verified), not written by the AI model.
          </div>
        )}

        <div style={{ display: "flex", flexWrap: "wrap", gap: 24, alignItems: "flex-start" }}>
          {/* Main column */}
          <main style={{ flex: "1 1 520px", maxWidth: 760, minWidth: 0 }}>
            <Card t={t} style={{ padding: "16px 20px", marginBottom: 16, background: t.blueDim, border: `1px solid ${t.blueBorder}` }}>
              <div style={h}>Executive summary</div>
              {r.summary ? <p style={{ margin: 0, ...body, color: t.text }}>{r.summary}</p> : none()}
            </Card>

            {section("Key findings", !ws ? none() : (
              <div style={{ display: "grid", gridTemplateColumns: "100px minmax(0, 1fr)", gap: "10px 16px" }}>
                {WS_ROWS.map(([k, name]) => {
                  const v = ws[k];
                  const lines = Array.isArray(v) ? strs(v) : typeof v === "string" && v.trim() ? [v] : [];
                  return (
                    <div key={k} style={{ display: "contents" }}>
                      <div style={label}>{name}</div>
                      <div>{lines.length === 0 ? none() : lines.length === 1 ? <div style={body}>{lines[0]}</div> : bullets(lines, false)}</div>
                    </div>
                  );
                })}
              </div>
            ))}

            {section("Investigation steps", steps.length ? bullets(steps, true) : none())}
            {section("Containment actions", actions.length ? bullets(actions, false) : none())}

            {/* Supporting evidence: live incident data, loaded separately */}
            <div style={{ ...h, fontSize: 16, margin: "24px 0 4px" }}>Supporting evidence</div>
            <div style={{ fontSize: 12, color: t.textMuted, marginBottom: 12 }}>From the incident record, not from the report text.</div>

            {incError && retry(incError, () => setIncTry(n => n + 1))}
            {!incError && !inc && <Skeleton t={t} h={110} r={12} style={{ marginBottom: 16 }}/>}
            {inc && section("Why it was flagged", inc.reasons.length === 0 ? none("None recorded for this incident")
              : hasImpacts(inc.reasons) ? <ImpactBars reasons={inc.reasons} t={t}/>
              : bullets(inc.reasons.map(x => x.text ?? x.feature ?? "—"), false))}
            {inc && section("Investigation timeline", inc.timeline.length === 0 ? none("None recorded for this incident") : (
              <div style={{ display: "flex", flexDirection: "column" }}>
                {inc.timeline.map((e, i) => (
                  <div key={i} style={{ display: "flex", gap: 14 }}>
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", flexShrink: 0 }}>
                      <div style={{ width: 10, height: 10, borderRadius: "50%", background: e.color ?? t.textMuted, marginTop: 3 }}/>
                      {i < inc.timeline.length - 1 && <div style={{ width: 2, flex: 1, background: t.border, margin: "2px 0" }}/>}
                    </div>
                    <div style={{ paddingBottom: 16 }}>
                      <div style={{ ...mono, fontSize: 11, color: t.textMuted, marginBottom: 2 }}>{e.time} · <span style={{ color: e.color ?? t.textMuted, fontWeight: 600 }}>{e.actor}</span></div>
                      <div style={{ fontSize: 13, color: t.textSub, lineHeight: 1.4 }}>{e.msg}</div>
                    </div>
                  </div>
                ))}
              </div>
            ))}

            {section(`Affected events${ev ? ` (${ev.total})` : ""}`, evError ? retry(evError, () => setEvTry(n => n + 1))
              : !ev ? <Skeleton t={t} h={180} r={8}/>
              : ev.items.length === 0 ? none("No events recorded for this incident")
              : (
                <>
                  <div style={{ overflowX: "auto" }}>
                    <table style={{ width: "100%", borderCollapse: "collapse" }}>
                      <thead><tr>{["Time", "Kind", "User", "IP", "Amount", "Status"].map(c => <th key={c} style={th}>{c}</th>)}</tr></thead>
                      <tbody>
                        {ev.items.map(e => (
                          <tr key={e.event_id}>
                            <td style={{ ...td, ...mono, whiteSpace: "nowrap" }}>{stamp(e.ts)}</td>
                            <td style={td}>{e.event_kind ?? "—"}</td>
                            <td style={{ ...td, ...mono }}>{e.user_id ?? "—"}</td>
                            <td style={{ ...td, ...mono }}>{e.ip_address ?? "—"}</td>
                            <td style={{ ...td, ...mono, textAlign: "right" }}>{money(e.amount)}</td>
                            <td style={td}>{e.status ?? "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {ev.total > EVENT_PAGE && (
                    <div className="no-print" style={{ display: "flex", alignItems: "center", gap: 14, marginTop: 12 }}>
                      <Btn t={t} variant="ghost" size="sm" disabled={evPage <= 1} onClick={() => setEvPage(p => p - 1)}>Previous</Btn>
                      <span style={{ fontSize: 12, color: t.textMuted }}>Page {evPage} of {evTotalPages}</span>
                      <Btn t={t} variant="ghost" size="sm" disabled={evPage >= evTotalPages} onClick={() => setEvPage(p => p + 1)}>Next</Btn>
                    </div>
                  )}
                </>
              ))}
          </main>

          {/* At a glance */}
          <aside className="report-aside" style={{ flex: "0 1 300px", minWidth: 260, position: "sticky", top: 0, alignSelf: "flex-start" }}>
            <Card t={t} style={{ padding: "16px 20px" }}>
              <div style={h}>At a glance</div>
              {glance("Severity", <SevBadge level={r.sev} t={t}/>)}
              {inc ? (
                <>
                  {glance("Status", <StatusBadge status={inc.status} t={t}/>)}
                  {glance("Attack type", inc.vector ?? "—")}
                  {glance("Risk score", inc.risk_score == null ? "—" : Math.round(inc.risk_score))}
                  {glance("Confidence", inc.confidence == null ? "—" : `${Math.round(inc.confidence)}%`)}
                  {glance("Business impact", inc.impact == null ? "—" : `${Math.round(inc.impact)}%`)}
                  {glance("Amount involved", money(inc.amount_total))}
                  {glance(`Users (${inc.users.length})`, inc.users.length ? <span style={{ ...mono, fontSize: 12, fontWeight: 500, wordBreak: "break-word" }}>{inc.users.slice(0, 5).join(", ")}{inc.users.length > 5 ? ` +${inc.users.length - 5} more` : ""}</span> : "—")}
                  {glance(`IPs (${inc.ips.length})`, inc.ips.length ? <span style={{ ...mono, fontSize: 12, fontWeight: 500, wordBreak: "break-word" }}>{inc.ips.slice(0, 5).join(", ")}{inc.ips.length > 5 ? ` +${inc.ips.length - 5} more` : ""}</span> : "—")}
                </>
              ) : incError ? none("Incident details unavailable") : <Skeleton t={t} h={150} r={8} style={{ marginBottom: 12 }}/>}

              <div style={{ ...label, marginBottom: 6 }}>MITRE ATT&amp;CK</div>
              {mitre.length ? (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 12 }}>
                  {mitre.map(m => <span key={m} style={{ background: t.badge, border: `1px solid ${t.border}`, borderRadius: 4, padding: "2px 8px", fontSize: 11, fontWeight: 600, color: t.textSub }}>{m}</span>)}
                </div>
              ) : <div style={{ marginBottom: 12 }}>{none()}</div>}

              {glance("Generated by", sourceLabel(r.source))}
              {glance("Grounding check", <span style={{ color: verified ? t.green : t.amber }}>{verified ? "Passed: facts match the incident data" : "Not fully verified"}</span>)}

              <div className="no-print"><Btn t={t} variant="secondary" fullWidth onClick={() => onOpenIncident(r.id)}>Open incident</Btn></div>
            </Card>
          </aside>
        </div>
      </>
    );
  }

  return (
    <div className="report-print-root" style={{ padding: "24px 28px", overflowY: "auto", flex: 1, minHeight: 0, animation: "fadeUp 0.25s ease-out" }}>
      <style>{PRINT_CSS}</style>
      {backBtn}
      {content}
    </div>
  );
}
