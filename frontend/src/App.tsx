import { useState, useEffect, useRef } from "react";
import { LIGHT, DARK } from "./theme";
import { Icons, LogoMark } from "./ui";
import LoginPage, { type UserProfile } from "./LoginPage";
import DashboardPage from "./DashboardPage";
import IncidentsPage from "./IncidentsPage";
import LLIReportsPage from "./LLIReportsPage";
import AICopilotPage from "./AICopilotPage";
import { reportIdFromHash, openReportHash, clearReportHash } from "./ReportDetailPage";
import * as api from "./api";

// ─── Toast ────────────────────────────────────────────────────────────────────
type Toast = { id: number; msg: string; type: string };

function ToastItem({ toast, t, onRemove }: { toast: Toast; t: ReturnType<typeof getTheme>; onRemove: () => void }) {
  useEffect(() => { const timer = setTimeout(onRemove, 3600); return () => clearTimeout(timer); }, []);
  const color  = toast.type === "error" ? t.red   : toast.type === "warning" ? t.amber  : t.green;
  const bg     = toast.type === "error" ? t.redDim: toast.type === "warning" ? t.amberDim: t.greenDim;
  const border = toast.type === "error" ? t.redBorder: toast.type === "warning" ? t.amberBorder: t.greenBorder;
  return (
    <div className="animate-slideIn" style={{ background: t.card, border: `1px solid ${border}`, borderLeft: `4px solid ${color}`, borderRadius: t.radiusSm, padding: "12px 14px", boxShadow: t.shadowMd, display: "flex", alignItems: "center", gap: 10, minWidth: 280, maxWidth: 380 }}>
      <span style={{ color, fontSize: 16, flexShrink: 0 }}>{toast.type === "error" ? "⚠" : "✓"}</span>
      <span style={{ fontSize: 13, color: t.text, flex: 1, fontWeight: 500 }}>{toast.msg}</span>
      <button onClick={onRemove} style={{ background: "none", border: "none", color: t.textMuted, cursor: "pointer", padding: "0 2px", fontSize: 18, lineHeight: 1 }}>×</button>
    </div>
  );
}

function getTheme(isDark: boolean) { return isDark ? DARK : LIGHT; }

const TABS = [
  { id: "DASHBOARD",   label: "Dashboard",  icon: Icons.dashboard },
  { id: "INCIDENTS",   label: "Incidents",  icon: Icons.incidents  },
  { id: "LLI REPORTS", label: "Reports",    icon: Icons.reports   },
  { id: "AI COPILOT",  label: "AI Copilot", icon: Icons.copilot   },
] as const;

const POSITIONS = [
  "Security Analyst", "Senior Analyst", "SOC Manager",
  "Threat Intelligence Lead", "Compliance Officer", "Platform Engineer", "CISO / CTO",
];

