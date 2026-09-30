import { useState, useRef, useEffect } from "react";
import type { Theme } from "./theme";
import { Card, Btn, Icons } from "./ui";

type Msg = { role: "user" | "ai"; text: string; ts: string; thinking?: boolean };

const CHIPS = [
  "Summarize today's critical incidents",
  "What caused INC-2026-8848?",
  "Generate a PCI-DSS remediation plan",
  "Explain the SWIFT gateway risk score",
  "What is the FIN-APT-7 attack pattern?",
  "Draft a regulatory disclosure report",
];

const ANSWERS: Record<string, string> = {
  default: `**Security Posture Summary — Today**

Here's what's happening across your FinTech platform right now:

**🔴 Critical:** INC-2026-8848 requires immediate action. An attacker (185.226.101.5) is sweeping SWIFT transaction IDs using an unauthenticated API endpoint. Match confidence: 94% for FIN-APT-7 tactic.

**🟡 Elevated:** Platform risk index is at 67/100. The SWIFT gateway node is the primary contributor (+12 points).

**🟢 Good news:** GDPR compliance is at 100%. PCI-DSS is at 91%. Mean response time is 4m 12s — within your 5-minute target.

**Recommended next step:** Investigate and contain INC-2026-8848 first. I've pre-loaded the evidence files and timeline in the Incidents tab.

*This analysis was produced by finbert-vantix-v2.1 using rule-based correlation + ML anomaly scoring. All outputs are audit-logged.*`,

  "Summarize today's critical incidents": `**Today's Critical Incidents (2 found)**

**INC-2026-8848 — CRITICAL · Still Open**
High-velocity SWIFT transaction sweep. Attacker IP 185.226.101.5 has sent 42,000+ requests/min. SLA expires in 4 seconds. Action: Block IP at WAF immediately.

**INC-2026-8838 — CRITICAL · Resolved ✓**
Brute-force on Treasury Ledger admin portal from 91.108.4.77. Blocked after 1,847 attempts. Analyst K. Brennan resolved at 10:44. No data exfiltration detected.

**Your MTTR for resolved incidents today: 4m 12s** (target: under 5 min ✓)`,

  "What caused INC-2026-8848?": `**Root Cause — INC-2026-8848**

**Attack Chain (step by step):**
1. Attacker scanned SWIFT gateway at 12:03:55 UTC
2. Found unauthenticated \`/v2/transfers\` endpoint
3. Sent 42,000 requests/min — 300× normal traffic
4. ML anomaly model scored it 0.97 (critical threshold: 0.90)
5. Correlation rule R-104 auto-created this incident

**Why it happened:**
- Patch SWIFT-SEC-2026-041 was not yet applied
- WAF update was delayed during maintenance window
- No geographic IP restriction was set on the SWIFT API

**Fix it in 3 steps:**
1. Block 185.226.0.0/16 at the WAF right now
2. Apply the pending SWIFT security patch (NODE-SWIFT-01)
3. Set rate limit: max 200 requests/min per token`,

  "Generate a PCI-DSS remediation plan": `**PCI-DSS Remediation Plan — 2 Open Findings**

**Finding F-001 · Control 8.3.6 · Risk: HIGH**
*Problem:* MFA not enforced on 2 legacy admin consoles.
*Fix:* Deploy TOTP via Okta to admin-console-legacy-01 and -02. Estimated time: 4 hours.
*Due:* September 1, 2026 · Owner: Infra Team

**Finding F-003 · SWIFT CSP 2.2 · Risk: HIGH**
*Problem:* Mandatory security update pending on SWIFT gateway.
*Fix:* Schedule maintenance window Aug 24, 02:00–04:00 UTC. Apply patch SWIFT-SEC-2026-041. Run CSP verification suite after.
*Due:* August 28, 2026 · Owner: NetOps

**Total effort: ~6 hours** · Compliance deadline: Sep 1 · Risk if missed: QSA escalation`,
};

function typeText(text: string, onChunk: (t: string) => void, onDone: () => void) {
  let i = 0;
  const iv = setInterval(() => {
    if (i >= text.length) { clearInterval(iv); onDone(); return; }
    i = Math.min(text.length, i + Math.floor(Math.random() * 8) + 4);
    onChunk(text.slice(0, i));
  }, 20);
  return () => clearInterval(iv);
}

