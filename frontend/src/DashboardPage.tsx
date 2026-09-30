import { useState, useEffect } from "react";
import type { Theme } from "./theme";
import { Card, StatCard, SevBadge, ProgressBar, SectionHead, Btn, Icons } from "./ui";

const RISK_NODES = [
  { id: "SWIFT Gateway",      score: 94, tag: "SWIFT",   alerts: 14, risk: "critical" },
  { id: "Banking Auth",       score: 82, tag: "AUTH",    alerts: 6,  risk: "high"     },
  { id: "Card Processing",    score: 78, tag: "CARD",    alerts: 5,  risk: "high"     },
  { id: "PCI HSM Tokens",     score: 45, tag: "PCI",     alerts: 2,  risk: "medium"   },
  { id: "Treasury Ledger",    score: 22, tag: "LEDGER",  alerts: 0,  risk: "low"      },
  { id: "Kubernetes Cluster", score: 58, tag: "K8S",     alerts: 4,  risk: "medium"   },
  { id: "Banking App",        score: 50, tag: "APP",     alerts: 3,  risk: "medium"   },
  { id: "MFA Core Router",    score: 30, tag: "MFA",     alerts: 1,  risk: "low"      },
];

const RECENT = [
  { id: "INC-2026-8848", sev: "critical", title: "High-Velocity SWIFT Transaction Sweep",     time: "12:04",  status: "OPEN"          },
  { id: "INC-2026-8847", sev: "high",     title: "Auth Vault Memory Corruption Attempt",      time: "11:58",  status: "INVESTIGATING"  },
  { id: "INC-2026-8845", sev: "medium",   title: "Card API SQL Injection Detected",           time: "11:52",  status: "OPEN"           },
  { id: "INC-2026-8843", sev: "medium",   title: "Message Bus Dead-Letter Queue Spike",       time: "11:33",  status: "CONTAINED"      },
  { id: "INC-2026-8840", sev: "low",      title: "Audit Trail Gap in Log Store",              time: "10:58",  status: "OPEN"           },
];

const STREAM_POOL = [
  { node: "SWIFT-GW",   msg: "Batch of 1,204 events ingested successfully",   type: "ok"      },
  { node: "CARD-PROC",  msg: "Rate limit reached on /v1/tokenize",            type: "warn"    },
  { node: "ML-ENGINE",  msg: "Anomaly score 0.97 exceeds critical threshold", type: "alert"   },
  { node: "WAF",        msg: "Blocked 2,441 requests — OWASP-API-2023",       type: "block"   },
  { node: "COMPLIANCE", msg: "PCI-DSS log chain verified OK",                 type: "ok"      },
  { node: "IDS",        msg: "Port scan from 45.152.66.11 detected",          type: "alert"   },
];

function nodeColor(risk: string, t: Theme) {
  if (risk === "critical") return t.red;
  if (risk === "high")     return t.amber;
  if (risk === "medium")   return t.blue;
  return t.green;
}

function streamTypeColor(type: string, t: Theme) {
  if (type === "alert" || type === "block") return t.red;
  if (type === "warn")  return t.amber;
  return t.green;
}

interface Props { t: Theme; onNavigate: (tab: string) => void; }

