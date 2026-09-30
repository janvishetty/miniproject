import { useState } from "react";
import type { Theme } from "./theme";
import { Icons } from "./ui";

const POSITIONS = [
  "Security Analyst",
  "Senior Analyst",
  "SOC Manager",
  "Threat Intelligence Lead",
  "Compliance Officer",
  "Platform Engineer",
  "CISO / CTO",
];

export type UserProfile = {
  name: string;
  username: string;
  email: string;
  position: string;
};

interface Props {
  t: Theme;
  isDark: boolean;
  setIsDark: (v: boolean) => void;
  onLogin: (user: UserProfile) => void;
}

export default function LoginPage({ t, isDark, setIsDark, onLogin }: Props) {
  const [form, setForm] = useState({ name: "", username: "", email: "", password: "", position: "Security Analyst" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [showPassword, setShowPassword] = useState(false);

  function validate() {
    const e: Record<string, string> = {};
    if (!form.name.trim())     e.name     = "Name is required";
    if (!form.username.trim()) e.username = "Username is required";
    if (!form.email.includes("@")) e.email = "Enter a valid email";
    if (form.password.length < 6)  e.password = "Password must be at least 6 characters";
    return e;
  }

  function handleSubmit(ev: React.FormEvent) {
    ev.preventDefault();
    const e = validate();
    if (Object.keys(e).length > 0) { setErrors(e); return; }
    onLogin({ name: form.name, username: form.username, email: form.email, position: form.position });
  }

  const field = (key: keyof typeof form, label: string, type = "text", placeholder = "") => (
    <div style={{ display: "flex", flexDirection: "column" as const, gap: 5 }}>
      <label style={{ fontSize: 13, fontWeight: 600, color: t.text }}>{label}</label>
      {key === "position" ? (
        <select
          value={form.position}
          onChange={e => setForm(f => ({ ...f, position: e.target.value }))}
          style={{ padding: "9px 12px", borderRadius: t.radiusSm, border: `1px solid ${errors[key] ? t.red : t.border}`, background: t.input, color: t.text, fontSize: 13, outline: "none", fontFamily: "inherit" }}
        >
          {POSITIONS.map(p => <option key={p} value={p}>{p}</option>)}
        </select>
      ) : (
        <div style={{ position: "relative" as const }}>
          <input
            type={key === "password" && !showPassword ? "password" : "text"}
            value={form[key]}
            onChange={e => { setForm(f => ({ ...f, [key]: e.target.value })); setErrors(er => ({ ...er, [key]: "" })); }}
            placeholder={placeholder}
            style={{ width: "100%", padding: "9px 12px", paddingRight: key === "password" ? 40 : 12, borderRadius: t.radiusSm, border: `1px solid ${errors[key] ? t.red : t.border}`, background: t.input, color: t.text, fontSize: 13, outline: "none", fontFamily: "inherit", boxSizing: "border-box" as const }}
          />
          {key === "password" && (
            <button type="button" onClick={() => setShowPassword(v => !v)} style={{ position: "absolute" as const, right: 10, top: "50%", transform: "translateY(-50%)", background: "none", border: "none", cursor: "pointer", color: t.textMuted, display: "flex", padding: 0 }}>
              {Icons.eye}
            </button>
          )}
        </div>
      )}
      {errors[key] && <span style={{ fontSize: 11, color: t.red }}>{errors[key]}</span>}
    </div>
  );

  return (
    <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column" as const, background: t.bg, fontFamily: "'IBM Plex Sans', system-ui, sans-serif" }}>

      {/* Minimal top bar */}
      <div style={{ height: 52, background: t.nav, borderBottom: `1px solid ${t.border}`, display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 24px", boxShadow: t.shadow }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ width: 30, height: 30, background: "linear-gradient(135deg, #2563eb, #1d4ed8)", borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
            </svg>
          </div>
          <span style={{ fontSize: 15, fontWeight: 700, color: t.text }}>Vantix</span>
        </div>
        <button onClick={() => setIsDark(!isDark)} style={{ width: 32, height: 32, borderRadius: 8, border: `1px solid ${t.border}`, background: t.badge, color: t.textSub, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}>
          {isDark ? Icons.sun : Icons.moon}
        </button>
      </div>

      {/* Centered form */}
      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
        <div style={{ width: "100%", maxWidth: 420 }} className="animate-fadeUp">
          <div style={{ marginBottom: 28, textAlign: "center" as const }}>
            <h1 style={{ margin: "0 0 6px", fontSize: 22, fontWeight: 700, color: t.text }}>Sign in to Vantix</h1>
            <p style={{ margin: 0, fontSize: 14, color: t.textSub }}>FinTech Security Operations Platform</p>
          </div>

          <div style={{ background: t.card, border: `1px solid ${t.border}`, borderRadius: t.radiusLg, padding: "28px 28px", boxShadow: t.shadowMd }}>
            <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column" as const, gap: 16 }}>
              {field("name",     "Full Name",  "text", "e.g. Kim Brennan")}
              {field("username", "Username",   "text", "e.g. kbrennan")}
              {field("email",    "Email",      "email","e.g. k.brennan@vantix.io")}
              {field("password", "Password",   "password", "Min. 6 characters")}
              {field("position", "Position")}

              <button
                type="submit"
                style={{ marginTop: 8, width: "100%", padding: "11px 0", background: "#2563eb", color: "#fff", border: "none", borderRadius: t.radiusSm, fontSize: 14, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", transition: "background 0.15s" }}
                onMouseEnter={e => (e.currentTarget.style.background = "#1d4ed8")}
                onMouseLeave={e => (e.currentTarget.style.background = "#2563eb")}
              >
                Sign In
              </button>
            </form>
          </div>

          <p style={{ textAlign: "center" as const, marginTop: 16, fontSize: 12, color: t.textMuted }}>
            Demo: fill any values (password ≥ 6 chars) to enter
          </p>
        </div>
      </div>
    </div>
  );
}
