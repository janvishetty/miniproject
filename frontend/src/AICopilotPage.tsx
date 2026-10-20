import { useState, useRef, useEffect } from "react";
import type { Theme } from "./theme";
import { Btn, Icons } from "./ui";
import * as api from "./api";

type Retry = { welcome: true } | { question: string };
type Msg = { id: number; role: "user" | "ai"; text: string; ts: string; thinking?: boolean; retry?: Retry };

const CHIPS = [
  "Summarize the critical incidents",
  "What caused INC-2026-0081?",
  "Which incidents are account takeover?",
  "What containment steps do you recommend for INC-2026-0081?",
  "Show the highest-risk incidents",
];

function now() { return new Date().toTimeString().slice(0, 8); }

function renderText(text: string, t: Theme) {
  return text.split("\n").map((line, i) => {
    if (line.startsWith("**") && line.endsWith("**") && !line.slice(2,-2).includes("**")) {
      return <div key={i} style={{ fontWeight: 700, color: t.text, fontSize: 14, marginTop: i > 0 ? 14 : 0, marginBottom: 4 }}>{line.replace(/\*\*/g, "")}</div>;
    }
    if (line === "") return <div key={i} style={{ height: 6 }}/>;
    const bullet = line.match(/^\s*[-*]\s+(.*)$/);
    if (bullet) {
      return (
        <div key={i} style={{ display: "flex", gap: 8, fontSize: 13, color: t.textSub, lineHeight: 1.7, paddingLeft: 4 }}>
          <span style={{ color: t.link, flexShrink: 0 }}>•</span>
          <span style={{ flex: 1, minWidth: 0 }}>
            {bullet[1].split(/\*\*(.*?)\*\*/g).map((p, j) => j % 2 === 1 ? <strong key={j} style={{ color: t.text, fontWeight: 600 }}>{p}</strong> : p)}
          </span>
        </div>
      );
    }
    const parts = line.split(/\*\*(.*?)\*\*/g);
    return (
      <div key={i} style={{ fontSize: 13, color: t.textSub, lineHeight: 1.7 }}>
        {parts.map((p, j) => j % 2 === 1 ? <strong key={j} style={{ color: t.text, fontWeight: 600 }}>{p}</strong> : p)}
      </div>
    );
  });
}

interface Props { t: Theme; }