export default function DashboardPage({ t, onNavigate }: Props) {
  const [eps, setEps] = useState(14288);
  const [stream, setStream] = useState(STREAM_POOL.slice(0, 4).map((e, i) => ({ ...e, id: i, ts: `12:09:0${i}` })));
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const iv = setInterval(() => {
      setEps(v => Math.round(v + (Math.random() - 0.5) * 120));
      setTick(x => x + 1);
    }, 1500);
    return () => clearInterval(iv);
  }, []);

  useEffect(() => {
    const iv = setInterval(() => {
      const e = STREAM_POOL[Math.floor(Math.random() * STREAM_POOL.length)];
      const ts = new Date().toTimeString().slice(0, 8);
      setStream(prev => [{ ...e, id: Date.now(), ts }, ...prev.slice(0, 7)]);
    }, 2200);
    return () => clearInterval(iv);
  }, []);

  return (
    <div style={{ padding: "24px 28px", overflowY: "auto", flex: 1, minHeight: 0, animation: "fadeUp 0.25s ease-out" }}>

      {/* Page title */}
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 800, color: t.text }}>Security Overview</h1>
        <p style={{ margin: "4px 0 0", fontSize: 14, color: t.textSub }}>Real-time view of your FinTech security posture — updated every few seconds.</p>
      </div>

      {/* Stat cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 24 }}>
        <StatCard label="Active Incidents"    value="6"       sub="2 critical need action" icon={Icons.alert}    color={t.red}   t={t}/>
        <StatCard label="Platform Risk Score" value="67/100"  sub="Elevated — up 3 pts"    icon={Icons.shield}  color={t.amber} t={t}/>
        <StatCard label="Events / Second"     value={`${(eps/1000).toFixed(1)}K`} sub="Live SIEM ingest rate" icon={Icons.activity} color={t.blue} t={t}/>
        <StatCard label="Avg Response Time"   value="4m 12s"  sub="Target: under 5 min"    icon={Icons.clock}   color={t.green} t={t}/>
      </div>

      {/* Middle row */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: 16, marginBottom: 24 }}>

        {/* Risk heatmap */}
        <Card t={t} style={{ padding: "20px 24px" }}>
          <SectionHead title="Infrastructure Risk Map" sub="Each node shows its current risk score — red means high priority" t={t}/>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10 }}>
            {RISK_NODES.map(node => {
              const color = nodeColor(node.risk, t);
              return (
                <div key={node.id} style={{ background: t.bg, border: `1px solid ${t.border}`, borderRadius: t.radiusSm, padding: "12px 14px", cursor: "pointer", transition: "all 0.15s" }}
                  onMouseEnter={e => { e.currentTarget.style.borderColor = color; e.currentTarget.style.background = color + "0d"; }}
                  onMouseLeave={e => { e.currentTarget.style.borderColor = t.border; e.currentTarget.style.background = t.bg; }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                    <span style={{ fontSize: 10, fontWeight: 600, color: t.textMuted, background: t.card, border: `1px solid ${t.border}`, borderRadius: 4, padding: "1px 5px" }}>{node.tag}</span>
                    <span style={{ fontSize: 15, fontWeight: 800, color, fontFamily: "'DM Mono',monospace" }}>{node.score}</span>
                  </div>
                  <div style={{ fontSize: 12, fontWeight: 600, color: t.text, marginBottom: 6, lineHeight: 1.3 }}>{node.id}</div>
                  <ProgressBar value={node.score} color={color} t={t}/>
                  {node.alerts > 0
                    ? <div style={{ fontSize: 11, color, fontWeight: 600, marginTop: 5 }}>⚠ {node.alerts} alerts</div>
                    : <div style={{ fontSize: 11, color: t.green, marginTop: 5 }}>✓ Clear</div>}
                </div>
              );
            })}
          </div>
        </Card>

        {/* Live event feed */}
        <Card t={t} style={{ padding: "20px 20px", display: "flex", flexDirection: "column" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16 }}>
            <div className="live-dot" style={{ width: 8, height: 8, borderRadius: "50%", background: t.green, flexShrink: 0 }}/>
            <h2 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: t.text }}>Live Events</h2>
          </div>
          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 8, overflowY: "auto" }}>
            {stream.map((e, i) => (
              <div key={e.id} className={i === 0 ? "animate-slideIn" : ""} style={{ display: "flex", gap: 10, padding: "8px 10px", background: t.bg, borderRadius: t.radiusSm, alignItems: "flex-start" }}>
                <div style={{ width: 7, height: 7, borderRadius: "50%", background: streamTypeColor(e.type, t), flexShrink: 0, marginTop: 4 }}/>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 10, fontWeight: 600, color: t.textMuted, fontFamily: "'DM Mono',monospace", marginBottom: 1 }}>{e.ts} · {e.node}</div>
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
          <div style={{ display: "grid", gridTemplateColumns: "120px 1fr 100px 120px 80px", gap: 12, padding: "8px 12px", fontSize: 11, fontWeight: 600, color: t.textMuted, borderBottom: `1px solid ${t.border}`, marginBottom: 4 }}>
            <span>Incident ID</span><span>Title</span><span>Severity</span><span>Status</span><span>Time</span>
          </div>
          {RECENT.map(inc => (
            <div key={inc.id} style={{ display: "grid", gridTemplateColumns: "120px 1fr 100px 120px 80px", gap: 12, padding: "10px 12px", borderRadius: t.radiusSm, cursor: "pointer", transition: "background 0.15s" }}
              onMouseEnter={e => (e.currentTarget.style.background = t.bg)}
              onMouseLeave={e => (e.currentTarget.style.background = "transparent")}
              onClick={() => onNavigate("INCIDENTS")}>
              <span style={{ fontFamily: "'DM Mono',monospace", fontSize: 12, color: t.blue, fontWeight: 500 }}>{inc.id}</span>
              <span style={{ fontSize: 13, color: t.text, fontWeight: 500 }}>{inc.title}</span>
              <span><SevBadge level={inc.sev} t={t}/></span>
              <span style={{ fontSize: 12, color: inc.status === "OPEN" ? t.red : inc.status === "INVESTIGATING" ? t.amber : inc.status === "CONTAINED" ? t.blue : t.green, fontWeight: 600 }}>{inc.status.charAt(0) + inc.status.slice(1).toLowerCase()}</span>
              <span style={{ fontSize: 12, color: t.textMuted, fontFamily: "'DM Mono',monospace" }}>{inc.time}</span>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
