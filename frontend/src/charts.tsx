import { type Theme, sevColor } from "./theme";
import type { Reason, Severity } from "./api";

// ─── Loading skeleton (pulsing block) ────────────────────────────────────────
export function Skeleton({ t, w = "100%", h = 16, r = 6, style }: { t: Theme; w?: number | string; h?: number | string; r?: number; style?: React.CSSProperties }) {
  return <div style={{ width: w, height: h, borderRadius: r, background: t.border, animation: "pulse 1.5s ease-in-out infinite", ...style }}/>;
}

// ─── Severity donut ──────────────────────────────────────────────────────────
const SEV_ORDER: Severity[] = ["critical", "high", "medium", "low"];

export function SeverityDonut({ counts, t }: { counts: Partial<Record<Severity, number>>; t: Theme }) {
  const total = SEV_ORDER.reduce((n, s) => n + (counts[s] ?? 0), 0);
  if (total === 0) return <div style={{ fontSize: 12, color: t.textMuted }}>No open incidents in this run.</div>;
  const R = 44, C = 2 * Math.PI * R;
  let offset = 0;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
      <svg width="120" height="120" viewBox="0 0 120 120" role="img" aria-label="Open incidents by severity" style={{ flexShrink: 0 }}>
        <circle cx="60" cy="60" r={R} fill="none" stroke={t.badge} strokeWidth="16"/>
        {SEV_ORDER.map(s => {
          const n = counts[s] ?? 0;
          if (n === 0) return null;
          const len = (n / total) * C;
          const el = <circle key={s} cx="60" cy="60" r={R} fill="none" stroke={sevColor(s, t).text} strokeWidth="16" strokeDasharray={`${len} ${C - len}`} strokeDashoffset={-offset} transform="rotate(-90 60 60)"/>;
          offset += len;
          return el;
        })}
        <text x="60" y="58" textAnchor="middle" style={{ fontSize: 22, fontWeight: 800, fill: t.text, fontFamily: "'DM Mono',monospace" }}>{total}</text>
        <text x="60" y="74" textAnchor="middle" style={{ fontSize: 10, fill: t.textMuted }}>open</text>
      </svg>
      <div style={{ display: "flex", flexDirection: "column", gap: 6, flex: 1, minWidth: 0 }}>
        {SEV_ORDER.map(s => (
          <div key={s} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12 }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: sevColor(s, t).text, flexShrink: 0 }}/>
            <span style={{ color: t.textSub, flex: 1 }}>{s.charAt(0).toUpperCase() + s.slice(1)}</span>
            <span style={{ color: t.text, fontWeight: 700, fontFamily: "'DM Mono',monospace" }}>{counts[s] ?? 0}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Horizontal bars (label, bar, value) ─────────────────────────────────────
export function HBars({ rows, color, t, empty }: { rows: { label: string; value: number; note?: string }[]; color: string; t: Theme; empty: string }) {
  const max = Math.max(0, ...rows.map(r => r.value));
  if (rows.length === 0 || max === 0) return <div style={{ fontSize: 12, color: t.textMuted }}>{empty}</div>;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {rows.map(r => (
        <div key={r.label}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 10, marginBottom: 4, fontSize: 12 }}>
            <span style={{ color: t.textSub }}>{r.label}</span>
            <span style={{ color: t.text, fontWeight: 700, fontFamily: "'DM Mono',monospace" }}>{r.note ?? r.value}</span>
          </div>
          <div style={{ height: 8, background: t.badge, borderRadius: 99, overflow: "hidden" }}>
            <div style={{ height: "100%", width: `${(r.value / max) * 100}%`, background: color, borderRadius: 99, transition: "width 0.5s ease" }}/>
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── Impact bars for "Why it was flagged" ────────────────────────────────────
// Needs a numeric impact on every reason; otherwise the caller keeps the text list.
export function hasImpacts(reasons: Reason[]) {
  return reasons.length > 0 && reasons.every(r => typeof r.impact === "number" && Number.isFinite(r.impact));
}

export function ImpactBars({ reasons, t }: { reasons: Reason[]; t: Theme }) {
  const rows = [...reasons].sort((a, b) => (b.impact ?? 0) - (a.impact ?? 0)).map(r => ({ label: r.text ?? r.feature ?? "—", value: Math.abs(r.impact ?? 0), note: (r.impact ?? 0).toFixed(3) }));
  return (
    <>
      <HBars rows={rows} color={t.amber} t={t} empty="No impact data."/>
      <div style={{ fontSize: 11, color: t.textMuted, marginTop: 10 }}>Bar length is relative to the strongest factor for this incident.</div>
    </>
  );
}
