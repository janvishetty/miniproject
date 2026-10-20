import { useState, useEffect } from "react";
import * as api from "./api";
import type { Theme } from "./theme";
import { Card, Btn, SevBadge, EmptyState, Icons, sourceLabel } from "./ui";
import { Skeleton } from "./charts";
import ReportDetailPage, { reportIdFromHash, openReportHash, closeReportHash } from "./ReportDetailPage";

interface Props { t: Theme; showToast: (msg: string, type?: string) => void; onOpenIncident: (id: string) => void; }

export default function LLIReportsPage({ t, showToast, onOpenIncident }: Props) {
  const [selectedId, setSelectedId] = useState<string | null>(reportIdFromHash);
  const [reports, setReports] = useState<api.Report[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError("");
    api.listReports(page, 20)
      .then(res => { if (alive) { setReports(res.items); setTotal(res.total); setLoading(false); } })
      .catch(err => { if (alive) { setError(err instanceof api.ApiError ? err.message : "Could not load reports"); setLoading(false); } });
    return () => { alive = false; };
  }, [page, attempt]);

  // Browser Back/Forward, a pasted link and the Back button all just change the hash.
  useEffect(() => {
    const sync = () => setSelectedId(reportIdFromHash());
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  const lastPage = Math.max(1, Math.ceil(total / 20));

  if (selectedId) {
    return <ReportDetailPage key={selectedId} t={t} id={selectedId} showToast={showToast}
      onBack={() => { setAttempt(n => n + 1); closeReportHash(); }} onOpenIncident={onOpenIncident}/>;
  }

  return (
    <div style={{ padding: "24px 28px", overflowY: "auto", flex: 1, minHeight: 0, animation: "fadeUp 0.25s ease-out" }}>

      {/* Page title */}
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ margin: "0 0 4px", fontSize: 22, fontWeight: 800, color: t.text }}>Incident Reports</h1>
        <p style={{ margin: 0, fontSize: 14, color: t.textSub }}>AI-generated, fact-checked investigation reports for critical and high incidents.</p>
      </div>

      <>
          {loading && (
            <div aria-label="Loading reports" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))", gap: 16 }}>
              {[0, 1, 2, 3, 4, 5].map(i => <Skeleton key={i} t={t} h={118} r={12}/>)}
            </div>
          )}
          {!loading && error && (
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <span style={{ fontSize: 13, color: t.red }}>{error}</span>
              <Btn t={t} variant="ghost" size="sm" onClick={() => setAttempt(n => n + 1)}>Retry</Btn>
            </div>
          )}
          {!loading && !error && reports.length === 0 && (
            <Card t={t}><EmptyState icon={Icons.reports} title="No reports yet" sub="Open an incident and choose Generate Report." t={t}/></Card>
          )}

          {/* Report cards grid */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))", gap: 16 }}>
            {!loading && reports.map(r => (
              <div key={r.id} role="button" tabIndex={0} aria-label={`Open report ${r.id}: ${r.title}`}
                onClick={() => openReportHash(r.id)}
                onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openReportHash(r.id); } }}
                onFocus={e => { if (e.currentTarget.matches(":focus-visible")) { e.currentTarget.style.outline = `2px solid ${t.blue}`; e.currentTarget.style.outlineOffset = "2px"; } }}
                onBlur={e => { e.currentTarget.style.outline = "none"; }}
                style={{ borderRadius: t.radius, cursor: "pointer", outline: "none" }}>
              <Card t={t} hoverable style={{ padding: "18px 20px", height: "100%" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
                  <div>
                    <span style={{ fontFamily: "'DM Mono',monospace", fontSize: 11, color: t.blue, fontWeight: 500, display: "block", marginBottom: 4 }}>{r.id}</span>
                    <span style={{ background: t.badge, border: `1px solid ${t.border}`, borderRadius: 4, padding: "1px 7px", fontSize: 11, fontWeight: 600, color: t.textSub }}>{sourceLabel(r.source)}</span>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
                  <SevBadge level={r.sev} t={t}/>
                  <span style={{ background: r.grounded ? t.greenDim : t.amberDim, color: r.grounded ? t.green : t.amber, border: `1px solid ${r.grounded ? t.greenBorder : t.amberBorder}`, borderRadius: 99, padding: "3px 10px", fontSize: 11, fontWeight: 600 }}>{r.grounded ? "Verified" : "Unverified"}</span>
                  </div>
                </div>
                <div style={{ fontSize: 14, fontWeight: 600, color: t.text, marginBottom: 6, lineHeight: 1.4 }}>{r.title}</div>
                {r.summary && <div style={{ fontSize: 12, color: t.textSub, lineHeight: 1.5, marginBottom: 8, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{r.summary}</div>}
                <div style={{ fontSize: 12, color: t.textMuted }}>Created: {(r.created_at ?? "").slice(0, 16).replace("T", " ")}</div>
              </Card>
              </div>
            ))}
          </div>

          {total > 20 && (
            <div style={{ display: "flex", alignItems: "center", gap: 14, marginTop: 20 }}>
              <Btn t={t} variant="ghost" size="sm" disabled={page <= 1 || loading} onClick={() => setPage(p => p - 1)}>Previous</Btn>
              <span style={{ fontSize: 12, color: t.textMuted }}>Page {page} of {lastPage}</span>
              <Btn t={t} variant="ghost" size="sm" disabled={page >= lastPage || loading} onClick={() => setPage(p => p + 1)}>Next</Btn>
            </div>
          )}
      </>
    </div>
  );
}