// ─── Profile dropdown ─────────────────────────────────────────────────────────
function ProfileDropdown({ user, t, isDark, setIsDark, onEdit, onSignOut, onClose }: {
  user: UserProfile; t: ReturnType<typeof getTheme>; isDark: boolean;
  setIsDark: (v: boolean) => void; onEdit: () => void; onSignOut: () => void; onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const menuItem = (label: string, icon: React.ReactNode, onClick: () => void, danger = false) => (
    <button onClick={onClick} style={{ display: "flex", alignItems: "center", gap: 10, width: "100%", background: "none", border: "none", padding: "9px 14px", fontSize: 13, color: danger ? t.red : t.textSub, cursor: "pointer", fontFamily: "inherit", textAlign: "left" as const, transition: "background 0.12s" }}
      onMouseEnter={e => (e.currentTarget.style.background = t.badge)}
      onMouseLeave={e => (e.currentTarget.style.background = "none")}>
      <span style={{ color: danger ? t.red : t.textMuted, display: "flex" }}>{icon}</span>
      {label}
    </button>
  );

  return (
    <div ref={ref} className="animate-fadeUp" style={{ position: "absolute" as const, top: "calc(100% + 8px)", right: 0, width: 260, background: t.card, border: `1px solid ${t.border}`, borderRadius: t.radius, boxShadow: t.shadowLg, zIndex: 200, overflow: "hidden" }}>
      {/* User info */}
      <div style={{ padding: "16px 14px 12px", borderBottom: `1px solid ${t.border}` }}>
        <div style={{ width: 40, height: 40, borderRadius: "50%", background: t.brandGrad, display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontWeight: 700, fontSize: 14, marginBottom: 10 }}>
          {user.name.split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase()}
        </div>
        <div style={{ fontSize: 14, fontWeight: 700, color: t.text, marginBottom: 2 }}>{user.name}</div>
        <div style={{ fontSize: 12, color: t.textMuted, fontFamily: "'DM Mono', monospace", marginBottom: 2 }}>@{user.username}</div>
        <div style={{ fontSize: 12, color: t.textSub }}>{user.email}</div>
        <div style={{ marginTop: 6, display: "inline-block", background: t.linkDim, color: t.link, border: `1px solid ${t.linkBorder}`, borderRadius: 99, padding: "2px 9px", fontSize: 11, fontWeight: 600 }}>{user.position}</div>
      </div>

      {/* Actions */}
      <div style={{ padding: "6px 0" }}>
        {menuItem("Edit Profile", Icons.eye, () => { onEdit(); onClose(); })}
        {menuItem("Change Password", <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg>, () => { onClose(); })}
        <div style={{ padding: "6px 14px" }}>
          <button onClick={() => setIsDark(!isDark)} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%", background: "none", border: "none", padding: "3px 0", fontSize: 13, color: t.textSub, cursor: "pointer", fontFamily: "inherit" }}>
            <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{ color: t.textMuted, display: "flex" }}>{isDark ? Icons.sun : Icons.moon}</span>
              {isDark ? "Light mode" : "Dark mode"}
            </span>
            <div style={{ width: 36, height: 20, borderRadius: 99, background: isDark ? t.blue : t.border, position: "relative" as const, transition: "background 0.2s", flexShrink: 0 }}>
              <div style={{ position: "absolute" as const, top: 2, left: isDark ? 18 : 2, width: 16, height: 16, borderRadius: "50%", background: "#fff", boxShadow: "0 1px 3px rgba(0,0,0,0.3)", transition: "left 0.2s" }}/>
            </div>
          </button>
        </div>
      </div>

      <div style={{ borderTop: `1px solid ${t.border}`, padding: "6px 0" }}>
        {menuItem("Sign out", <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>, onSignOut, true)}
      </div>
    </div>
  );
}

// ─── Edit profile modal ───────────────────────────────────────────────────────
function EditProfileModal({ user, t, onSave, onClose }: {
  user: UserProfile; t: ReturnType<typeof getTheme>; onSave: (u: UserProfile) => void; onClose: () => void;
}) {
  const [form, setForm] = useState({ ...user });

  const inputStyle = { width: "100%", padding: "9px 12px", borderRadius: t.radiusSm, border: `1px solid ${t.border}`, background: t.input, boxShadow: t.inset, color: t.text, fontSize: 13, outline: "none", fontFamily: "inherit", boxSizing: "border-box" as const };

  return (
    <div className="animate-fadeIn" style={{ position: "fixed" as const, inset: 0, background: "rgba(0,0,0,0.45)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 300 }} onClick={onClose}>
      <div className="animate-fadeUp" style={{ background: t.card, border: `1px solid ${t.border}`, borderRadius: t.radiusLg, padding: "28px 28px", width: 420, maxWidth: "90vw", boxShadow: t.shadowLg }} onClick={e => e.stopPropagation()}>
        <h3 style={{ margin: "0 0 20px", fontSize: 17, fontWeight: 700, color: t.text }}>Edit Profile</h3>

        <div style={{ display: "flex", flexDirection: "column" as const, gap: 14 }}>
          {([["name","Full Name"],["username","Username"],["email","Email"]] as const).map(([key, label]) => (
            <div key={key}>
              <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: t.textMuted, marginBottom: 5, textTransform: "uppercase" as const, letterSpacing: "0.04em" }}>{label}</label>
              <input value={form[key]} onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))} style={inputStyle}/>
            </div>
          ))}
          <div>
            <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: t.textMuted, marginBottom: 5, textTransform: "uppercase" as const, letterSpacing: "0.04em" }}>Position</label>
            <select value={form.position} onChange={e => setForm(f => ({ ...f, position: e.target.value }))} style={{ ...inputStyle }}>
              {POSITIONS.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
        </div>

        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", marginTop: 24 }}>
          <button onClick={onClose} style={{ padding: "8px 18px", borderRadius: t.radiusSm, border: `1px solid ${t.border}`, background: "transparent", color: t.textSub, fontSize: 13, fontWeight: 600, cursor: "pointer", fontFamily: "inherit" }}>Cancel</button>
          <button onClick={() => { onSave(form); onClose(); }} style={{ padding: "8px 18px", borderRadius: t.radiusSm, border: "none", background: t.primary, boxShadow: t.raisedSm, color: "#fff", fontSize: 13, fontWeight: 600, cursor: "pointer", fontFamily: "inherit" }}>Save Changes</button>
        </div>
      </div>
    </div>
  );
}

