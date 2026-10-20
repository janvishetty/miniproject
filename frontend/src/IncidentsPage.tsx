import { useState, useEffect, useRef } from "react";
import type { Theme } from "./theme";
import { Card, SevBadge, StatusBadge, Btn, ProgressBar, EmptyState, Icons, sourceLabel } from "./ui";
import { sevColor } from "./theme";
import { Skeleton, ImpactBars, hasImpacts } from "./charts";
import * as api from "./api";
import { runReportJob } from "./reportJob";

const PAGE_SIZE = 20;

type ConfirmAction = { label: string; message: string; variant: "danger" | "success" | "primary" } | null;

interface Props { t: Theme; showToast: (msg: string, type?: string) => void; onChanged?: () => void; role?: string; initialId?: string | null; onViewReport?: (id: string) => void; }

export default function IncidentsPage({ t, showToast, onChanged, role = "", initialId = null, onViewReport }: Props) {
  const [items, setItems] = useState<api.IncidentItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(initialId);
  const [detail, setDetail] = useState<api.IncidentDetail | null>(null);
  const [detailError, setDetailError] = useState("");
  const [report, setReport] = useState<api.Report | null>(null);
  const [filterSev, setFilterSev] = useState("All");
  const [filterStatus, setFilterStatus] = useState("All");
  const [search, setSearch] = useState("");
  const [searchQ, setSearchQ] = useState("");
  const [confirm, setConfirm] = useState<ConfirmAction>(null);
  const [busy, setBusy] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [genId, setGenId] = useState<string | null>(null);
  const [genSecs, setGenSecs] = useState(0);
  const genRun = useRef(0);
  const listSeq = useRef(0);
  const detailSeq = useRef(0);

  // Search box -> query, 350 ms after typing stops.
  useEffect(() => {
    const timer = setTimeout(() => { setSearchQ(search.trim()); setPage(1); }, 350);
    return () => clearTimeout(timer);
  }, [search]);

  // Seconds counter while a report is being generated; stop any poll when leaving the page.
  useEffect(() => {
    if (!genId) return;
    const t0 = Date.now();
    setGenSecs(0);
    const iv = setInterval(() => setGenSecs(Math.floor((Date.now() - t0) / 1000)), 1000);
    return () => clearInterval(iv);
  }, [genId]);
  useEffect(() => () => { genRun.current++; }, []);

  // List
  useEffect(() => {
    const seq = ++listSeq.current;
    setListLoading(true);
    setListError("");
    api.listIncidents({
      page, page_size: PAGE_SIZE, search: searchQ || undefined,
      severity: filterSev === "All" ? undefined : (filterSev.toLowerCase() as api.Severity),
      status: filterStatus === "All" ? undefined : (filterStatus.toUpperCase() as api.Status),
    }).then(res => {
      if (seq !== listSeq.current) return;
      setItems(res.items);
      setTotal(res.total);
      setSelectedId(cur => cur ?? res.items[0]?.id ?? null);
      setListLoading(false);
    }).catch(err => {
      if (seq !== listSeq.current) return;
      setItems([]);
      setTotal(0);
      setListError(err instanceof api.ApiError ? err.message : "Could not load incidents");
      setListLoading(false);
    });
  }, [page, filterSev, filterStatus, searchQ, reloadKey]);

  // Detail
  useEffect(() => {
    if (!selectedId) { setDetail(null); return; }
    const seq = ++detailSeq.current;
    setDetailError("");
    api.getIncident(selectedId).then(d => {
      if (seq === detailSeq.current) setDetail(d);
    }).catch(err => {
      if (seq === detailSeq.current) setDetailError(err instanceof api.ApiError ? err.message : "Could not load this incident");
    });
  }, [selectedId, reloadKey]);

  function select(id: string) {
    if (id === selectedId) return;
    genRun.current++;
    setGenId(null);
    setDetail(null);
    setReport(null);
    setSelectedId(id);
  }

  function changeFilter(set: (v: string) => void, value: string) {
    set(value);
    setPage(1);
  }

  async function changeStatus(status: api.Status) {
    if (!detail || busy) return;
    setBusy(true);
    try {
      await api.patchIncident(detail.id, { status });
      showToast(`${detail.id} is now ${status.charAt(0) + status.slice(1).toLowerCase()}`);
      setReloadKey(k => k + 1);
      onChanged?.();
    } catch (err) {
      showToast(err instanceof api.ApiError ? err.message : "Update failed", "error");
    }
    setBusy(false);
  }

  function doAction(label: string) {
    setConfirm(null);
    if (label === "Contain") changeStatus("CONTAINED");
    if (label === "Resolve") changeStatus("RESOLVED");
  }

  async function generateReport() {
    if (!detail || genId) return;
    const id = detail.id;
    if (detail.report) {
      try {
        setReport(await api.getReport(id));
        showToast("This incident already has a verified report");
      } catch (err) {
        showToast(err instanceof api.ApiError ? err.message : "Could not load the report", "error");
      }
      return;
    }
    const run = ++genRun.current;
    const alive = () => run === genRun.current;
    setGenId(id);
    try {
      const out = await runReportJob(id, alive);
      if (out.kind === "cancelled") return;
      if (out.kind === "failed") { showToast(out.message, "error"); return; }
      setReport(await api.getReport(id));
      if (!alive()) return;
      setReloadKey(k => k + 1);
      showToast("Report generated and verified");
    } catch (err) {
      if (!alive()) return;
      if (err instanceof api.ApiError && err.status === 429) showToast("Another report is being generated, try again shortly", "warning");
      else showToast(err instanceof api.ApiError ? err.message : "Could not generate the report", "error");
    } finally {
      if (alive()) setGenId(null);
    }
  }

  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const note = { fontSize: 12, color: t.textMuted, padding: "14px 20px" };

  return (
    <div style={{ display: "flex", flex: 1, minHeight: 0, animation: "fadeUp 0.25s ease-out" }}>

      {/* Sidebar list */}
      <div style={{ width: 380, borderRight: `1px solid ${t.border}`, display: "flex", flexDirection: "column", background: t.card, flexShrink: 0 }}>
        {/* Header */}
        <div style={{ padding: "20px 20px 14px", borderBottom: `1px solid ${t.border}` }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: t.text }}>Incidents</h2>
            <span style={{ background: t.redDim, color: t.red, border: `1px solid ${t.redBorder}`, borderRadius: 99, padding: "2px 10px", fontSize: 12, fontWeight: 600 }}>{total} found</span>
          </div>

          {/* Search */}
          <div style={{ display: "flex", alignItems: "center", background: t.input, boxShadow: t.inset, border: `1px solid ${t.border}`, borderRadius: t.radiusSm, padding: "7px 12px", gap: 8, marginBottom: 10 }}>
            <span style={{ color: t.textMuted }}>{Icons.search}</span>
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search by title or ID..." style={{ background: "none", border: "none", outline: "none", fontSize: 13, color: t.text, flex: 1 }}/>
          </div>

          {/* Filters */}
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" as const }}>
            {["All","Critical","High","Medium","Low"].map(s => (
              <button key={s} onClick={() => changeFilter(setFilterSev, s)} style={{ fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 99, border: `1px solid ${filterSev === s ? t.blue : t.border}`, background: filterSev === s ? t.blueDim : "transparent", color: filterSev === s ? t.blue : t.textSub, cursor: "pointer", transition: "all 0.15s" }}
                onMouseEnter={e => { if (filterSev !== s) e.currentTarget.style.background = t.badge; }}
                onMouseLeave={e => { if (filterSev !== s) e.currentTarget.style.background = "transparent"; }}>{s}</button>
            ))}
            <div style={{ width: 1, background: t.border, margin: "0 2px" }}/>
            {["All","Open","Investigating","Contained","Resolved"].map(s => (
              <button key={s} onClick={() => changeFilter(setFilterStatus, s)} style={{ fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 99, border: `1px solid ${filterStatus === s ? t.blue : t.border}`, background: filterStatus === s ? t.blueDim : "transparent", color: filterStatus === s ? t.blue : t.textSub, cursor: "pointer", transition: "all 0.15s" }}
                onMouseEnter={e => { if (filterStatus !== s) e.currentTarget.style.background = t.badge; }}
                onMouseLeave={e => { if (filterStatus !== s) e.currentTarget.style.background = "transparent"; }}>{s === "All" ? "Any status" : s}</button>
            ))}
          </div>
        </div>

        {/* List */}
        <div style={{ flex: 1, overflowY: "auto" }}>
          {listLoading && [0, 1, 2, 3, 4, 5].map(i => (
            <div key={i} style={{ padding: "14px 20px", borderBottom: `1px solid ${t.border}`, borderLeft: "3px solid transparent" }}>
              <Skeleton t={t} w="40%" h={12} style={{ marginBottom: 10 }}/>
              <Skeleton t={t} h={14} style={{ marginBottom: 10 }}/>
              <Skeleton t={t} w="60%" h={12}/>
            </div>
          ))}
          {!listLoading && listError && <div style={{ ...note, color: t.red }}>{listError}</div>}
          {!listLoading && !listError && items.length === 0 && <EmptyState icon={Icons.search} title="No incidents found" sub="Try clearing the search or filters." t={t}/>}
          {!listLoading && items.map(inc => (
            <div key={inc.id} onClick={() => select(inc.id)} style={{ padding: "14px 20px", borderBottom: `1px solid ${t.border}`, cursor: "pointer", background: selectedId === inc.id ? t.blueDim : "transparent", borderLeft: `3px solid ${sevColor(inc.sev, t).text}`, transition: "background 0.15s" }}
              onMouseEnter={e => { if (selectedId !== inc.id) e.currentTarget.style.background = t.bg; }}
              onMouseLeave={e => { if (selectedId !== inc.id) e.currentTarget.style.background = "transparent"; }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 6 }}>
                <span style={{ fontFamily: "'DM Mono',monospace", fontSize: 11, color: t.blue, fontWeight: 500 }}>{inc.id}</span>
                <SevBadge level={inc.sev} t={t}/>
              </div>
              <div style={{ fontSize: 13, fontWeight: 600, color: t.text, marginBottom: 6, lineHeight: 1.35 }}>{inc.title}</div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <StatusBadge status={inc.status} t={t}/>
                <span style={{ fontSize: 11, color: t.textMuted, fontFamily: "'DM Mono',monospace" }}>{inc.created}</span>
              </div>
            </div>
          ))}
        </div>

        {/* Paging */}
        <div style={{ padding: "10px 20px", borderTop: `1px solid ${t.border}`, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <Btn t={t} variant="ghost" size="sm" disabled={page <= 1 || listLoading} onClick={() => setPage(p => p - 1)}>Previous</Btn>
          <span style={{ fontSize: 12, color: t.textMuted }}>Page {page} of {lastPage}</span>
          <Btn t={t} variant="ghost" size="sm" disabled={page >= lastPage || listLoading} onClick={() => setPage(p => p + 1)}>Next</Btn>
        </div>
      </div>

      {/* Detail panel */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflowY: "auto" }}>
        {!selectedId && !listLoading && <EmptyState icon={Icons.incidents} title="Select an incident" sub="Pick one from the list to see its analysis." t={t}/>}
        {selectedId && !detail && !detailError && (
          <div aria-label="Loading incident" style={{ padding: "24px 28px" }}>
            <Skeleton t={t} w={220} h={14} style={{ marginBottom: 12 }}/>
            <Skeleton t={t} w="60%" h={24} style={{ marginBottom: 24 }}/>
            <Skeleton t={t} h={44} r={8} style={{ marginBottom: 24 }}/>
            <Skeleton t={t} h={90} r={12} style={{ marginBottom: 20 }}/>
            <Skeleton t={t} h={150} r={12}/>
          </div>
        )}
        {selectedId && detailError && <div style={{ ...note, padding: "24px 28px", color: t.red }}>{detailError}</div>}
        {detail && (
          <div style={{ padding: "24px 28px" }} className="animate-fadeIn">
            {/* Title */}
            <div style={{ marginBottom: 20, borderLeft: `3px solid ${sevColor(detail.sev, t).text}`, paddingLeft: 14 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
                <span style={{ fontFamily: "'DM Mono',monospace", fontSize: 13, color: t.blue, fontWeight: 500 }}>{detail.id}</span>
                <SevBadge level={detail.sev} t={t}/>
                <StatusBadge status={detail.status} t={t}/>
              </div>
              <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: t.text, lineHeight: 1.3 }}>{detail.title}</h1>
            </div>

            {/* Action buttons */}
            <div style={{ display: "flex", gap: 10, marginBottom: 24, flexWrap: "wrap" as const }}>
              <Btn t={t} variant="primary" icon={Icons.eye} disabled={busy || ["INVESTIGATING", "CONTAINED", "RESOLVED"].includes(detail.status)} onClick={() => changeStatus("INVESTIGATING")}>Investigate</Btn>
              <Btn t={t} variant="success" disabled={busy || ["CONTAINED", "RESOLVED"].includes(detail.status)} onClick={() => setConfirm({ label: "Contain", message: `Isolate the affected asset (${detail.asset ?? "unknown"}) and stop the threat from spreading?`, variant: "success" })}>Contain Threat</Btn>
              {(role === "manager" || role === "admin") && detail.status !== "RESOLVED" && (
                <Btn t={t} variant="success" disabled={busy} onClick={() => setConfirm({ label: "Resolve", message: `Mark ${detail.id} as resolved?`, variant: "success" })}>Resolve</Btn>
              )}
              <Btn t={t} variant="danger"  onClick={() => showToast(`Escalation noted for ${detail.id}`, "warning")}>Escalate</Btn>
              <Btn t={t} variant="ghost"   disabled={!!genId} onClick={generateReport}>{genId ? `Generating… (${genSecs}s)` : "Generate Report"}</Btn>
              {onViewReport && (detail.report || report) && <Btn t={t} variant="secondary" icon={Icons.file} onClick={() => onViewReport(detail.id)}>View full report</Btn>}
            </div>

            {/* Meta grid */}
            <Card t={t} style={{ padding: "16px 20px", marginBottom: 16 }}>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 }}>
                {[["Source IP", detail.ip],["Affected Asset", detail.asset],["Attack Vector", detail.vector],["Assigned Analyst", detail.analyst],["Detected", detail.created],["Threat Actor", detail.threat_actor]].map(([label, val]) => (
                  <div key={label}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: t.textMuted, marginBottom: 3, textTransform: "uppercase" as const, letterSpacing: "0.04em" }}>{label}</div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: t.text, fontFamily: label === "Source IP" || label === "Detected" ? "'DM Mono',monospace" : undefined }}>{val ?? "—"}</div>
                  </div>
                ))}
              </div>
            </Card>

            {/* AI confidence */}
            <Card t={t} style={{ padding: "16px 20px", marginBottom: 16, border: `1px solid ${t.blueBorder}` }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
                <div style={{ width: 28, height: 28, borderRadius: 8, background: t.blueDim, display: "flex", alignItems: "center", justifyContent: "center", color: t.blue }}>{Icons.bot}</div>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 700, color: t.text }}>AI Analysis</div>
                  <div style={{ fontSize: 11, color: t.textSub }}>Isolation Forest + SHAP · llama3.2:3b (local)</div>
                </div>
              </div>
              <p style={{ margin: "0 0 14px", fontSize: 13, color: t.textSub, lineHeight: 1.6 }}>
                {detail.report?.summary || detail.ai_summary || "No AI analysis is available for this incident."}
              </p>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                <div>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
                    <span style={{ fontSize: 12, color: t.textSub, fontWeight: 500 }}>AI Confidence</span>
                    <span style={{ fontSize: 12, fontWeight: 700, color: t.blue, fontFamily: "'DM Mono',monospace" }}>{Math.round(detail.confidence ?? 0)}%</span>
                  </div>
                  <ProgressBar value={detail.confidence ?? 0} color={t.blue} t={t}/>
                </div>
                <div>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
                    <span style={{ fontSize: 12, color: t.textSub, fontWeight: 500 }}>Business Impact</span>
                    <span style={{ fontSize: 12, fontWeight: 700, color: t.amber, fontFamily: "'DM Mono',monospace" }}>{Math.round(detail.impact ?? 0)}%</span>
                  </div>
                  <ProgressBar value={detail.impact ?? 0} color={t.amber} t={t}/>
                </div>
              </div>
            </Card>

            {/* Incident report (after Generate Report, when one exists) */}
            {report && (
              <Card t={t} style={{ padding: "16px 20px", marginBottom: 16 }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: t.text, marginBottom: 10 }}>Incident Report <span style={{ fontSize: 11, color: t.textMuted, fontWeight: 500 }}>· {sourceLabel(report.source)}</span></div>
                <p style={{ margin: "0 0 12px", fontSize: 13, color: t.textSub, lineHeight: 1.6 }}>{report.summary}</p>
                {([["Containment actions", report.containment_actions], ["Investigation steps", report.investigation_steps]] as const).map(([label, list]) => list.length > 0 && (
                  <div key={label} style={{ marginBottom: 10 }}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: t.textMuted, marginBottom: 4, textTransform: "uppercase" as const, letterSpacing: "0.04em" }}>{label}</div>
                    {list.map((x, i) => <div key={i} style={{ fontSize: 13, color: t.textSub, lineHeight: 1.5 }}>• {x}</div>)}
                  </div>
                ))}
              </Card>
            )}

            {/* Why it was flagged */}
            {detail.reasons.length > 0 && (
              <Card t={t} style={{ padding: "16px 20px", marginBottom: 16 }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: t.text, marginBottom: 10 }}>Why it was flagged</div>
                {hasImpacts(detail.reasons)
                  ? <ImpactBars reasons={detail.reasons} t={t}/>
                  : detail.reasons.map((r, i) => <div key={i} style={{ fontSize: 13, color: t.textSub, lineHeight: 1.6 }}>• {r.text}</div>)}
              </Card>
            )}

            {/* Timeline */}
            <Card t={t} style={{ padding: "16px 20px" }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: t.text, marginBottom: 14 }}>Investigation Timeline</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
                {detail.timeline.map((ev, i) => (
                  <div key={i} style={{ display: "flex", gap: 14, position: "relative" }}>
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", flexShrink: 0 }}>
                      <div style={{ width: 10, height: 10, borderRadius: "50%", background: ev.color ?? t.textMuted, marginTop: 3, zIndex: 1 }}/>
                      {i < detail.timeline.length - 1 && <div style={{ width: 2, flex: 1, background: t.border, margin: "2px 0" }}/>}
                    </div>
                    <div style={{ paddingBottom: 16 }}>
                      <div style={{ fontSize: 11, color: t.textMuted, fontFamily: "'DM Mono',monospace", marginBottom: 2 }}>{ev.time} · <span style={{ color: ev.color ?? t.textMuted, fontWeight: 600 }}>{ev.actor}</span></div>
                      <div style={{ fontSize: 13, color: t.textSub, lineHeight: 1.4 }}>{ev.msg}</div>
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          </div>
        )}
      </div>

      {/* Confirmation modal */}
      {confirm && (
        <div className="animate-fadeIn" style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100 }} onClick={() => setConfirm(null)}>
          <div className="animate-fadeUp" style={{ background: t.card, borderRadius: t.radiusLg, padding: "28px 32px", maxWidth: 420, width: "90%", boxShadow: t.shadowLg }} onClick={e => e.stopPropagation()}>
            <h3 style={{ margin: "0 0 10px", fontSize: 18, fontWeight: 700, color: t.text }}>Confirm: {confirm.label}</h3>
            <p style={{ margin: "0 0 24px", fontSize: 14, color: t.textSub, lineHeight: 1.6 }}>{confirm.message}</p>
            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
              <Btn t={t} variant="ghost" onClick={() => setConfirm(null)}>Cancel</Btn>
              <Btn t={t} variant={confirm.variant} onClick={() => doAction(confirm.label)}>{confirm.label}</Btn>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
