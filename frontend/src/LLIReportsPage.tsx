import { useState, useEffect } from "react";
import * as api from "./api";
import type { Theme } from "./theme";
import { Card, SectionHead, Btn, ProgressBar, Icons } from "./ui";

const STANDARDS = [
  { id: "pci", label: "PCI-DSS", desc: "Payment Card Industry Data Security Standard", color: "#2563eb", score: 91 },
  { id: "sox", label: "SOX",     desc: "Sarbanes-Oxley IT General Controls",           color: "#7c3aed", score: 74 },
  { id: "gdpr",label: "GDPR",    desc: "General Data Protection Regulation",           color: "#059669", score: 100},
  { id: "fca", label: "FCA",     desc: "Financial Conduct Authority SYSC",             color: "#d97706", score: 67 },
];

interface Props { t: Theme; showToast: (msg: string, type?: string) => void; }

export default function LLIReportsPage({ t, showToast }: Props) {
  const [tab, setTab] = useState<"reports"|"compliance"|"generate">("reports");
  const [genForm, setGenForm] = useState({ standard: "PCI-DSS", period: "Last 30 Days", scope: "Full Platform" });
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

  const lastPage = Math.max(1, Math.ceil(total / 20));
  const sampleTag = (
    <span style={{ display: "inline-block", marginBottom: 16, background: t.amberDim, color: t.amber, border: `1px solid ${t.amberBorder}`, borderRadius: 99, padding: "3px 10px", fontSize: 11, fontWeight: 600 }}>Sample data</span>
  );

  return (
    <div style={{ padding: "24px 28px", overflowY: "auto", flex: 1, minHeight: 0, animation: "fadeUp 0.25s ease-out" }}>

      {/* Page title + sub-nav */}
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ margin: "0 0 4px", fontSize: 22, fontWeight: 800, color: t.text }}>Incident Reports</h1>
        <p style={{ margin: "0 0 16px", fontSize: 14, color: t.textSub }}>AI-generated, fact-checked investigation reports for critical and high incidents.</p>
        <div style={{ display: "flex", gap: 4, background: t.bg, borderRadius: t.radiusSm, padding: 4, width: "fit-content", border: `1px solid ${t.border}` }}>
          {(["reports","compliance","generate"] as const).map(tb => (
            <button key={tb} onClick={() => setTab(tb)} style={{ padding: "6px 18px", borderRadius: 6, border: "none", background: tab === tb ? t.card : "transparent", color: tab === tb ? t.text : t.textSub, fontWeight: 600, fontSize: 13, cursor: "pointer", boxShadow: tab === tb ? t.shadow : "none", transition: "all 0.15s" }}>
              {tb === "reports" ? "All Reports" : tb === "compliance" ? "Compliance Status" : "Generate New"}
            </button>
          ))}
        </div>
      </div>

      {tab === "reports" && (
        <>
          {loading && <div style={{ fontSize: 13, color: t.textMuted }}>Loading reports...</div>}
          {!loading && error && (
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <span style={{ fontSize: 13, color: t.red }}>{error}</span>
              <Btn t={t} variant="ghost" size="sm" onClick={() => setAttempt(n => n + 1)}>Retry</Btn>
            </div>
          )}
          {!loading && !error && reports.length === 0 && <div style={{ fontSize: 13, color: t.textMuted }}>No incident reports have been generated yet.</div>}

          {/* Report cards grid */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))", gap: 16 }}>
            {!loading && reports.map(r => (
              <Card key={r.id} t={t} style={{ padding: "18px 20px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
                  <div>
                    <span style={{ fontFamily: "'DM Mono',monospace", fontSize: 11, color: t.blue, fontWeight: 500, display: "block", marginBottom: 4 }}>{r.id}</span>
                    <span style={{ background: t.badge, border: `1px solid ${t.border}`, borderRadius: 4, padding: "1px 7px", fontSize: 11, fontWeight: 600, color: t.textSub }}>{r.source}</span>
                  </div>
                  <span style={{ background: r.grounded ? t.greenDim : t.amberDim, color: r.grounded ? t.green : t.amber, border: `1px solid ${r.grounded ? t.greenBorder : t.amberBorder}`, borderRadius: 99, padding: "3px 10px", fontSize: 11, fontWeight: 600 }}>{r.grounded ? "Verified" : "Unverified"}</span>
                </div>
                <div style={{ fontSize: 14, fontWeight: 600, color: t.text, marginBottom: 6, lineHeight: 1.4 }}>{r.title}</div>
                <div style={{ fontSize: 12, color: t.textMuted }}>Created: {(r.created_at ?? "").slice(0, 16).replace("T", " ")}</div>
              </Card>
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
      )}

      {tab === "compliance" && (<>
        {sampleTag}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 20 }}>
          {STANDARDS.map(std => (
            <Card key={std.id} t={t} style={{ padding: "22px 24px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14 }}>
                <div>
                  <span style={{ fontSize: 22, fontWeight: 800, color: std.color, fontFamily: "'DM Mono',monospace" }}>{std.label}</span>
                  <div style={{ fontSize: 12, color: t.textSub, marginTop: 2 }}>{std.desc}</div>
                </div>
                <div style={{ textAlign: "right" as const }}>
                  <div style={{ fontSize: 30, fontWeight: 800, color: std.score >= 90 ? t.green : std.score >= 70 ? t.amber : t.red, fontFamily: "'DM Mono',monospace" }}>{std.score}<span style={{ fontSize: 14, color: t.textMuted }}>%</span></div>
                  <div style={{ fontSize: 11, color: t.textMuted }}>compliance</div>
                </div>
              </div>
              <ProgressBar value={std.score} color={std.score >= 90 ? t.green : std.score >= 70 ? t.amber : t.red} t={t}/>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10, marginTop: 16 }}>
                {[["Controls Passed", std.score >= 90 ? "47/50" : std.score >= 70 ? "37/50" : "28/42"],["Open Findings", std.score >= 90 ? "1" : std.score >= 70 ? "5" : "8"],["Last Assessed", "Aug 2026"]].map(([k, v]) => (
                  <div key={k} style={{ background: t.bg, borderRadius: t.radiusSm, padding: "10px 12px" }}>
                    <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 3 }}>{k}</div>
                    <div style={{ fontSize: 14, fontWeight: 700, color: t.text, fontFamily: "'DM Mono',monospace" }}>{v}</div>
                  </div>
                ))}
              </div>
            </Card>
          ))}
        </div>
      </>)}

      {tab === "generate" && (<>
        {sampleTag}
        <div style={{ maxWidth: 680 }}>
          <Card t={t} style={{ padding: "28px 32px" }}>
            <h2 style={{ margin: "0 0 6px", fontSize: 18, fontWeight: 700, color: t.text }}>Generate a New Report</h2>
            <p style={{ margin: "0 0 28px", fontSize: 14, color: t.textSub }}>Fill in the options below. The AI will automatically collect evidence, correlate findings, and format the report for regulators.</p>

            <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
              {[
                { label: "Regulatory Standard", key: "standard", opts: ["PCI-DSS","SOX","GDPR","FCA","SWIFT-CSP","SR 11-7","Internal Audit"] },
                { label: "Reporting Period",     key: "period",   opts: ["Last 7 Days","Last 30 Days","Last Quarter","Year to Date"] },
                { label: "Scope",                key: "scope",    opts: ["Full Platform","SWIFT Gateway Only","Card Processing","Auth Services"] },
              ].map(({ label, key, opts }) => (
                <div key={key}>
                  <label style={{ display: "block", fontSize: 13, fontWeight: 600, color: t.text, marginBottom: 8 }}>{label}</label>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" as const }}>
                    {opts.map(o => (
                      <button key={o} onClick={() => setGenForm(f => ({ ...f, [key]: o }))} style={{ padding: "7px 14px", borderRadius: t.radiusSm, border: `1px solid ${(genForm as Record<string,string>)[key] === o ? t.blue : t.border}`, background: (genForm as Record<string,string>)[key] === o ? t.blueDim : t.bg, color: (genForm as Record<string,string>)[key] === o ? t.blue : t.textSub, fontSize: 13, fontWeight: 500, cursor: "pointer", transition: "all 0.15s" }}>{o}</button>
                    ))}
                  </div>
                </div>
              ))}

              <div>
                <label style={{ display: "block", fontSize: 13, fontWeight: 600, color: t.text, marginBottom: 8 }}>Include Sections</label>
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {["Executive Summary","Control Assessment Results","Open Findings & Remediation","AI Explainability Appendix","Evidence Chain of Custody"].map((s, i) => (
                    <label key={s} style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer" }}>
                      <div style={{ width: 18, height: 18, borderRadius: 5, border: `1.5px solid ${i < 4 ? t.blue : t.border}`, background: i < 4 ? t.blue : "transparent", display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", flexShrink: 0 }}>
                        {i < 4 && <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>}
                      </div>
                      <span style={{ fontSize: 13, color: t.textSub }}>{s}</span>
                    </label>
                  ))}
                </div>
              </div>

              <div style={{ paddingTop: 8, borderTop: `1px solid ${t.border}`, display: "flex", gap: 12 }}>
                <Btn t={t} variant="primary" size="lg" icon={Icons.file} onClick={() => showToast("Report generation started — check Reports tab in ~2 minutes", "success")}>Generate Report</Btn>
                <Btn t={t} variant="secondary" size="lg" onClick={() => showToast("Preview generated", "success")}>Preview</Btn>
              </div>
            </div>
          </Card>
        </div>
      </>)}
    </div>
  );
}
