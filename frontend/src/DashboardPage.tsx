import { useState, useEffect } from "react";
import * as api from "./api";
import type { Theme } from "./theme";
import { Card, StatCard, SevBadge, ProgressBar, SectionHead, Btn, Icons } from "./ui";
import { Skeleton, SeverityDonut, HBars } from "./charts";

function nodeColor(risk: string, t: Theme) {
  if (risk === "critical") return t.red;
  if (risk === "high")     return t.amber;
  if (risk === "medium")   return t.medium;
  return t.green;
}

function streamTypeColor(type: string, t: Theme) {
  if (type === "alert" || type === "block") return t.redFill;
  if (type === "warn")  return t.amberFill;
  return t.greenFill;
}

interface Props { t: Theme; onNavigate: (tab: string) => void; }

export default function DashboardPage({ t, onNavigate }: Props) {
  const [data, setData] = useState<api.Dashboard | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let alive = true;
    setError("");
    api.dashboard().then(d => { if (alive) setData(d); })
      .catch(err => { if (alive) setError(err instanceof api.ApiError ? err.message : "Could not load the dashboard"); });
    return () => { alive = false; };
  }, [attempt]);

  if (!data) {
    return (
      <div style={{ padding: "24px 28px", flex: 1 }}>
        {error
          ? <div style={{ display: "flex", alignItems: "center", gap: 12, background: t.redDim, border: `1px solid ${t.redBorder}`, borderRadius: 8, padding: "10px 14px" }}>
              <span style={{ fontSize: 13, color: t.red }}>{error}</span>
              <Btn t={t} variant="ghost" size="sm" onClick={() => setAttempt(n => n + 1)}>Retry</Btn>
            </div>
          : <div aria-label="Loading dashboard">
              <Skeleton t={t} w={260} h={24} style={{ marginBottom: 10 }}/>
              <Skeleton t={t} w={420} h={14} style={{ marginBottom: 24 }}/>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, marginBottom: 24 }}>
                {[0, 1, 2].map(i => <Skeleton key={i} t={t} h={118} r={12}/>)}
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: 16 }}>
                <Skeleton t={t} h={300} r={12}/>
                <Skeleton t={t} h={300} r={12}/>
              </div>
            </div>}
      </div>
    );
  }

  const riskNodes = data.risk_map ?? [];
  // Quiet endpoints are hidden only when the endpoint field matches AND alerts is exactly 0; a missing or null count keeps the tile.
  const HIDE_WHEN_QUIET = ["/api/v1/accounts/balance", "/api/v1/transactions/history"];
  const visibleNodes = riskNodes.filter(n => !(n.endpoint !== undefined && HIDE_WHEN_QUIET.includes(n.endpoint) && n.alerts === 0));
  const stream = data.live_events ?? [];

  return (
    <div style={{ padding: "24px 28px", overflowY: "auto", flex: 1, minHeight: 0, animation: "fadeUp 0.25s ease-out" }}>

      {/* Page title */}
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 800, color: t.text }}>Security Overview</h1>
        <p style={{ margin: "4px 0 0", fontSize: 14, color: t.textSub }}>Live view of your FinTech security posture from the latest pipeline run.</p>
      </div>

      {/* Stat cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, marginBottom: 24 }}>
        <StatCard label="Active Incidents"    value={String(data.active_incidents)} sub={`${data.critical_open} critical need action`} icon={Icons.alert}    color={t.red}   t={t}/>
        <StatCard label="Platform Risk Score" value={`${data.platform_risk_score}/100`} sub="Severity-weighted mean risk of open incidents" icon={Icons.shield}  color={t.amber} progress={{ value: data.platform_risk_score, fill: t.amberFill }} t={t}/>
        <StatCard label="Events Analysed"     value={(data.events_analysed ?? 0).toLocaleString()} sub={data.events_analysed_sub ?? "Scored by the model"} icon={Icons.activity} color={t.link} t={t}/>
      </div>

      {/* Middle row */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: 16, marginBottom: 24 }}>

        <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
          {/* Risk heatmap */}
          <Card t={t} style={{ padding: "20px 24px" }}>
            <SectionHead title={data.risk_map_title ?? "Risk Map"} sub="Each node shows its current risk score — red means high priority" t={t}/>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(max(220px, calc((100% - 20px) / 3)), 1fr))", gap: 10 }}>
              {visibleNodes.length === 0 && <div style={{ fontSize: 12, color: t.textMuted }}>No risk map data in this run.</div>}
              {visibleNodes.map(node => {
                const color = nodeColor(node.risk, t);
                return (
                  <div key={node.id} style={{ background: t.bg, boxShadow: t.raisedSm, border: `1px solid ${t.border}`, borderRadius: t.radiusSm, padding: "12px 14px", cursor: "pointer", transition: "all 0.15s" }}
                    onMouseEnter={e => { e.currentTarget.style.borderColor = color; e.currentTarget.style.background = color + "0d"; }}
                    onMouseLeave={e => { e.currentTarget.style.borderColor = t.border; e.currentTarget.style.background = t.bg; }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                      <span style={{ fontSize: 11, fontWeight: 600, color: t.textMuted, background: t.card, border: `1px solid ${t.border}`, borderRadius: 4, padding: "1px 5px" }}>{node.tag}</span>
                      <span style={{ fontSize: 15, fontWeight: 500, color, fontFamily: "'DM Mono',monospace" }}>{node.score}</span>
                    </div>
                    <div style={{ fontSize: 12, fontWeight: 600, color: t.text, marginBottom: 6, lineHeight: 1.3 }}>{node.id}</div>
                    <ProgressBar value={node.score} color={color} t={t}/>
                    {node.alerts > 0
                      ? <div style={{ fontSize: 11, color, fontWeight: 600, marginTop: 5 }}>⚠ {node.alerts} {node.alerts === 1 ? "alert" : "alerts"}</div>
                      : <div style={{ fontSize: 11, color: t.green, marginTop: 5 }}>✓ Clear</div>}
                  </div>
                );
              })}
            </div>
          </Card>

          {/* Severity and attack-type breakdown */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            <Card t={t} style={{ padding: "20px 24px" }}>
              <SectionHead title="By Severity" sub="Open incidents" t={t}/>
              <SeverityDonut counts={data.by_severity ?? {}} t={t}/>
            </Card>
            <Card t={t} style={{ padding: "20px 24px" }}>
              <SectionHead title="By Attack Type" sub="Open incidents" t={t}/>
              <HBars rows={Object.entries(data.by_type ?? {}).map(([label, value]) => ({ label, value })).sort((a, b) => b.value - a.value)} color={t.link} fill={t.accentGrad} t={t} empty="No open incidents in this run."/>
            </Card>
          </div>
        </div>

        {/* Live event feed */}
        <Card t={t} style={{ padding: "20px 20px", display: "flex", flexDirection: "column", maxHeight: 560 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16 }}>
            <div className="live-dot" style={{ width: 8, height: 8, borderRadius: "50%", background: t.green, flexShrink: 0 }}/>
            <h2 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: t.text }}>Live Events</h2>
          </div>
          <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", gap: 8, overflowY: "auto" }}>
            {stream.length === 0 && <div style={{ fontSize: 12, color: t.textMuted }}>No live events in this run.</div>}
            {stream.map((e, i) => (
              <div key={i} className={i === 0 ? "animate-slideIn" : ""} style={{ display: "flex", gap: 10, padding: "8px 10px", background: t.bg, borderRadius: t.radiusSm, alignItems: "flex-start" }}>
                <div style={{ width: 7, height: 7, borderRadius: "50%", background: streamTypeColor(e.type ?? "", t), flexShrink: 0, marginTop: 4 }}/>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 11, fontWeight: 500, color: t.textMuted, fontFamily: "'DM Mono',monospace", marginBottom: 1 }}>{(e.ts ?? "").slice(5, 16)} · {e.node}</div>
                  <div style={{ fontSize: 12, color: t.textSub, lineHeight: 1.35 }}>{e.msg}</div>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* Recent incidents */}
      <Card t={t} style={{ padding: "20px 24px" }}>
        <SectionHead title="Recent Incidents" sub="Most recent security events requiring analyst attention" t={t}
          action={<Btn t={t} variant="primary" size="sm" onClick={() => onNavigate("INCIDENTS")}>View All Incidents</Btn>}/>
        <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
          {/* Header */}
          <div style={{ display: "grid", gridTemplateColumns: "120px 1fr 100px 120px 80px", gap: 12, padding: "8px 12px", fontSize: 11, fontWeight: 600, color: t.textMuted, textTransform: "uppercase", letterSpacing: "0.06em", borderBottom: `1px solid ${t.border}`, marginBottom: 4 }}>
            <span>Incident ID</span><span>Title</span><span>Severity</span><span>Status</span><span>Time</span>
          </div>
          {data.recent.length === 0 && <div style={{ fontSize: 12, color: t.textMuted, padding: "10px 12px" }}>No incidents in this run.</div>}
          {data.recent.map(inc => (
            <div key={inc.id} style={{ display: "grid", gridTemplateColumns: "120px 1fr 100px 120px 80px", gap: 12, padding: "10px 12px", borderRadius: t.radiusSm, cursor: "pointer", transition: "background 0.15s" }}
              onMouseEnter={e => (e.currentTarget.style.background = t.bg)}
              onMouseLeave={e => (e.currentTarget.style.background = "transparent")}
              onClick={() => onNavigate("INCIDENTS")}>
              <span style={{ fontFamily: "'DM Mono',monospace", fontSize: 12, color: t.link, fontWeight: 500 }}>{inc.id}</span>
              <span style={{ fontSize: 13, color: t.text, fontWeight: 500 }}>{inc.title}</span>
              <span><SevBadge level={inc.sev} t={t}/></span>
              <span style={{ fontSize: 12, color: inc.status === "OPEN" ? t.red : inc.status === "INVESTIGATING" ? t.amber : inc.status === "CONTAINED" ? t.medium : t.green, fontWeight: 600 }}>{inc.status.charAt(0) + inc.status.slice(1).toLowerCase()}</span>
              <span style={{ fontSize: 12, color: t.textMuted, fontFamily: "'DM Mono',monospace" }}>{inc.time}</span>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
