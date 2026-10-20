import { type Theme, sevColor, statusColor } from "./theme";

// ─── Badge ───────────────────────────────────────────────────────────────────
export function SevBadge({ level, t }: { level: string; t: Theme }) {
  const c = sevColor(level, t);
  return (
    <span style={{ background: c.bg, color: c.text, border: `1px solid ${c.border}`, borderRadius: 99, padding: "2px 10px", fontSize: 11, fontWeight: 600, whiteSpace: "nowrap" as const, display: "inline-flex", alignItems: "center", gap: 4 }}>
      <span style={{ width: 6, height: 6, borderRadius: "50%", background: c.text, display: "inline-block", flexShrink: 0 }}/>
      {level.charAt(0).toUpperCase() + level.slice(1)}
    </span>
  );
}

export function StatusBadge({ status, t }: { status: string; t: Theme }) {
  const c = statusColor(status, t);
  return (
    <span style={{ background: c.bg, color: c.text, border: `1px solid ${c.border}`, borderRadius: 99, padding: "2px 10px", fontSize: 11, fontWeight: 600, whiteSpace: "nowrap" as const }}>
      {status.charAt(0) + status.slice(1).toLowerCase().replace("_", " ")}
    </span>
  );
}

// ─── Report source label ─────────────────────────────────────────────────────
export function sourceLabel(source: string | null | undefined) {
  if (source === "llm") return "LLM";
  if (source === "llm_corrected") return "LLM · self-corrected";
  if (source === "template") return "Template";
  if (source === "facts") return "From data (no LLM)";
  return source ?? "—";
}

// ─── Button ──────────────────────────────────────────────────────────────────
type BtnVariant = "primary" | "secondary" | "ghost" | "danger" | "success";
interface BtnProps {
  children: React.ReactNode;
  onClick?: () => void;
  variant?: BtnVariant;
  t: Theme;
  disabled?: boolean;
  size?: "sm" | "md" | "lg";
  fullWidth?: boolean;
  icon?: React.ReactNode;
}
export function Btn({ children, onClick, variant = "secondary", t, disabled, size = "md", fullWidth, icon }: BtnProps) {
  const styles: Record<BtnVariant, { bg: string; color: string; border: string; hoverBg: string }> = {
    primary:   { bg: t.primary, color: t.textInv,   border: t.primary,      hoverBg: t.primaryHover },
    secondary: { bg: t.btn,     color: t.text,       border: t.btnBorder,    hoverBg: t.cardHover },
    ghost:     { bg: "transparent", color: t.textSub, border: "transparent", hoverBg: t.badge },
    danger:    { bg: t.redDim,  color: t.red,        border: t.redBorder,    hoverBg: t.red + "22" },
    success:   { bg: t.greenDim,color: t.green,      border: t.greenBorder,  hoverBg: t.green + "22" },
  };
  const pad = size === "sm" ? "6px 12px" : size === "lg" ? "12px 24px" : "8px 16px";
  const fs  = size === "sm" ? 12 : size === "lg" ? 15 : 13;
  const s = styles[variant];
  // Neumorphic: raised at rest, pressed (inset) while the mouse is down. Ghost stays flat.
  const raised = variant === "ghost" ? "none" : size === "sm" ? t.raisedSm : t.raised;
  const pressed = variant === "ghost" ? "none" : t.inset;

  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{ background: s.bg, color: s.color, border: `1px solid ${s.border}`, boxShadow: raised, borderRadius: t.radiusSm, padding: pad, fontSize: fs, fontWeight: 600, cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.5 : 1, display: "inline-flex", alignItems: "center", gap: 6, width: fullWidth ? "100%" : undefined, justifyContent: fullWidth ? "center" : undefined, transition: "all 0.15s", whiteSpace: "nowrap" as const }}
      onMouseEnter={e => { if (!disabled) e.currentTarget.style.background = s.hoverBg; }}
      onMouseLeave={e => { e.currentTarget.style.background = s.bg; e.currentTarget.style.boxShadow = raised; }}
      onMouseDown={e => { if (!disabled) e.currentTarget.style.boxShadow = pressed; }}
      onMouseUp={e => { e.currentTarget.style.boxShadow = raised; }}
    >
      {icon && <span style={{ display: "flex", alignItems: "center" }}>{icon}</span>}
      {children}
    </button>
  );
}