// ─── Main App ─────────────────────────────────────────────────────────────────
export default function App() {
  const [isDark, setIsDark]           = useState(false);
  const [isAuthenticated, setIsAuth]  = useState(false);
  const [user, setUser]               = useState<UserProfile>({ id: "", name: "", username: "", email: "", position: "Security Analyst", role: "analyst" });
  const [critical, setCritical]       = useState<number | null>(null);
  const [healthy, setHealthy]         = useState(false);
  const [tab, setTab]                 = useState<string>(() => reportIdFromHash() ? "LLI REPORTS" : "DASHBOARD");
  const [focusIncident, setFocusIncident] = useState<string | null>(null);
  const [toasts, setToasts]           = useState<Toast[]>([]);
  const [showProfile, setShowProfile] = useState(false);
  const [showEdit, setShowEdit]       = useState(false);
  const avatarRef                     = useRef<HTMLDivElement>(null);

  const t = getTheme(isDark);

  function showToast(msg: string, type = "success") {
    setToasts(prev => [...prev, { id: Date.now(), msg, type }]);
  }
  function removeToast(id: number) { setToasts(prev => prev.filter(x => x.id !== id)); }

  function handleLogin(u: UserProfile) {
    setUser(u);
    setIsAuth(true);
    showToast(`Welcome back, ${(u.name || u.username || "analyst").split(" ")[0]}!`);
  }

  function resetSession() {
    setIsAuth(false);
    setShowProfile(false);
    setTab(reportIdFromHash() ? "LLI REPORTS" : "DASHBOARD");
    setCritical(null);
    setHealthy(false);
  }

  function handleSignOut() {
    api.logout();
    clearReportHash();
    resetSession();
  }

  function openReport(id: string) { openReportHash(id); setTab("LLI REPORTS"); }
  function openIncident(id: string) { setFocusIncident(id); setTab("INCIDENTS"); }

  // The report hash only lives on the Reports tab; the incident preselect only on first entry to Incidents.
  useEffect(() => {
    if (!isAuthenticated) return;
    if (tab !== "LLI REPORTS") clearReportHash();
    if (tab !== "INCIDENTS") setFocusIncident(null);
  }, [tab, isAuthenticated]);

  // Any 401 from the API (token expired or revoked) lands here.
  useEffect(() => {
    api.setUnauthorizedHandler(() => { resetSession(); showToast("Session expired", "error"); });
    return () => api.setUnauthorizedHandler(null);
  }, []);

  function refreshCritical() {
    api.dashboard().then(d => setCritical(d.critical_open)).catch(() => setCritical(null));
  }

  // Nav badge (critical_open) and the "All systems live" pill (GET /health), refreshed on tab change.
  useEffect(() => {
    if (!isAuthenticated) return;
    refreshCritical();
    api.health().then(() => setHealthy(true)).catch(() => setHealthy(false));
  }, [isAuthenticated, tab]);

  if (!isAuthenticated) {
    return (
      <>
        <div style={{ width: "100%", height: "100vh", fontFamily: "'IBM Plex Sans', system-ui, sans-serif", backgroundColor: t.bg, backgroundImage: t.ambient, ["--focus" as string]: t.focus }}>
          <LoginPage t={t} isDark={isDark} setIsDark={setIsDark} onLogin={handleLogin}/>
        </div>
        <div style={{ position: "fixed", bottom: 24, right: 24, display: "flex", flexDirection: "column", gap: 10, zIndex: 200 }}>
          {toasts.map(toast => <ToastItem key={toast.id} toast={toast} t={t} onRemove={() => removeToast(toast.id)}/>)}
        </div>
      </>
    );
  }

  const initials = ((user.name || user.username || "?").split(" ").map(w => w[0]).join("").slice(0, 2)).toUpperCase();
  const pageProps = { t, showToast, isDark };

  return (
    <div style={{ width: "100%", height: "100vh", display: "flex", flexDirection: "column", backgroundColor: t.bg, backgroundImage: t.ambient, ["--focus" as string]: t.focus, fontFamily: "'IBM Plex Sans', system-ui, sans-serif", fontSize: 13, color: t.text, overflow: "hidden" }}>

      {/* ── Navigation bar ── */}
      <nav style={{ background: t.nav, borderBottom: `1px solid ${t.border}`, height: 56, display: "flex", alignItems: "center", padding: "0 20px", flexShrink: 0, boxShadow: t.shadow, zIndex: 10 }}>

        {/* Logo */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, paddingRight: 28, marginRight: 8 }}>
          <LogoMark t={t} size={32}/>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: t.text, lineHeight: 1.1 }}>Vantix</div>
            <div style={{ fontSize: 11, color: t.textMuted, fontWeight: 500 }}>FinTech Security Platform</div>
          </div>
        </div>

        {/* Tabs */}
        <div style={{ display: "flex", gap: 2, height: "100%", alignItems: "center" }}>
          {TABS.map(tb => (
            <button key={tb.id} onClick={() => setTab(tb.id)} style={{ display: "flex", alignItems: "center", gap: 7, height: "100%", padding: "0 16px", background: "none", border: "none", borderBottom: `2px solid ${tab === tb.id ? t.blue : "transparent"}`, color: tab === tb.id ? t.blue : t.textSub, fontWeight: tab === tb.id ? 600 : 500, fontSize: 13, cursor: "pointer", transition: "all 0.15s", fontFamily: "inherit" }}>
              <span style={{ opacity: tab === tb.id ? 1 : 0.6 }}>{tb.icon}</span>
              {tb.label}
            </button>
          ))}
        </div>

        {/* Right side */}
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 12 }}>
          {healthy && (
            <div style={{ display: "flex", alignItems: "center", gap: 6, background: t.greenDim, border: `1px solid ${t.greenBorder}`, borderRadius: 99, padding: "4px 12px" }}>
              <div className="live-dot" style={{ width: 6, height: 6, borderRadius: "50%", background: t.green }}/>
              <span style={{ fontSize: 12, color: t.green, fontWeight: 600 }}>All systems live</span>
            </div>
          )}

          {critical !== null && (
            <div style={{ display: "flex", alignItems: "center", gap: 6, background: t.redDim, border: `1px solid ${t.redBorder}`, borderRadius: 99, padding: "4px 12px", cursor: "pointer" }} onClick={() => setTab("INCIDENTS")}>
              <span style={{ fontSize: 12, color: t.red, fontWeight: 700 }}>{critical} critical</span>
            </div>
          )}

          {/* Avatar — profile trigger */}
          <div ref={avatarRef} style={{ position: "relative" as const }}>
            <div
              onClick={() => setShowProfile(v => !v)}
              title={`${user.name} — ${user.position}`}
              style={{ width: 34, height: 34, borderRadius: "50%", background: t.brandGrad, display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontWeight: 700, fontSize: 13, cursor: "pointer", userSelect: "none" as const, border: showProfile ? `2px solid ${t.focus}` : "2px solid transparent", transition: "border-color 0.15s" }}
            >
              {initials}
            </div>
            {showProfile && (
              <ProfileDropdown
                user={user} t={t} isDark={isDark} setIsDark={setIsDark}
                onEdit={() => setShowEdit(true)}
                onSignOut={handleSignOut}
                onClose={() => setShowProfile(false)}
              />
            )}
          </div>
        </div>
      </nav>

      {/* ── Page content ── */}
      <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {tab === "DASHBOARD"   && <DashboardPage  {...pageProps} onNavigate={setTab}/>}
        {tab === "INCIDENTS"   && <IncidentsPage  {...pageProps} role={user.role} onChanged={refreshCritical} initialId={focusIncident} onViewReport={openReport}/>}
        {tab === "LLI REPORTS" && <LLIReportsPage {...pageProps} onOpenIncident={openIncident}/>}
        {tab === "AI COPILOT"  && <AICopilotPage  {...pageProps}/>}
      </div>

      {/* ── Edit profile modal ── */}
      {showEdit && (
        <EditProfileModal
          user={user} t={t}
          onSave={u => { setUser(u); showToast("Profile updated"); }}
          onClose={() => setShowEdit(false)}
        />
      )}

      {/* ── Toast stack ── */}
      <div style={{ position: "fixed", bottom: 24, right: 24, display: "flex", flexDirection: "column", gap: 10, zIndex: 400 }}>
        {toasts.map(toast => <ToastItem key={toast.id} toast={toast} t={t} onRemove={() => removeToast(toast.id)}/>)}
      </div>
    </div>
  );
}
