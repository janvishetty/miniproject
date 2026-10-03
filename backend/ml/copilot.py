"""
Sentra / FSIA - AI/ML module: AI Copilot (analyst chat), grounded in the incident data.

    answer(question) -> {"answer": markdown, "incidents": [ids used], "source": "llm" | "llm_corrected" | "facts",
                         "grounding": {...}, "attempts": [...], "seconds": float}

1. RETRIEVE (code): work out what the question is about - incident IDs, users, IPs, transaction IDs,
   attack types, "critical", "how many" - and pull those incidents, their verified reports and summary stats.
2. ANSWER (LLM, llama3.2:3b via Ollama): write the reply using ONLY that facts block.
3. VERIFY (code): the same grounding check as the reports (IDs, IPs, amounts, times, places, currency,
   invented names) + every incident ID it cites must be one it was given. Up to 3 attempts with feedback;
   if it still fails, the reply is built from the facts by code, so nothing unverified reaches the analyst.

Backend use (Anushka):   from backend.ml.copilot import answer      ->   POST /copilot {"question": "..."}
CLI:                     python backend/ml/copilot.py "What caused INC-2026-0081?"
                         python backend/ml/copilot.py --demo          (runs the frontend's suggestion chips)
"""
import argparse
import json
import re
import time
import urllib.error
from collections import Counter
from pathlib import Path

import summarize as S   # reuse facts_block, containment_actions, grounding_check, ask_ollama

OUT = Path(__file__).resolve().parent / "output"
SEV_ORDER = ["critical", "high", "medium", "low"]
VECTOR_WORDS = {
    "Account Takeover": ["takeover", "ato", "hijack", "compromised account"],
    "Credential Stuffing": ["stuffing", "credential"],
    "Brute Force": ["brute", "password guessing"],
    "Transaction Anomaly": ["transaction anomaly", "payment", "scam", "app fraud", "unusual transfer"],
    "Suspicious Login": ["suspicious login", "login from", "new device"],
}
DEMO = [
    "Summarize the critical incidents",
    "What caused INC-2026-0081?",
    "Generate a remediation plan for the account takeovers",
    "How many incidents are there by type?",
    "What happened to user U0063?",
    "Explain the credential stuffing from Moscow",
]

PROMPT = """You are Sentra's SOC copilot for a FinTech security team. Answer the analyst's QUESTION using ONLY the FACTS.
Rules:
- Use only incident IDs, user IDs, IPs, transaction IDs, amounts (Indian rupees, written with the rupee sign), times
  and places that appear in FACTS. If FACTS do not contain the answer, say so in one sentence.
- Cite the incident ID for every incident you mention. Be concise: at most about 150 words.
- Do NOT write containment or remediation steps (blocking, locking, freezing...): they are added automatically
  after your answer, per incident. Do not invent tools, patches, people or deadlines.
- Never mix incidents: a user, IP or transaction belongs only to the incident it is listed under in FACTS.
- If FACTS say NO transfers or NO successful logins for an incident, do not claim otherwise.
- Light markdown is fine (**bold**, short lists). Respond with JSON only: {{"answer": "<markdown>"}}

{mode}
QUESTION: {question}

FACTS:
{facts}
"""
RETRY = """
Your previous answer had these problems: {problems}
Answer again using only the FACTS, citing only the incident IDs given there."""


def load():
    inc = json.loads((OUT / "incidents.json").read_text())
    rp = OUT / "reports.json"
    reports = {r["id"]: r for r in json.loads(rp.read_text())} if rp.exists() else {}
    return inc, reports