function renderText(text: string, t: Theme) {
  return text.split("\n").map((line, i) => {
    if (line.startsWith("**") && line.endsWith("**") && !line.slice(2,-2).includes("**")) {
      return <div key={i} style={{ fontWeight: 700, color: t.text, fontSize: 14, marginTop: i > 0 ? 14 : 0, marginBottom: 4 }}>{line.replace(/\*\*/g, "")}</div>;
    }
    if (line === "") return <div key={i} style={{ height: 6 }}/>;
    const parts = line.split(/\*\*(.*?)\*\*/g);
    const base = line.startsWith("1.") || line.startsWith("2.") || line.startsWith("3.") || line.startsWith("4.") || line.startsWith("5.");
    return (
      <div key={i} style={{ fontSize: 13, color: t.textSub, lineHeight: 1.7, paddingLeft: base ? 0 : line.startsWith("- ") || line.startsWith("*") ? 0 : 0 }}>
        {parts.map((p, j) => j % 2 === 1 ? <strong key={j} style={{ color: t.text, fontWeight: 600 }}>{p}</strong> : p)}
      </div>
    );
  });
}

interface Props { t: Theme; }

export default function AICopilotPage({ t }: Props) {
  const [msgs, setMsgs] = useState<Msg[]>([{ role: "ai", text: ANSWERS.default, ts: "12:09:01" }]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);

  function send(text: string) {
    if (!text.trim() || busy) return;
    const ts = new Date().toTimeString().slice(0, 8);
    setMsgs(prev => [...prev, { role: "user", text, ts }]);
    setInput("");
    setBusy(true);

    const reply = ANSWERS[text] || ANSWERS.default;
    setTimeout(() => {
      setMsgs(prev => [...prev, { role: "ai", text: "", ts, thinking: true }]);
      setTimeout(() => {
        setMsgs(prev => prev.map((m, i) => i === prev.length - 1 ? { ...m, thinking: false } : m));
        typeText(reply,
          chunk => setMsgs(prev => prev.map((m, i) => i === prev.length - 1 ? { ...m, text: chunk } : m)),
          () => setBusy(false)
        );
      }, 700);
    }, 200);
  }

  return (
    <div style={{ display: "flex", flex: 1, minHeight: 0, gap: 0, animation: "fadeUp 0.25s ease-out" }}>

      {/* Sidebar */}
      <div style={{ width: 260, borderRight: `1px solid ${t.border}`, background: t.card, display: "flex", flexDirection: "column", flexShrink: 0 }}>
        <div style={{ padding: "20px 18px", borderBottom: `1px solid ${t.border}` }}>
          <div style={{ display: "flex", align: "center", gap: 10, marginBottom: 6 }}>
            <div style={{ width: 36, height: 36, borderRadius: 10, background: t.blueDim, display: "flex", alignItems: "center", justifyContent: "center", color: t.blue, flexShrink: 0 }}>{Icons.bot}</div>
            <div>
              <div style={{ fontSize: 14, fontWeight: 700, color: t.text }}>AI Copilot</div>
              <div style={{ fontSize: 11, color: t.green, fontWeight: 600 }}>● Online</div>
            </div>
          </div>
          <p style={{ margin: "10px 0 0", fontSize: 12, color: t.textSub, lineHeight: 1.5 }}>Ask me anything about incidents, compliance, or threat analysis. I'll explain my reasoning.</p>
        </div>

        {/* Suggested prompts */}
        <div style={{ padding: "14px 12px", flex: 1, overflowY: "auto" }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase" as const, letterSpacing: "0.06em", marginBottom: 8, paddingLeft: 4 }}>Try asking…</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {CHIPS.map(c => (
              <button key={c} onClick={() => send(c)} disabled={busy} style={{ textAlign: "left" as const, background: "none", border: `1px solid ${t.border}`, borderRadius: t.radiusSm, padding: "9px 12px", fontSize: 12, color: t.textSub, cursor: busy ? "default" : "pointer", transition: "all 0.15s", lineHeight: 1.4 }}
                onMouseEnter={e => { if (!busy) { e.currentTarget.style.background = t.blueDim; e.currentTarget.style.borderColor = t.blue; e.currentTarget.style.color = t.blue; } }}
                onMouseLeave={e => { e.currentTarget.style.background = "none"; e.currentTarget.style.borderColor = t.border; e.currentTarget.style.color = t.textSub; }}>
                {c}
              </button>
            ))}
          </div>
        </div>

        {/* Model info */}
        <div style={{ padding: "12px 16px", borderTop: `1px solid ${t.border}`, background: t.bg }}>
          {[["Model", "finbert-vantix-v2.1"], ["Method", "Rule + ML hybrid"], ["Audit log", "Enabled"]].map(([k, v]) => (
            <div key={k} style={{ display: "flex", justifyContent: "space-between", padding: "3px 0" }}>
              <span style={{ fontSize: 11, color: t.textMuted }}>{k}</span>
              <span style={{ fontSize: 11, color: t.textSub, fontWeight: 500 }}>{v}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Chat area */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>

        {/* Messages */}
        <div style={{ flex: 1, overflowY: "auto", padding: "20px 24px", display: "flex", flexDirection: "column", gap: 16 }}>
          {msgs.map((msg, i) => (
            <div key={i} className={i === msgs.length - 1 ? "animate-slideIn" : ""} style={{ display: "flex", gap: 12, justifyContent: msg.role === "user" ? "flex-end" : "flex-start" }}>
              {msg.role === "ai" && (
                <div style={{ width: 32, height: 32, borderRadius: 9, background: t.blueDim, border: `1px solid ${t.blueBorder}`, display: "flex", alignItems: "center", justifyContent: "center", color: t.blue, flexShrink: 0, marginTop: 2 }}>{Icons.bot}</div>
              )}
              <div style={{ maxWidth: "70%", background: msg.role === "user" ? t.blue : t.card, border: `1px solid ${msg.role === "user" ? t.blue : t.border}`, borderRadius: msg.role === "user" ? "14px 14px 4px 14px" : "4px 14px 14px 14px", padding: "12px 16px", boxShadow: t.shadow }}>
                {msg.thinking ? (
                  <div style={{ display: "flex", gap: 5, alignItems: "center", padding: "2px 0" }}>
                    {[0,1,2].map(j => <div key={j} style={{ width: 7, height: 7, borderRadius: "50%", background: t.blue, animation: `pulse 1.2s ease-in-out ${j*0.2}s infinite` }}/>)}
                    <span style={{ fontSize: 12, color: t.textMuted, marginLeft: 4 }}>Analyzing…</span>
                  </div>
                ) : (
                  <>
                    <div style={{ color: msg.role === "user" ? "#fff" : undefined }}>
                      {msg.role === "user"
                        ? <span style={{ fontSize: 13, lineHeight: 1.5 }}>{msg.text}</span>
                        : renderText(msg.text, t)}
                    </div>
                    <div style={{ fontSize: 10, color: msg.role === "user" ? "rgba(255,255,255,0.6)" : t.textMuted, marginTop: 6, textAlign: "right" as const }}>{msg.ts}</div>
                  </>
                )}
              </div>
            </div>
          ))}
          <div ref={bottomRef}/>
        </div>

        {/* Input bar */}
        <div style={{ padding: "14px 20px", borderTop: `1px solid ${t.border}`, background: t.card }}>
          <div style={{ display: "flex", gap: 10, alignItems: "flex-end", background: t.bg, border: `1px solid ${t.border}`, borderRadius: t.radius, padding: "8px 8px 8px 16px" }}>
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }}
              placeholder="Ask the AI Copilot anything about your security environment…"
              rows={1}
              style={{ flex: 1, background: "none", border: "none", outline: "none", resize: "none", fontSize: 13, color: t.text, lineHeight: 1.5, maxHeight: 120, overflowY: "auto" }}
            />
            <button
              onClick={() => send(input)}
              disabled={busy || !input.trim()}
              style={{ width: 36, height: 36, borderRadius: 9, background: input.trim() && !busy ? t.blue : t.border, border: "none", color: input.trim() && !busy ? "#fff" : t.textMuted, display: "flex", alignItems: "center", justifyContent: "center", cursor: input.trim() && !busy ? "pointer" : "default", transition: "all 0.15s", flexShrink: 0 }}>
              {busy
                ? <div className="spinner" style={{ width: 14, height: 14, border: `2px solid ${t.textMuted}`, borderTopColor: t.blue, borderRadius: "50%" }}/>
                : Icons.send}
            </button>
          </div>
          <div style={{ fontSize: 11, color: t.textMuted, marginTop: 7, textAlign: "center" as const }}>
            Enter to send · Shift+Enter for new line · All queries audit-logged for SR 11-7 compliance
          </div>
        </div>
      </div>
    </div>
  );
}
