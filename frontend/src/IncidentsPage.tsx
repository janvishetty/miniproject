import { useState } from "react";
import type { Theme } from "./theme";
import { sevColor, statusColor } from "./theme";
import { Card, SevBadge, StatusBadge, SectionHead, Btn, ProgressBar, Icons } from "./ui";

const ALL = [
  { id: "INC-2026-8848", sev: "critical", status: "OPEN",          title: "Automated High-Velocity SWIFT Transaction Sweep",     asset: "swift-gateway-primary",  ip: "185.226.101.5",  analyst: "K. Brennan",  vector: "API Abuse",       created: "12:04", confidence: 94, impact: 92 },
  { id: "INC-2026-8847", sev: "high",     status: "INVESTIGATING", title: "Core Banking Auth Vault Memory Corruption Attempt",    asset: "auth-vault-cluster-01",  ip: "185.152.220.19", analyst: "M. Osei",     vector: "Exploit",         created: "11:58", confidence: 87, impact: 80 },
  { id: "INC-2026-8845", sev: "medium",   status: "OPEN",          title: "Card Authorization API SQL Injection Attempt",         asset: "card-proc-api.cluster",  ip: "192.168.1.5",    analyst: "Unassigned",  vector: "SQL Injection",   created: "11:52", confidence: 78, impact: 60 },
  { id: "INC-2026-8844", sev: "low",      status: "OPEN",          title: "Suspicious OAuth2 Token Reuse Across Regions",        asset: "oauth-svc.prod",         ip: "10.0.4.122",     analyst: "Unassigned",  vector: "Auth Anomaly",    created: "11:41", confidence: 62, impact: 35 },
  { id: "INC-2026-8843", sev: "medium",   status: "CONTAINED",     title: "Dead-Letter Queue Spike on Message Bus",              asset: "msg-broker-02",          ip: "10.0.2.81",      analyst: "T. Nkosi",    vector: "DoS Pattern",     created: "11:33", confidence: 71, impact: 55 },
  { id: "INC-2026-8840", sev: "low",      status: "OPEN",          title: "Compliance Audit Trail Gap in Log Store",             asset: "audit-log-store",        ip: "internal",       analyst: "Unassigned",  vector: "Config Drift",    created: "10:58", confidence: 55, impact: 28 },
  { id: "INC-2026-8838", sev: "critical", status: "RESOLVED",      title: "Brute-Force on Treasury Ledger Admin Portal",         asset: "treasury-ledger-svc",    ip: "91.108.4.77",    analyst: "K. Brennan",  vector: "Brute Force",     created: "09:14", confidence: 99, impact: 88 },
  { id: "INC-2026-8835", sev: "high",     status: "RESOLVED",      title: "Lateral Movement via Compromised Service Account",    asset: "k8s-cluster-prod",       ip: "10.0.8.44",      analyst: "M. Osei",     vector: "Lateral Movement",created: "08:31", confidence: 91, impact: 76 },
];

const TIMELINE = [
  { time: "12:09", actor: "AI Engine",   msg: "Correlated 847 events — matches FIN-APT-7 sweep tactic", color: "#7c3aed" },
  { time: "12:07", actor: "Rule R-104",  msg: "Threshold breached: 14,200 transactions/min",             color: "#d97706" },
  { time: "12:06", actor: "WAF",         msg: "Blocked 2,441 requests matching OWASP-API-2023",          color: "#dc2626" },
  { time: "12:04", actor: "SIEM",        msg: "Incident auto-created from event cluster EVC-88213",      color: "#2563eb" },
  { time: "12:03", actor: "API Gateway", msg: "First anomalous request from 185.226.101.5 detected",     color: "#64748b" },
];

type ConfirmAction = { label: string; message: string; variant: "danger" | "success" | "primary" } | null;

interface Props { t: Theme; showToast: (msg: string, type?: string) => void; }

