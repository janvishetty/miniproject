import { useState } from "react";
import type { Theme } from "./theme";
import { Icons, LogoMark } from "./ui";
import * as api from "./api";

export type UserProfile = {
  id: string;
  name: string;
  username: string;
  email: string;
  position: string;
  role: string;
};

interface Props {
  t: Theme;
  isDark: boolean;
  setIsDark: (v: boolean) => void;
  onLogin: (user: UserProfile) => void;
}

export default function LoginPage({ t, isDark, setIsDark, onLogin }: Props) {
  const [form, setForm] = useState({ email: "", password: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);

  function validate() {
    const e: Record<string, string> = {};
    if (!form.email.includes("@")) e.email = "Enter a valid email";
    if (form.password.length < 8)  e.password = "Password must be at least 8 characters";
    return e;
  }

  async function handleSubmit(ev: React.FormEvent) {
    ev.preventDefault();
    const e = validate();
    if (Object.keys(e).length > 0) { setErrors(e); return; }
    setBusy(true);
    try {
      const p = await api.login(form.email.trim(), form.password);
      onLogin({ id: p.id, name: p.name ?? "", username: p.username ?? "", email: p.email ?? form.email.trim(),
                position: p.position ?? "", role: p.role });
    } catch (err) {
      const apiErr = err instanceof api.ApiError ? err : null;
      setErrors({ form: apiErr?.status === 429 ? "Too many attempts, wait a minute"
                      : apiErr ? apiErr.message : "Something went wrong. Try again." });
      setBusy(false);
    }
  }

  const MAIL = <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M22 7l-10 6L2 7"/></svg>;
  const LOCK = <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg>;

  const field = (key: keyof typeof form, label: string, type = "text", placeholder = "") => {
    const id = `login-${key}`;
    return (
      <div style={{ display: "flex", flexDirection: "column" as const, gap: 10 }}>
        <label htmlFor={id} style={{ fontSize: 13, fontWeight: 600, color: t.textSub }}>{label}</label>
        <div style={{ position: "relative" as const }}>
          <span aria-hidden="true" style={{ position: "absolute" as const, left: 16, top: "50%", transform: "translateY(-50%)", color: t.textMuted, display: "flex", pointerEvents: "none" as const }}>{key === "password" ? LOCK : MAIL}</span>
          <input
            id={id}
            className="login-input"
            type={key === "password" && !showPassword ? "password" : "text"}
            value={form[key]}
            onChange={e => { setForm(f => ({ ...f, [key]: e.target.value })); setErrors(er => ({ ...er, [key]: "", form: "" })); }}
            placeholder={placeholder}
            style={{ width: "100%", height: 54, padding: "0 12px 0 48px", paddingRight: key === "password" ? 58 : 12, borderRadius: 16, border: `1px solid ${errors[key] ? t.red : t.border}`, background: t.input, boxShadow: t.inset, color: t.text, fontSize: 15, outline: "none", fontFamily: "inherit", boxSizing: "border-box" as const }}
          />
          {key === "password" && (
            <button type="button" aria-label={showPassword ? "Hide password" : "Show password"} onClick={() => setShowPassword(v => !v)} style={{ position: "absolute" as const, right: 8, top: "50%", transform: "translateY(-50%)", width: 38, height: 38, borderRadius: 10, border: `1px solid ${t.btnBorder}`, background: t.btn, boxShadow: t.raisedSm, cursor: "pointer", color: t.textSub, display: "flex", alignItems: "center", justifyContent: "center", padding: 0 }}>
              {Icons.eye}
            </button>
          )}
        </div>
        {errors[key] && <span style={{ fontSize: 12, color: t.red }}>{errors[key]}</span>}
      </div>
    );
  };

  // Hero geometry is in % of a 480px square (rings 440 / 320 / 220, disc 150), so it scales down on narrow desktops and short screens.
  const ring = (px: number, extra: React.CSSProperties): React.CSSProperties =>
    ({ position: "absolute", inset: `${((480 - px) / 480) * 50}%`, borderRadius: "50%", ...extra });
  const pill = (label: string, dot: string, pos: React.CSSProperties) => (
    <div data-glass="" style={{ position: "absolute", display: "flex", alignItems: "center", gap: 8, height: 40, padding: "0 16px", borderRadius: 99, background: t.glass, border: `1px solid ${t.glassBorder}`, backdropFilter: t.blur, WebkitBackdropFilter: t.blur, boxShadow: t.shadow, fontSize: 13, fontWeight: 700, color: t.text, whiteSpace: "nowrap", ...pos }}>
      <span style={{ width: 8, height: 8, borderRadius: "50%", background: dot, flexShrink: 0 }}/>{label}
    </div>
  );

  return (
    <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column" as const, fontFamily: "'IBM Plex Sans', system-ui, sans-serif", ["--ph" as string]: t.textMuted }}>

      {/* Transparent top bar so the glows reach the top edge */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "28px clamp(16px, 4.2vw, 60px) 0" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <LogoMark t={t} size={42}/>
          <span style={{ fontSize: 20, fontWeight: 700, color: t.text }}>Vantix</span>
        </div>
        <button onClick={() => setIsDark(!isDark)} aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"} style={{ width: 44, height: 44, borderRadius: 12, border: `1px solid ${t.btnBorder}`, background: t.btn, boxShadow: t.raisedSm, color: t.textSub, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}>
          {isDark ? Icons.sun : Icons.moon}
        </button>
      </div>

      {/* Hero (>= 960px, CSS-only) + form */}
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto", display: "flex", alignItems: "center", gap: "clamp(24px, 5.5vw, 80px)", padding: "16px clamp(16px, 8.3vw, 120px) 24px clamp(16px, 4.2vw, 60px)" }}>
        <div className="login-hero">
          <div style={{ position: "relative", width: "min(480px, 100%, calc(100vh - 330px))", aspectRatio: "1 / 1" }}>
            <div aria-hidden="true" style={{ position: "absolute", inset: 0 }}>
              <div style={ring(440, { border: `1px solid ${t.heroRing}`, boxShadow: `0 0 48px ${t.heroGlow}, inset 0 0 48px ${t.heroGlow}` })}/>
              <div className="hero-spin-rev" style={ring(320, { border: `1px dashed ${t.heroDash}` })}/>
              <div className="hero-spin" style={ring(220, { background: t.heroConic, WebkitMask: "radial-gradient(farthest-side, transparent calc(100% - 7px), #000 calc(100% - 7px))", mask: "radial-gradient(farthest-side, transparent calc(100% - 7px), #000 calc(100% - 7px))" })}/>
              <div style={{ ...ring(150, { background: t.bg, boxShadow: t.raised }), display: "flex", alignItems: "center", justifyContent: "center" }}>
                <svg style={{ width: "48%", height: "48%" }} viewBox="0 0 24 24" fill="none" stroke={t.blue} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
              </div>
            </div>
            {pill("Isolation Forest + SHAP", t.purple, { top: "9%", right: "-1%" })}
            {pill("9 detection rules", t.cyan, { top: "43%", left: "-5%" })}
            {pill("Fact-checked AI reports", t.green, { bottom: "11%", right: "1%" })}
          </div>
          <div style={{ maxWidth: 540, textAlign: "center" as const }}>
            <h2 style={{ margin: "0 0 12px", fontSize: 28, lineHeight: 1.25, fontWeight: 700, color: t.text, textWrap: "balance" }}>Explainable incident investigation for FinTech security teams</h2>
            <p style={{ margin: "0 auto", maxWidth: 520, fontSize: 15, lineHeight: 1.6, color: t.textSub, textWrap: "balance" }}>Hybrid ML and rules detection, fact-checked AI reports, and analysts always in control.</p>
          </div>
        </div>

        <div style={{ width: "100%", maxWidth: 440, flex: "0 1 440px", margin: "0 auto" }} className="animate-fadeUp">
          <div data-glass="" style={{ background: t.glass, border: `1px solid ${t.glassBorder}`, backdropFilter: t.blur, WebkitBackdropFilter: t.blur, borderRadius: 28, padding: "40px 40px 34px", boxShadow: t.shadowMd }}>
            <div style={{ marginBottom: 28, textAlign: "center" as const }}>
              <h1 style={{ margin: "0 0 10px", fontSize: 30, fontWeight: 700, color: t.text }}>Sign in to Vantix</h1>
              <p style={{ margin: 0, fontSize: 14, color: t.textSub }}>FinTech Security Operations Platform</p>
            </div>
            <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column" as const, gap: 20 }}>
              {field("email",    "Email",      "email","e.g. k.brennan@vantix.io")}
              {field("password", "Password",   "password", "Min. 8 characters")}
              {errors.form && <span style={{ fontSize: 12, color: t.red }}>{errors.form}</span>}

              <button
                type="submit"
                disabled={busy}
                style={{ opacity: busy ? 0.7 : 1, marginTop: 4, width: "100%", height: 56, background: t.primary, boxShadow: t.primaryShadow, color: "#fff", border: "none", borderRadius: 14, fontSize: 16, fontWeight: 700, cursor: "pointer", fontFamily: "inherit", transition: "background 0.15s" }}
                onMouseEnter={e => (e.currentTarget.style.background = t.primaryHover)}
                onMouseLeave={e => (e.currentTarget.style.background = t.primary)}
              >
                {busy ? "Signing in..." : "Sign In"}
              </button>
            </form>
            <p style={{ textAlign: "center" as const, margin: "22px 0 0", fontSize: 13, color: t.textMuted }}>
              Accounts are created by an administrator for now
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