// ─── Card ────────────────────────────────────────────────────────────────────
export function Card({ children, t, onClick, hoverable, style }: { children: React.ReactNode; t: Theme; onClick?: () => void; hoverable?: boolean; style?: React.CSSProperties }) {
  const lift = !!onClick || !!hoverable;
  return (
    <div
      onClick={onClick}
      data-glass=""
      style={{ background: t.glass, border: `1px solid ${t.glassBorder}`, backdropFilter: t.blur, WebkitBackdropFilter: t.blur, borderRadius: t.radius, boxShadow: t.shadow, cursor: onClick ? "pointer" : undefined, transition: "box-shadow 0.2s, transform 0.2s", ...style }}
      onMouseEnter={e => { if (lift) { e.currentTarget.style.boxShadow = t.shadowMd; e.currentTarget.style.transform = "translateY(-1px)"; } }}
      onMouseLeave={e => { if (lift) { e.currentTarget.style.boxShadow = t.shadow; e.currentTarget.style.transform = "none"; } }}
    >
      {children}
    </div>
  );
}

// ─── Section heading ─────────────────────────────────────────────────────────
export function SectionHead({ title, sub, t, action }: { title: string; sub?: string; t: Theme; action?: React.ReactNode }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
      <div>
        <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: t.text }}>{title}</h2>
        {sub && <p style={{ margin: "2px 0 0", fontSize: 13, color: t.textSub }}>{sub}</p>}
      </div>
      {action}
    </div>
  );
}

// ─── Stat card ───────────────────────────────────────────────────────────────
export function StatCard({ label, value, sub, icon, color, t }: { label: string; value: string; sub?: string; icon: React.ReactNode; color: string; t: Theme }) {
  return (
    <Card t={t} style={{ padding: "20px 24px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
        <div style={{ width: 40, height: 40, borderRadius: 10, background: t.bg, boxShadow: t.raisedSm, display: "flex", alignItems: "center", justifyContent: "center", color }}>
          {icon}
        </div>
      </div>
      <div style={{ fontSize: 28, fontWeight: 800, color: t.text, fontFamily: "'DM Mono', monospace", lineHeight: 1.1 }}>{value}</div>
      <div style={{ fontSize: 13, fontWeight: 600, color: t.textSub, marginTop: 4 }}>{label}</div>
      {sub && <div style={{ fontSize: 12, color: t.textMuted, marginTop: 2 }}>{sub}</div>}
    </Card>
  );
}

// ─── Progress bar ────────────────────────────────────────────────────────────
export function ProgressBar({ value, max = 100, color, t }: { value: number; max?: number; color: string; t: Theme }) {
  const pct = Math.min(100, (value / max) * 100);
  return (
    <div style={{ height: 6, background: t.input, boxShadow: t.inset, borderRadius: 99, overflow: "hidden" }}>
      <div style={{ height: "100%", width: `${pct}%`, background: color, borderRadius: 99, transition: "width 0.5s ease" }}/>
    </div>
  );
}

// ─── Empty state ─────────────────────────────────────────────────────────────
export function EmptyState({ icon, title, sub, t }: { icon: React.ReactNode; title: string; sub: string; t: Theme }) {
  return (
    <div style={{ textAlign: "center", padding: "40px 24px" }}>
      <div style={{ width: 48, height: 48, borderRadius: "50%", background: t.input, boxShadow: t.inset, color: t.textMuted, display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 12px" }}>{icon}</div>
      <div style={{ fontSize: 15, fontWeight: 600, color: t.text, marginBottom: 4 }}>{title}</div>
      <div style={{ fontSize: 13, color: t.textSub }}>{sub}</div>
    </div>
  );
}

// ─── Icon helpers (inline SVG) ────────────────────────────────────────────────
export const Icons = {
  dashboard: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>,
  incidents:  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>,
  reports:    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>,
  copilot:    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>,
  shield:     <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>,
  alert:      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>,
  activity:   <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>,
  clock:      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>,
  check:      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>,
  x:          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>,
  search:     <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>,
  download:   <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>,
  refresh:    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/></svg>,
  send:       <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>,
  chevron:    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 18 15 12 9 6"/></svg>,
  sun:        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>,
  moon:       <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/></svg>,
  bot:        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/><line x1="8" y1="16" x2="8" y2="16"/><line x1="16" y1="16" x2="16" y2="16"/></svg>,
  file:       <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>,
  plus:       <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>,
  eye:        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>,
};