export default function IncidentsPage({ t, showToast }: Props) {
  const [selected, setSelected] = useState(ALL[0]);
  const [filterSev, setFilterSev] = useState("All");
  const [filterStatus, setFilterStatus] = useState("All");
  const [search, setSearch] = useState("");
  const [confirm, setConfirm] = useState<ConfirmAction>(null);

  const filtered = ALL.filter(i => {
    if (filterSev !== "All" && i.sev !== filterSev.toLowerCase()) return false;
    if (filterStatus !== "All" && i.status !== filterStatus.toUpperCase()) return false;
    if (search && !i.title.toLowerCase().includes(search.toLowerCase()) && !i.id.includes(search)) return false;
    return true;
  });

  function doAction(label: string) {
    setConfirm(null);
    showToast(`${label} action taken on ${selected.id}`, label === "Escalate" ? "error" : "success");
  }

  return (
    <div style={{ display: "flex", flex: 1, minHeight: 0, animation: "fadeUp 0.25s ease-out" }}>

      {/* Sidebar list */}
      <div style={{ width: 380, borderRight: `1px solid ${t.border}`, display: "flex", flexDirection: "column", background: t.card, flexShrink: 0 }}>
        {/* Header */}
        <div style={{ padding: "20px 20px 14px", borderBottom: `1px solid ${t.border}` }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: t.text }}>Incidents</h2>
            <span style={{ background: t.redDim, color: t.red, border: `1px solid ${t.redBorder}`, borderRadius: 99, padding: "2px 10px", fontSize: 12, fontWeight: 600 }}>{filtered.length} open</span>
          </div>

          {/* Search */}
          <div style={{ display: "flex", alignItems: "center", background: t.bg, border: `1px solid ${t.border}`, borderRadius: t.radiusSm, padding: "7px 12px", gap: 8, marginBottom: 10 }}>
            <span style={{ color: t.textMuted }}>{Icons.search}</span>
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search by title or ID..." style={{ background: "none", border: "none", outline: "none", fontSize: 13, color: t.text, flex: 1 }}/>
          </div>

          {/* Filters */}
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" as const }}>
            {["All","Critical","High","Medium","Low"].map(s => (
              <button key={s} onClick={() => setFilterSev(s)} style={{ fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 99, border: `1px solid ${filterSev === s ? t.blue : t.border}`, background: filterSev === s ? t.blueDim : "transparent", color: filterSev === s ? t.blue : t.textSub, cursor: "pointer", transition: "all 0.15s" }}>{s}</button>
            ))}
            <div style={{ width: 1, background: t.border, margin: "0 2px" }}/>
            {["All","Open","Investigating","Contained","Resolved"].map(s => (
              <button key={s} onClick={() => setFilterStatus(s)} style={{ fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 99, border: `1px solid ${filterStatus === s ? t.blue : t.border}`, background: filterStatus === s ? t.blueDim : "transparent", color: filterStatus === s ? t.blue : t.textSub, cursor: "pointer", transition: "all 0.15s" }}>{s}</button>
            ))}
          </div>
        </div>

        {/* List */}
        <div style={{ flex: 1, overflowY: "auto" }}>
          {filtered.map(inc => (
            <div key={inc.id} onClick={() => setSelected(inc)} style={{ padding: "14px 20px", borderBottom: `1px solid ${t.border}`, cursor: "pointer", background: selected.id === inc.id ? t.blueDim : "transparent", borderLeft: `3px solid ${selected.id === inc.id ? t.blue : "transparent"}`, transition: "background 0.15s" }}
              onMouseEnter={e => { if (selected.id !== inc.id) e.currentTarget.style.background = t.bg; }}
              onMouseLeave={e => { if (selected.id !== inc.id) e.currentTarget.style.background = "transparent"; }}>
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
      </div>

      {/* Detail panel */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflowY: "auto" }}>
        {selected && (
          <div style={{ padding: "24px 28px" }} className="animate-fadeIn">
            {/* Title */}
            <div style={{ marginBottom: 20 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
                <span style={{ fontFamily: "'DM Mono',monospace", fontSize: 13, color: t.blue, fontWeight: 500 }}>{selected.id}</span>
                <SevBadge level={selected.sev} t={t}/>
                <StatusBadge status={selected.status} t={t}/>
              </div>
              <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: t.text, lineHeight: 1.3 }}>{selected.title}</h1>
            </div>

            {/* Action buttons */}
            <div style={{ display: "flex", gap: 10, marginBottom: 24, flexWrap: "wrap" as const }}>
              <Btn t={t} variant="primary" icon={Icons.eye} onClick={() => showToast("Investigation started for " + selected.id)}>Investigate</Btn>
              <Btn t={t} variant="success" onClick={() => setConfirm({ label: "Contain", message: `Isolate the affected asset (${selected.asset}) and stop the threat from spreading?`, variant: "success" })}>Contain Threat</Btn>
              <Btn t={t} variant="danger"  onClick={() => setConfirm({ label: "Escalate", message: `Escalate ${selected.id} to the senior analyst team and trigger PagerDuty?`, variant: "danger"  })}>Escalate</Btn>
              <Btn t={t} variant="ghost"   onClick={() => showToast("Report generated", "success")}>Generate Report</Btn>
            </div>

            {/* Meta grid */}
            <Card t={t} style={{ padding: "16px 20px", marginBottom: 20 }}>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 }}>
                {[["Source IP", selected.ip],["Affected Asset", selected.asset],["Attack Vector", selected.vector],["Assigned Analyst", selected.analyst],["Detected", selected.created],["Threat Actor", "FIN-APT-7 (suspected)"]].map(([label, val]) => (
                  <div key={label}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: t.textMuted, marginBottom: 3, textTransform: "uppercase" as const, letterSpacing: "0.04em" }}>{label}</div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: t.text, fontFamily: label === "Source IP" || label === "Detected" ? "'DM Mono',monospace" : undefined }}>{val}</div>
                  </div>
                ))}
              </div>
            </Card>

            {/* AI confidence */}
            <Card t={t} style={{ padding: "16px 20px", marginBottom: 20, border: `1px solid ${t.blueBorder}` }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
                <div style={{ width: 28, height: 28, borderRadius: 8, background: t.blueDim, display: "flex", alignItems: "center", justifyContent: "center", color: t.blue }}>{Icons.bot}</div>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 700, color: t.text }}>AI Analysis</div>
                  <div style={{ fontSize: 11, color: t.textSub }}>finbert-vantix-v2.1 · Explainable output</div>
                </div>
              </div>
              <p style={{ margin: "0 0 14px", fontSize: 13, color: t.textSub, lineHeight: 1.6 }}>
                Pattern matches <strong style={{ color: t.text }}>FIN-APT-7 sweep tactic</strong> with high confidence. The attacker is exploiting an unauthenticated SWIFT gateway endpoint to enumerate transaction IDs. Immediate WAF rate-limiting and IP block recommended.
              </p>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                <div>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
                    <span style={{ fontSize: 12, color: t.textSub, fontWeight: 500 }}>AI Confidence</span>
                    <span style={{ fontSize: 12, fontWeight: 700, color: t.red, fontFamily: "'DM Mono',monospace" }}>{selected.confidence}%</span>
                  </div>
                  <ProgressBar value={selected.confidence} color={t.red} t={t}/>
                </div>
                <div>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
                    <span style={{ fontSize: 12, color: t.textSub, fontWeight: 500 }}>Business Impact</span>
                    <span style={{ fontSize: 12, fontWeight: 700, color: t.amber, fontFamily: "'DM Mono',monospace" }}>{selected.impact}%</span>
                  </div>
                  <ProgressBar value={selected.impact} color={t.amber} t={t}/>
                </div>
              </div>
            </Card>

            {/* Timeline */}
            <Card t={t} style={{ padding: "16px 20px" }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: t.text, marginBottom: 14 }}>Investigation Timeline</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
                {TIMELINE.map((ev, i) => (
                  <div key={i} style={{ display: "flex", gap: 14, position: "relative" }}>
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", flexShrink: 0 }}>
                      <div style={{ width: 10, height: 10, borderRadius: "50%", background: ev.color, marginTop: 3, zIndex: 1 }}/>
                      {i < TIMELINE.length - 1 && <div style={{ width: 2, flex: 1, background: t.border, margin: "2px 0" }}/>}
                    </div>
                    <div style={{ paddingBottom: 16 }}>
                      <div style={{ fontSize: 11, color: t.textMuted, fontFamily: "'DM Mono',monospace", marginBottom: 2 }}>{ev.time} · <span style={{ color: ev.color, fontWeight: 600 }}>{ev.actor}</span></div>
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