def retrieve(q, incidents, max_items=5):
    """Pick the incidents a question is about. Returns (selected incidents, why, wants_stats)."""
    ql = q.lower()
    by_id = {i["id"]: i for i in incidents}
    ids = [x.upper() for x in re.findall(r"\binc-\d{4}-\d{4}\b", ql)]
    users = {x.upper() for x in re.findall(r"\bu\d{4}\b", ql)}
    txns = {x.upper() for x in re.findall(r"\bt\d{6}\b", ql)}
    ips = set(re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", q))
    sel, why = [], []
    if ids:
        sel = [by_id[i] for i in ids if i in by_id]
        why.append("incident id")
        missing = [i for i in ids if i not in by_id]
        if missing:
            why.append(f"not found: {', '.join(missing)}")
    if users or ips or txns:
        hit = [i for i in incidents if users & set(i["users"]) or ips & set(i["ips"])
               or txns & {t["id"] for t in i.get("sequence", {}).get("transfers", [])}]
        sel += [i for i in hit if i not in sel]
        why.append("user/ip/transaction" if hit else
                   f"not found: {', '.join(sorted(users | ips | txns))}")
    vectors = [v for v, words in VECTOR_WORDS.items() if any(w in ql for w in words)]
    places = {w for i in incidents for o in i.get("sequence", {}).get("successful_logins", [])
              for w in [o["location"].split(",")[0].lower()]} | {i["title"].split(" from ")[-1].split(",")[0].lower()
                                                                  for i in incidents if " from " in i["title"]}
    place = next((p for p in places if p and re.search(rf"\b{re.escape(p)}\b", ql)), None)
    if not sel and (vectors or place):
        pool = [i for i in incidents if (not vectors or i["vector"] in vectors)
                and (not place or place in json.dumps(i).lower())]
        sel = pool[:max_items]
        why.append(f"type/place: {', '.join(vectors) or ''} {place or ''}".strip())
    sev = next((s for s in SEV_ORDER if s in ql), None)
    if not sel and sev:
        sel = [i for i in incidents if i["sev"] == sev][:max_items]
        why.append(f"severity: {sev}")
    wants_stats = bool(re.search(r"\bhow many\b|\bcount(?:s)?\b|\bnumber of\b|\bstats?\b|\boverview\b|"
                                 r"\bbreakdown\b|\bsummar\w*|\bposture\b|\btoday\b", ql))
    asked_entity = bool(ids or users or ips or txns)
    if not sel and not wants_stats and not asked_entity:
        sel = incidents[:3]          # vague question: fall back to the highest-risk incidents
        why.append("top risk")
    return sel[:max_items], why, wants_stats


def stats_block(incidents):
    by_v = Counter(i["vector"] for i in incidents)
    by_s = Counter(i["sev"] for i in incidents)
    money = sum(i["amount_total"] for i in incidents if i["vector"] == "Account Takeover")
    lines = [f"Total incidents: {len(incidents)}",
             "By severity: " + ", ".join(f"{s} {by_s[s]}" for s in SEV_ORDER if by_s[s]),
             "By type: " + ", ".join(f"{v} {n}" for v, n in by_v.most_common()),
             f"Money moved in account takeovers: ₹{money:,.0f} across {by_v['Account Takeover']} incidents",
             "Highest-risk incidents: " + ", ".join(f"{i['id']} ({i['vector']}, {i['sev']})" for i in incidents[:5])]
    return "\n".join(lines)


def rankings(sel):
    if len(sel) < 2:
        return ""
    money = sorted(sel, key=lambda i: -i["amount_total"])
    when = sorted(sel, key=lambda i: i["start"])
    return ("RANKINGS (use these for any comparison)\n"
            "By money moved, most first: " + " > ".join(f"{i['id']} ₹{i['amount_total']:,.0f}" for i in money) + "\n"
            "By start time, earliest first: " + " > ".join(f"{i['id']} {i['start'][:16].replace('T', ' ')}" for i in when) + "\n"
            "By model confidence, highest first: " + " > ".join(f"{i['id']} {i['confidence']}" for i in
                                                                 sorted(sel, key=lambda i: -i["confidence"])))


def facts_for(sel, reports, incidents, with_stats, why=()):
    parts = [f"NOT IN THE DATA: {w.split(': ', 1)[1]} - no incident involves this" for w in why if w.startswith("not found")]
    if rankings(sel):
        parts.append(rankings(sel))
    if with_stats:
        parts.append("OVERVIEW\n" + stats_block(incidents))
    for i in sel:
        block = S.facts_block(i)
        block += "\nContainment: " + " | ".join(S.containment_actions(i))
        r = reports.get(i["id"])
        if r and r.get("grounding", {}).get("grounded"):
            block += f"\nVerified report summary: {r['summary']}"
        parts.append(block)
    return "\n\n".join(parts)


def fallback(sel, incidents, with_stats, why=()):
    """Correct-by-construction reply from the facts, used when the LLM can't pass the check."""
    out = [f"No incident in the current data involves {w.split(': ', 1)[1]}." for w in why if w.startswith("not found")]
    if with_stats:
        by_v = Counter(i["vector"] for i in incidents)
        out.append(f"**{len(incidents)} incidents**: " + ", ".join(f"{n} {v}" for v, n in by_v.most_common()) + ".")
    for i in sel:
        t, _ = S.template_report(i)
        out.append(f"**{i['id']}** ({i['vector']}, {i['sev']}): {t}")
    if not out:
        out.append("No incident in the current data matches that question.")
    return "\n\n".join(out)


MERGE_WORDS = re.compile(r"\b(?:was |were )?later (?:found|turned out|confirmed) to be\b|\bturned out to be\b|"
                         r"\bwhich became\b|\bescalated (?:in)?to\b", re.I)
ACTION_WORDS = re.compile(r"\b(?:block(?:ing)? (?:the )?ip|lock(?:ing)? (?:the )?account|freeze|recall|revoke|"
                          r"force (?:a )?password reset|rate-limit)\b", re.I)


def owners(sel):
    """entity (user / IP / transaction / incident id) -> set of incident ids it belongs to."""
    own = {}
    for i in sel:
        ents = set(i["users"]) | set(i["ips"]) | {i["id"]}
        ents |= {t["id"] for t in i.get("sequence", {}).get("transfers", [])}
        for e in ents:
            own.setdefault(e, set()).add(i["id"])
    return own


def pairing_problems(text, sel):
    """Every sentence must talk about ONE incident: the entities it names must share an incident."""
    own, out = owners(sel), []
    ent_re = re.compile(r"\bINC-\d{4}-\d{4}\b|\bU\d{4}\b|\bT\d{6}\b|\b\d{1,3}(?:\.\d{1,3}){3}\b")
    for sent in re.split(r"(?<=[.;!?])\s+|\n+", text):
        ents = list(dict.fromkeys(e for e in ent_re.findall(sent) if e in own))
        kind = lambda e: "inc" if e.startswith("INC") else "user" if e.startswith("U") else "txn" if e.startswith("T") else "ip"
        kinds = {kind(e) for e in ents}
        if len(kinds) < 2:
            continue            # a plain list of one kind (e.g. one IP per incident) is fine
        # each entity must share an incident with at least one entity of every OTHER kind in the sentence
        for e in ents:
            for k in kinds - {kind(e)}:
                if not any(own[e] & own[o] for o in ents if kind(o) == k):
                    out.append(f"mixes incidents in one sentence: {e} does not belong with the {k} named beside it")
                    break
    return out


def containment_section(sel, per=4):
    lines = [f"- **{i['id']}**: " + "; ".join(S.containment_actions(i)[:per]) for i in sel]
    return "\n\n**Containment (from the data)**\n" + "\n".join(lines) if lines else ""


def check(text, facts, sel, llm=True):
    g = S.grounding_check(text, facts)
    extra_p = pairing_problems(text, sel)
    if llm and ACTION_WORDS.search(text):
        extra_p.append("wrote containment steps (these are added by code)")
    if llm and len(sel) >= 2:
        top_money = max(sel, key=lambda i: i["amount_total"])["id"]
        first = min(sel, key=lambda i: i["start"])["id"]
        last = max(sel, key=lambda i: i["start"])["id"]
        last = []
        for sent in re.split(r"(?<=[.;!?])\s+|\n+", text):
            named = re.findall(r"\bINC-\d{4}-\d{4}\b", sent)
            if not named and last and re.search(r"\b(?:this|that|the same|it)\b", sent, re.I):
                named = last          # "This incident also has..." refers back to the last one named
            if not named:
                continue
            last = named
            if re.search(r"\b(?:highest|largest|biggest|most|greatest|maximum)\b[^.]{0,30}\b(?:amount|money|loss|value|₹)", sent, re.I) \
                    and top_money not in named:
                extra_p.append(f"wrong superlative: most money moved is {top_money}, not {', '.join(named)}")
            for field, words in (("confidence", r"confidence"), ("impact", r"impact"), ("risk_score", r"risk")):
                if re.search(rf"\b(?:highest|most|greatest|maximum|top)\b[^.]{{0,25}}\b{words}", sent, re.I):
                    best = max(i[field] for i in sel)
                    top = {i["id"] for i in sel if i[field] == best}
                    if not set(named) & top:
                        extra_p.append(f"wrong superlative: highest {field.replace('_', ' ')} is {', '.join(sorted(top))}")
            if re.search(r"\bearliest|first to (?:occur|happen)|\boldest\b", sent, re.I) and first not in named:
                extra_p.append(f"wrong superlative: earliest is {first}, not {', '.join(named)}")
            if re.search(r"\blatest\b|\bmost recent\b", sent, re.I) and last not in named:
                extra_p.append(f"wrong superlative: latest is {last}, not {', '.join(named)}")
    # blaming a threat feed for an incident whose IPs are on none
    if llm:
        no_feed = {i["id"]: i for i in sel if i.get("ip_threat_level", "None") == "None"}
        own = owners(sel)
        for sent in re.split(r"(?<=[.;!?])\s+|\n+", text):
            if not re.search(r"threat[- ]?(?:list|intel\w*|feed)", sent, re.I) or re.search(r"\bnot\b|\bno\b", sent, re.I):
                continue
            ents = re.findall(r"\bINC-\d{4}-\d{4}\b|\bU\d{4}\b|\bT\d{6}\b|\b\d{1,3}(?:\.\d{1,3}){3}\b", sent)
            incs = set.union(set(), *(own.get(e, set()) for e in ents)) if ents else set()
            if incs and incs <= set(no_feed):
                extra_p.append(f"claims threat intel for {', '.join(sorted(incs))}, whose IPs are on no threat feed")
    if llm and re.search(r"\bFACTS?\b", text):
        extra_p.append('mentions "FACTS" (internal prompt wording)')
    if llm and MERGE_WORDS.search(text):
        extra_p.append(f'merges separate incidents: "{MERGE_WORDS.search(text).group(0)}"')
    # "N incidents" must be a real number: the total, a per-type or per-severity count, or how many are discussed
    ok_n = {str(len(sel))} | set(re.findall(r"Total incidents: (\d+)", facts)) | \
           set(re.findall(r"(?:critical|high|medium|low|Takeover|Stuffing|Force|Anomaly|Login) (\d+)", facts))
    for m in re.finditer(r"(?<![\d.,₹])\b(\d+)\*{0,2} (?:\w+ ){0,2}incidents?\b", text):
        if re.search(r"\b(?:types?|kinds?|categories|classes)\b", m.group(0), re.I):
            continue
        if m.group(1) not in ok_n:
            extra_p.append(f'wrong incident count: "{m.group(0)}"')
    if re.search(r"\b(?:\d+|five|four|three) (?:incident )?types?\b", text) is None and \
            re.search(r"\bincidents by type\b", text, re.I) and re.search(r"\*{0,2}\d+\*{0,2} incidents by type", text):
        extra_p.append("calls the number of types a number of incidents")
    # a count next to an attack type must equal the real number of incidents of that type
    counts = {v: n for v, n in re.findall(r"(Account Takeover|Credential Stuffing|Brute Force|Transaction Anomaly|"
                                          r"Suspicious Login) (\d+)", facts)}
    for v, n in counts.items():
        for m in re.finditer(rf"{v}s?\**[ ]?[:=-]?[ ]?\**(\d+)\**(?=[ ]*(?:incidents?\b|[,;)\n]|\.(?!\d)|$))|"
                             rf"\b(\d+)\**[ ]+{v}", text, re.I):
            got = m.group(1) or m.group(2)
            if got != n:
                extra_p.append(f'wrong count for {v}: {got} (data: {n})')
    if extra_p:
        g["unverified"] = sorted(g["unverified"] + extra_p)
        g["grounded"] = False
    cited = set(re.findall(r"\bINC-\d{4}-\d{4}\b", text))
    allowed = set(re.findall(r"\bINC-\d{4}-\d{4}\b", facts))
    extra = sorted(cited - allowed)
    if extra:
        g["unverified"] = sorted(g["unverified"] + [f"incident not in facts: {x}" for x in extra])
        g["grounded"] = False
    return g


def answer(question, max_attempts=3):
    t0 = time.time()
    incidents, reports = load()
    sel, why, with_stats = retrieve(question, incidents)
    facts = facts_for(sel, reports, incidents, with_stats, why)
    action_q = bool(re.search(r"\bremediat\w*|\bcontain\w*|\bmitigat\w*|\bplan\b|\bwhat (?:should|do) we do\b|"
                              r"\bnext steps?\b|\brespond\w*|\bfix\b", question.lower()))
    mode = ("- This is a remediation question: the per-incident steps are added automatically below your answer. Write\n"
            "  ONLY 2-3 sentences saying which incident to act on first and why (amount moved, time, threat level).\n"
            "  Do not write any steps yourself.\n") if action_q else ""
    prompt = PROMPT.format(question=question.strip(), facts=facts, mode=mode)
    attempts, best = [], None
    for k in range(1, max_attempts + 1):
        p = prompt if k == 1 else prompt + RETRY.format(problems="; ".join(best["grounding"]["unverified"]))
        raw = S.ask_ollama(p, temperature=0.1 if k == 1 else 0.4)
        try:
            text = str(json.loads(raw).get("answer", "")).strip()
        except (json.JSONDecodeError, AttributeError):
            text = raw.strip()
        text = re.sub(r"\s*<br\s*/?>\s*", "\n", text)          # the frontend renders markdown, not html
        g = check(text, facts, sel) if text else {"grounded": False, "unverified": ["empty answer"], "checked": 0}
        attempts.append({"attempt": k, "grounded": g["grounded"], "problems": g["unverified"]})
        if best is None or len(g["unverified"]) < len(best["grounding"]["unverified"]):
            best = {"text": text, "grounding": g}
        if g["grounded"]:
            break
    if best["grounding"]["grounded"]:
        src, text = ("llm" if len(attempts) == 1 else "llm_corrected"), best["text"]
    else:
        src, text = "facts", fallback(sel, incidents, with_stats, why)
        best["grounding"] = check(text, facts, sel, llm=False)
    text += containment_section(sel)            # actions always come from code, grouped per incident
    return {"question": question, "answer": text, "incidents": [i["id"] for i in sel], "retrieved_by": why,
            "source": src, "grounding": best["grounding"], "attempts": attempts,
            "seconds": round(time.time() - t0, 1)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("question", nargs="?")
    p.add_argument("--demo", action="store_true", help="run the suggestion chips")
    a = p.parse_args()
    qs = DEMO if a.demo or not a.question else [a.question]
    results = []
    for q in qs:
        try:
            r = answer(q)
        except urllib.error.URLError as e:
            raise SystemExit(f"Can't reach Ollama at {S.OLLAMA_URL} ({e.reason}). Is `ollama serve` running?")
        results.append(r)
        print(f"\nQ: {q}\n   [{r['source']}, {r['seconds']}s, grounded: {r['grounding']['grounded']}, "
              f"incidents: {', '.join(r['incidents']) or '-'}]")
        for att in r["attempts"][:-1] if r["source"] != "facts" else r["attempts"]:
            print(f"   (attempt {att['attempt']} rejected: {att['problems']})")
        print("   " + r["answer"].replace("\n", "\n   "))
    if len(results) > 1:
        c = Counter(r["source"] for r in results)
        print(f"\n{len(results)} answers | verified {sum(r['grounding']['grounded'] for r in results)}/{len(results)} | "
              f"llm {c['llm']}, llm_corrected {c['llm_corrected']}, facts fallback {c['facts']} | "
              f"avg {sum(r['seconds'] for r in results) / len(results):.1f}s")
        (OUT / "copilot_demo.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