export default function AICopilotPage({ t }: Props) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [inputFocused, setInputFocused] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const nextId = useRef(1);
  const welcomed = useRef(false);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);

  function update(id: number, patch: Partial<Msg>) {
    setMsgs(prev => prev.map(m => m.id === id ? { ...m, ...patch } : m));
  }

  // Turns an API failure into the text (and Retry button) shown in the chat bubble.
  function failure(err: unknown, retry: Retry): Partial<Msg> {
    const e = err instanceof api.ApiError ? err : null;
    if (e?.status === 503) return { thinking: false, text: "AI service unavailable. Start Ollama.", retry };
    if (e?.status === 429) return { thinking: false, text: e.message };
    if (e && (e.status === 0 || e.status === 504)) return { thinking: false, text: e.message, retry };
    return { thinking: false, text: e ? e.message : "Something went wrong. Try again." };
  }

  function loadWelcome(id: number) {
    update(id, { thinking: true, text: "", retry: undefined });
    api.welcome()
      .then(res => update(id, { thinking: false, text: res.answer ?? "", ts: now() }))
      .catch(err => update(id, failure(err, { welcome: true })));
  }

  // Opening message: GET /copilot/welcome (built from the data; no Ollama needed).
  useEffect(() => {
    if (welcomed.current) return;
    welcomed.current = true;
    const id = nextId.current++;
    setMsgs([{ id, role: "ai", text: "", ts: now(), thinking: true }]);
    loadWelcome(id);
  }, []);

  function ask(question: string, aiId: number) {
    setBusy(true);
    api.copilot(question)
      .then(res => update(aiId, { thinking: false, text: res.answer ?? "", retry: undefined, ts: now() }))
      .catch(err => update(aiId, failure(err, { question })))
      .finally(() => setBusy(false));
  }

  function send(text: string) {
    const question = text.trim();
    if (!question || busy) return;
    const aiId = nextId.current + 1;
    setMsgs(prev => [...prev,
      { id: nextId.current, role: "user", text: question, ts: now() },
      { id: aiId, role: "ai", text: "", ts: now(), thinking: true }]);
    nextId.current += 2;
    setInput("");
    ask(question, aiId);
  }

  function retry(msg: Msg) {
    if (!msg.retry || busy) return;
    if ("welcome" in msg.retry) { loadWelcome(msg.id); return; }
    update(msg.id, { thinking: true, text: "", retry: undefined });
    ask(msg.retry.question, msg.id);
  }

  const botAvatar = (size: number, glow = false) => (
    <div style={{ width: size, height: size, borderRadius: "50%", padding: Math.max(2, Math.round(size / 28)), background: t.accentGrad, boxShadow: glow ? `0 0 28px ${t.link}59` : undefined, flexShrink: 0 }}>
      <div style={{ width: "100%", height: "100%", borderRadius: "50%", background: t.bg, boxShadow: glow ? t.raised : t.raisedSm, display: "flex", alignItems: "center", justifyContent: "center", color: t.link }}>
        <span style={{ display: "flex", transform: `scale(${(size / 100) * 2.2})` }}>{Icons.bot}</span>
      </div>
    </div>
  );

  return (
    <div style={{ display: "flex", flex: 1, minHeight: 0, gap: 24, padding: "20px 24px", animation: "fadeUp 0.25s ease-out" }}>

      {/* Side panel (glass) */}
      <div data-glass="" style={{ width: 340, background: t.glass, border: `1px solid ${t.glassBorder}`, backdropFilter: t.blur, WebkitBackdropFilter: t.blur, borderRadius: 20, boxShadow: t.shadow, overflow: "hidden", display: "flex", flexDirection: "column", flexShrink: 0 }}>
        <div style={{ padding: "28px 24px 16px", textAlign: "center" as const }}>
          <div style={{ display: "flex", justifyContent: "center", marginBottom: 14 }}>{botAvatar(100, true)}</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: t.text }}>AI Copilot</div>
          <div style={{ display: "inline-block", margin: "8px 0 12px", background: t.greenDim, border: `1px solid ${t.greenBorder}`, borderRadius: 99, padding: "2px 12px", fontSize: 11, color: t.green, fontWeight: 600 }}>● Online</div>
          <p style={{ margin: 0, fontSize: 13, color: t.textSub, lineHeight: 1.6 }}>Ask me about incidents, users, IPs, transactions and attack types. I'll explain my reasoning.</p>
        </div>

        {/* Suggested prompts */}
        <div style={{ padding: "8px 16px 14px", flex: 1, overflowY: "auto" }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase" as const, letterSpacing: "0.06em", marginBottom: 10, paddingLeft: 4 }}>Try asking…</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {CHIPS.map(c => (
              <button key={c} onClick={() => send(c)} disabled={busy} style={{ textAlign: "left" as const, background: t.btn, border: `1px solid ${t.btnBorder}`, boxShadow: t.raisedSm, borderRadius: 14, padding: "11px 14px", fontSize: 13, color: t.textSub, cursor: busy ? "default" : "pointer", transition: "all 0.15s", lineHeight: 1.4 }}
                onMouseEnter={e => { if (!busy) { e.currentTarget.style.background = t.cardHover; e.currentTarget.style.color = t.link; } }}
                onMouseLeave={e => { e.currentTarget.style.background = t.btn; e.currentTarget.style.color = t.textSub; }}>
                {c}
              </button>
            ))}
          </div>
        </div>

        {/* Model info (inset) */}
        <div style={{ margin: "0 16px 16px", padding: "14px 16px", background: t.input, boxShadow: t.inset, borderRadius: 16 }}>
          {[["Model", "Isolation Forest + SHAP · llama3.2:3b (local)"], ["Method", "Rule + ML hybrid"], ["Audit log", "Enabled"]].map(([k, v]) => (
            <div key={k} style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, padding: "4px 0" }}>
              <span style={{ fontSize: 12, color: t.textMuted, flexShrink: 0 }}>{k}</span>
              <span style={{ fontSize: 12, color: t.text, fontWeight: 600, textAlign: "right" as const }}>{v}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Chat area */}
      <div data-glass="" style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, background: t.glass, border: `1px solid ${t.glassBorder}`, backdropFilter: t.blur, WebkitBackdropFilter: t.blur, borderRadius: 20, boxShadow: t.shadow, overflow: "hidden" }}>

        {/* Messages */}
        <div style={{ flex: 1, overflowY: "auto", padding: "24px", display: "flex", flexDirection: "column", gap: 18 }}>
          {msgs.map((msg, i) => (
            <div key={msg.id} className={i === msgs.length - 1 ? "animate-slideIn" : ""} style={{ display: "flex", gap: 12, justifyContent: msg.role === "user" ? "flex-end" : "flex-start" }}>
              {msg.role === "ai" && (
                <div style={{ marginTop: 2 }}>{botAvatar(38)}</div>
              )}
              <div style={{ maxWidth: "70%", background: msg.role === "user" ? t.primary : t.glass, border: `1px solid ${msg.role === "user" ? t.primary : t.glassBorder}`, borderRadius: msg.role === "user" ? "18px 18px 6px 18px" : "6px 18px 18px 18px", padding: "12px 16px", boxShadow: msg.role === "user" ? t.primaryShadow : t.shadow }}>
                {msg.thinking ? (
                  <div style={{ display: "flex", gap: 5, alignItems: "center", padding: "2px 0" }}>
                    {[0,1,2].map(j => <div key={j} style={{ width: 7, height: 7, borderRadius: "50%", background: t.link, animation: `bounce 1.2s ease-in-out ${j*0.15}s infinite` }}/>)}
                    <span style={{ fontSize: 12, color: t.textMuted, marginLeft: 4 }}>Analyzing…</span>
                  </div>
                ) : (
                  <>
                    <div style={{ color: msg.role === "user" ? "#fff" : undefined }}>
                      {msg.role === "user"
                        ? <span style={{ fontSize: 13, lineHeight: 1.5 }}>{msg.text}</span>
                        : renderText(msg.text, t)}
                      {msg.retry && (
                        <div style={{ marginTop: 10 }}>
                          <Btn t={t} variant="ghost" size="sm" disabled={busy} onClick={() => retry(msg)}>Retry</Btn>
                        </div>
                      )}
                    </div>
                    <div style={{ fontSize: 10, color: msg.role === "user" ? "rgba(255,255,255,0.9)" : t.textMuted, marginTop: 6, textAlign: "right" as const }}>{msg.ts}</div>
                  </>
                )}
              </div>
            </div>
          ))}
          <div ref={bottomRef}/>
        </div>

        {/* Input bar */}
        <div style={{ padding: "14px 24px 18px" }}>
          <div style={{ display: "flex", gap: 10, alignItems: "flex-end", background: t.input, boxShadow: t.inset, border: `1px solid ${t.border}`, borderRadius: 18, padding: "8px 8px 8px 18px", outline: inputFocused ? `2px solid ${t.focus}` : "none", outlineOffset: 2 }}>
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              onFocus={() => setInputFocused(true)}
              onBlur={() => setInputFocused(false)}
              onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }}
              placeholder="Ask the AI Copilot anything about your security environment…"
              rows={1}
              maxLength={500}
              style={{ flex: 1, background: "none", border: "none", outline: "none", resize: "none", fontSize: 13, color: t.text, lineHeight: 1.5, maxHeight: 120, overflowY: "auto" }}
            />
            <button
              onClick={() => send(input)}
              disabled={busy || !input.trim()}
              style={{ width: 38, height: 38, borderRadius: "50%", boxShadow: input.trim() && !busy ? t.raisedSm : "none", background: input.trim() && !busy ? t.primary : t.border, border: "none", color: input.trim() && !busy ? "#fff" : t.textMuted, display: "flex", alignItems: "center", justifyContent: "center", cursor: input.trim() && !busy ? "pointer" : "default", transition: "all 0.15s", flexShrink: 0 }}>
              {busy
                ? <div className="spinner" style={{ width: 14, height: 14, border: `2px solid ${t.textMuted}`, borderTopColor: t.link, borderRadius: "50%" }}/>
                : Icons.send}
            </button>
          </div>
          <div style={{ fontSize: 11, color: t.textMuted, marginTop: 7, textAlign: "center" as const }}>
            Enter to send · Shift+Enter for new line · Queries are audit-logged (no question text stored)
          </div>
        </div>
      </div>
    </div>
  );
}
