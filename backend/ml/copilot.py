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

try:                      # imported as a package by the backend: from backend.ml.copilot import answer
    from . import summarize as S
except ImportError:       # run as a script: python backend/ml/copilot.py
    import summarize as S

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
- Cite the incident ID for every incident you mention. When the question is about one user, IP, transaction or
  incident, cover EVERY incident listed in FACTS (one sentence each) - leaving one out is an error. Be concise: at most about 150 words.
- Do NOT write containment or remediation steps (blocking, locking, freezing...): they are added automatically
  after your answer, per incident. Do not invent tools, patches, people or deadlines.
- Never mix incidents: a user, IP or transaction belongs only to the incident it is listed under in FACTS.
- If FACTS say NO transfers or NO successful logins for an incident, do not claim otherwise.
- Write 2-5 plain sentences (a short bullet list only when listing several incidents, one line each).
  No headings, no "Field: value" lines, no JSON or code, no copying of FACTS lines. Under about 120 words.
- Nothing has been done yet: never say an IP "was blocked", an account "was locked" or money "was frozen".

{mode}
QUESTION: {question}

FACTS:
{facts}
"""
RETRY = """
Your previous answer had these problems: {problems}
Answer again using only the FACTS, citing only the incident IDs given there."""


def ask_text(prompt, temperature=0.1, timeout=180):
    """Plain-text generation (no JSON mode): the copilot's answer is just markdown for the chat."""
    import urllib.request
    body = json.dumps({"model": S.MODEL, "prompt": prompt, "stream": False,
                       "options": {"temperature": temperature, "num_predict": 350}}).encode()
    req = urllib.request.Request(S.OLLAMA_URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["response"]


def readability_problems(text):
    """Reject non-answers: JSON/code dumps, copied fact blocks, cut-off or overlong text."""
    p, t = [], text.strip()
    if not t:
        return ["empty answer"]
    if t[:1] in "{[" or "```" in t or re.search(r'"\w+"\s*:\s*[\[{"\d]', t):
        p.append("not a readable answer (JSON/code instead of prose)")
    if re.search(r"\[(?:Auth Service|Payments API|Threat Intel|AI Engine)\]|^\s*(?:Who|What|When|Where):"
                 r"|^\s*\**Incident:\s*INC-|\|\s*(?:Type|Severity|Model confidence|Impact):", t, re.M):
        p.append("copied raw fact lines instead of answering")
    if re.search(r"(?<![\d.])\d{1,3}\.\d{1,3}\.\d{1,3}\.?\s*$", t):   # 3 octets only, not the tail of a full IP
        p.append("answer is cut off mid-sentence (incomplete IP)")
    fields = re.findall(r"^\s*[*\-]?\s*\**(?:Who|What|When|Where|Accounts involved|Source IPs?|Transaction ID|Amount|"
                        r"Model Confidence|Impact|Severity|Location|Time|User IDs?|IP|Incident ID)\**\s*:", t, re.M | re.I)
    if len(fields) >= 3:
        p.append("copied fact fields (Field: value lines) instead of answering in prose")
    if len(re.findall(r"\b(?:do(?:es)?n'?t|do(?:es)? not) (?:provide|include|contain|mention)\b[^.\n]{0,40}\binformation\b"
                      r"|\bno (?:further|additional) information\b", t, re.I)) >= 1:
        p.append("filler: says the facts lack information instead of answering from them")
    if len(t.split()) > 260:
        p.append(f"too long ({len(t.split())} words)")
    dangling = re.search(r"\b(?:to|and|or|the|of|from|with|a|an|for|at|by|in|on|via|than|then)\s*$", t, re.I)
    if t[-1] in ',:;([{"\'-' or t.count("(") > t.count(")") or t.count("**") % 2 or dangling:
        p.append("answer is cut off mid-sentence")
    return p


def load():
    inc = json.loads((OUT / "incidents.json").read_text())
    rp = OUT / "reports.json"
    reports = {r["id"]: r for r in json.loads(rp.read_text())} if rp.exists() else {}
    return inc, reports


# Words that are fine in a question even though no incident contains them
KNOWN_WORDS = {"i", "ip", "ips", "inc", "id", "ids", "mfa", "otp", "api", "waf", "soc", "ato", "app", "upi", "ml", "ai",
               "llm", "shap", "mitre", "att&ck", "copilot", "sentra", "vantix", "fsia", "rs", "inr", "india", "indian",
               "september", "sept", "sep", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
               "sunday", "today", "yesterday", "ok", "okay", "please", "hi", "hello", "thanks", "and", "or", "the",
               "what", "which", "who", "when", "where", "why", "how", "show", "tell", "list", "give", "explain"}
NAME = re.compile(r"\b(?:[A-Z][A-Za-z0-9&]*(?:-[A-Za-z0-9]+)*)\b")
ID_LIKE = re.compile(r"^(?:INC-\d{4}-\d{4}|U\d{4}|T\d{6}|E\d{6}|A\d{6}|T\d{4}(?:\.\d{3})?|R_[A-Z_]+)$")


def unknown_names(q, incidents):
    """Names in the question (PayPal, FIN-APT-7, SWIFT) that appear nowhere in the data: the question assumes
    something that isn't there, so the answer must say so instead of playing along."""
    vocab = set(re.findall(r"[a-z0-9&]+", json.dumps(incidents).lower())) | KNOWN_WORDS
    words = q.split()
    out = []
    for m in NAME.finditer(q):
        tok = m.group(0)
        if m.start() == 0 or ID_LIKE.match(tok):        # first word is capitalised anyway; IDs are checked elsewhere
            continue
        parts = re.findall(r"[a-z0-9&]+", tok.lower())
        if parts and not all(x in vocab for x in parts) and tok not in out:
            out.append(tok)
    return out


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
    vectors = [v for v, words in VECTOR_WORDS.items()   # word START only: "takeovers" ok, "zomato" is not "ato"
               if any(re.search(rf"\b{re.escape(w)}", ql) for w in words)]
    places = {w for i in incidents for o in i.get("sequence", {}).get("successful_logins", [])
              for w in [o["location"].split(",")[0].lower()]} | {i["title"].split(" from ")[-1].split(",")[0].lower()
                                                                  for i in incidents if " from " in i["title"]}
    place = next((p for p in places if p and re.search(rf"\b{re.escape(p)}\b", ql)), None)
    if not sel and (vectors or place):
        pool = [i for i in incidents if (not vectors or i["vector"] in vectors)
                and (not place or place in json.dumps(i).lower())]
        sel = pool[:max_items]
        why.append(f"type/place: {', '.join(vectors) or ''} {place or ''}".strip())
    # merchants: "Zomato", "Amazon India", "crypto exchange"
    merchants = {t["merchant"] for i in incidents for t in i.get("sequence", {}).get("transfers", [])}
    named = [m for m in merchants if re.search(rf"\b{re.escape(m.split(' - ')[0].lower())}\b", ql)
             or re.search(rf"\b{re.escape(m.split()[0].lower())}\b", ql) and len(m.split()[0]) > 4]
    if named and not sel:
        sel = [i for i in incidents if {t["merchant"] for t in i["sequence"].get("transfers", [])} & set(named)][:max_items]
        why.append(f"merchant: {', '.join(sorted(named))}")
    # dates: "2026-09-10", "10 Sept", "September 10", "10/09" (combined with type/place/merchant if given)
    mon = r"(?:sep(?:t(?:ember)?)?)"
    day = (re.search(r"\b2026-09-(\d{2})\b", ql) or re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{mon}\b", ql)
           or re.search(rf"\b{mon}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", ql) or re.search(r"\b(\d{1,2})/0?9\b", ql))
    if day:
        d = f"2026-09-{int(day.group(1)):02d}"
        pool = ([i for i in incidents if i["vector"] in vectors] if vectors   # all of that type, not just the top 5
                else sel if sel else incidents)
        on_day = [i for i in pool if i["start"][:10] <= d <= i["end"][:10]]
        sel = on_day[:max_items]
        why.append(f"date: {d}" if on_day else f"not found: incidents on {d}" + (f" ({', '.join(vectors)})" if vectors else ""))
    sev = next((s for s in SEV_ORDER if s in ql), None)
    if not sel and sev:
        sel = [i for i in incidents if i["sev"] == sev][:max_items]
        why.append(f"severity: {sev}")
    wants_stats = bool(re.search(r"\bhow many\b|\bcount(?:s)?\b|\bnumber of\b|\bstats?\b|\boverview\b|"
                                 r"\bbreakdown\b|\bsummar\w*|\bposture\b|\btoday\b", ql))
    unknown = unknown_names(q, incidents)
    if unknown:
        why.append(f"not found: {', '.join(unknown)}")
    # superlatives rank over ALL matching incidents, not the 5 highest-risk ones
    metric = (("money", lambda i: -i["amount_total"]) if re.search(r"\b(?:money|amount|lost|stolen|largest|biggest|"
                                                                  r"transferr?ed|costliest)\b", ql) else
              ("accounts", lambda i: -len(i["users"])) if re.search(r"\b(?:accounts|users|victims|targets)\b", ql) else
              ("earliest", lambda i: i["start"]) if re.search(r"\b(?:first|earliest|oldest)\b", ql) else
              ("latest", lambda i: [-ord(c) for c in i["start"]]) if re.search(r"\b(?:last|latest|most recent|newest)\b", ql)
              else None)
    if metric and re.search(r"\b(?:most|least|largest|biggest|highest|lowest|first|earliest|oldest|last|latest|"
                            r"newest|top|worst|costliest)\b", ql) and not (ids or users or ips or txns):
        pool = [i for i in incidents if (not vectors or i["vector"] in vectors) and (not sev or i["sev"] == sev)]
        sel = sorted(pool, key=metric[1])[:max_items]
        why = [w for w in why if not w.startswith(("type/place", "severity", "top risk"))] + [f"ranked by {metric[0]}"]
    asked_entity = bool(ids or users or ips or txns or unknown or day or named or DONE_Q.search(q))
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


def facts_for(sel, reports, incidents, with_stats, why=(), full=False):
    parts = [f"NOT IN THE DATA: {w.split(': ', 1)[1]} - no incident involves this" for w in why if w.startswith("not found")]
    if rankings(sel):
        parts.append(rankings(sel))
    if with_stats:
        parts.append("OVERVIEW\n" + stats_block(incidents))
    compact = len(sel) >= 3 and not full
    if compact:
        parts.append("INCIDENTS (one line each)")
    for i in sel:
        if compact:
            loc = next((o["location"] for o in i.get("sequence", {}).get("successful_logins", [])), "")
            parts.append(f"- {i['id']} | {i['vector']} | {i['sev']} | users {', '.join(i['users'])} | IP {', '.join(i['ips'][:2])}"
                         f"{' (' + loc + ')' if loc else ''} | ₹{i['amount_total']:,.0f} moved | {i['start'][:10]} | "
                         + S.sequence_line(i))
            continue
        block = S.facts_block(i) + "\nAll users in this incident: " + ", ".join(i["users"])
        r = reports.get(i["id"])
        if r and r.get("grounding", {}).get("grounded") and not compact:
            block += f"\nVerified report summary: {r['summary']}"
        parts.append(block)
    return "\n\n".join(parts)


def fallback(sel, incidents, with_stats, why=()):
    """Correct-by-construction reply from the facts, used when the LLM can't pass the check."""
    def nf(x):
        if x.startswith("incidents on "):
            d = x.split()[2]
            return (f"{d} is not a real date (September has 30 days)." if d.endswith("-31") and "-09-" in d else
                    f"There are no incidents on {x[len('incidents on '):]} in the current data.")
        return f"No incident in the current data involves {x}."
    out = [nf(w.split(": ", 1)[1]) for w in why if w.startswith("not found")]
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
    WN = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
    for m in re.finditer(r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:\w+\s+){0,2}incidents?\b", text, re.I):
        if not re.search(r"\b(?:types?|kinds?|categories)\b", m.group(0), re.I) and str(WN[m.group(1).lower()]) not in ok_n:
            extra_p.append(f'wrong incident count: "{m.group(0)}"')
    if llm and re.search(r"\b(?:was|were|has been|have been|is now|are now)\s+(?:\w+\s+)?(?:blocked|locked|frozen|"
                         r"recalled|revoked|reset|contained|suspended|rate-limited)\b", text, re.I):
        extra_p.append("claims actions were already taken (they are only recommended)")
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


def welcome():
    """Opening message for the Copilot page (replaces the mock ANSWERS.default). Built by code from the data, so
    it is instant, needs no Ollama and is always correct. Uses the page's renderText format (**bold** lines)."""
    incidents, _ = load()
    sev = Counter(i["sev"] for i in incidents)
    vec = Counter(i["vector"] for i in incidents)
    crit = [i for i in incidents if i["sev"] == "critical"][:3]
    money = sum(i["amount_total"] for i in incidents if i["vector"] == "Account Takeover")
    lines = ["**Security Posture Summary**", "",
             f"{len(incidents)} open incidents: **{sev.get('critical', 0)} critical**, {sev.get('high', 0)} high, "
             f"{sev.get('medium', 0)} medium, {sev.get('low', 0)} low.",
             "By type: " + ", ".join(f"{v} {k}" for k, v in vec.most_common()) + ".",
             f"Amount in account-takeover transfers: **₹{money:,.0f}**.", "", "**Highest-risk incidents**"]
    lines += [f"{n}. **{i['id']}** - {i['title']} (risk {i['risk_score']:.0f})" for n, i in enumerate(crit, 1)]
    lines += ["", "Ask me about any incident ID, user (U0214), IP, transaction (T002428) or attack type."]
    return {"question": None, "answer": "\n".join(lines), "incidents": [i["id"] for i in crit],
            "source": "facts", "grounding": {"grounded": True, "unverified": []}, "seconds": 0.0}


DONE_Q = re.compile(r"\b(?:were|was|been|got|already|have we|did we)\b[^?]{0,40}\b(?:locked|blocked|frozen|"
                    r"suspended|banned|reset|recalled|contained)\b|\b(?:locked|blocked|frozen)\b[^?]{0,30}\b(?:yesterday|"
                    r"already|today)\b", re.I)
FAIL_Q = re.compile(r"\b(?:why|how)\b[^?]*\b(?:fail(?:ed)?|unsuccessful|didn'?t (?:work|succeed|get in))\b", re.I)
BLOCK_Q = re.compile(r"\b(?:should|can|do|shall|must)\b[^?]{0,20}\bblock\b", re.I)
OWNER_Q = re.compile(r"\b(?:themselves|himself|herself|the customer (?:did|made|sent)|by the (?:customer|user)|"
                     r"(?:was|is) it (?:really )?(?:the customer|them|the user)|their own)\b", re.I)
MONEY_Q = re.compile(r"\b(?:how much|money|stolen|lost|amount|transferr?ed|rupees|₹)\b", re.I)


def premise_notes(question, sel):
    """Facts written by code when the question assumes something false. The LLM answer comes after them."""
    notes = []
    if DONE_Q.search(question):
        notes.append("Nothing has been locked, blocked or frozen yet: Sentra only detects incidents and recommends "
                     "containment; an analyst carries it out. The recommended actions are listed per incident.")
    if BLOCK_Q.search(question):
        asked = set(re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", question))
        for i in sel:
            for d in i.get("ip_details", []):
                if asked and d["ip"] not in asked:
                    continue
                if d["usual_for_user"] and d["threat"] == "None":
                    notes.append(f"No - do not block {d['ip']}: it is the usual IP of {', '.join(i['users'][:3])}, "
                                 f"so blocking it would lock out the real customer. Verify the activity with them "
                                 f"instead ({i['id']}).")
                else:
                    feed = f"on the threat feed ({d['threat']})" if d["threat"] != "None" else "not one the customer uses"
                    notes.append(f"Yes - block {d['ip']}: it is {feed} and was used in {i['id']} ({i['vector']}).")
    for i in sel:
        sq = i.get("sequence", {})
        if FAIL_Q.search(question) and sq.get("successful_logins"):
            o = sq["successful_logins"][0]
            notes.append(f"Note: {i['id']} was not only failures - there was a successful login to {o['user']} at "
                         f"{o['time']} from {o['ip']} ({o['location']}).")
        if OWNER_Q.search(question):
            for t in sq.get("transfers", [])[:3]:
                if "usual_ip" not in t:
                    continue
                if t["usual_ip"] and t["registered_device"]:
                    notes.append(f"{t['id']} (₹{t['amount']:,.0f} to {t['merchant']}) came from the customer's usual IP and "
                                 f"registered device, so it was most likely made by the customer - or by someone who "
                                 f"tricked them into paying. Confirm with the customer before acting.")
                else:
                    notes.append(f"{t['id']} (₹{t['amount']:,.0f} to {t['merchant']}) did NOT come from the customer's "
                                 f"usual setup ({'new IP' if not t['usual_ip'] else ''}"
                                 f"{' and ' if not t['usual_ip'] and not t['registered_device'] else ''}"
                                 f"{'unregistered device' if not t['registered_device'] else ''}), so it was most likely "
                                 f"not the customer.")
        if MONEY_Q.search(question) and not sq.get("transfers") and i["vector"] != "Transaction Anomaly":
            notes.append(f"No money moved in {i['id']}: it was a login attack with no transfers.")
    return notes


def answer(question, max_attempts=3):
    t0 = time.time()
    incidents, reports = load()
    sel, why, with_stats = retrieve(question, incidents)
    missing = [w.split(": ", 1)[1] for w in why if w.startswith("not found")]
    notes = premise_notes(question, sel)
    if notes and not sel:          # e.g. "which accounts were locked?" with no incident named: the note IS the answer
        return {"question": question, "answer": " ".join(notes), "incidents": [], "retrieved_by": why + ["premise"],
                "source": "facts", "grounding": {"grounded": True, "unverified": [], "checked": 0}, "attempts": [],
                "seconds": round(time.time() - t0, 1)}
    if missing and not sel and not with_stats:      # nothing real to talk about: answer from code, no LLM
        text = fallback(sel, incidents, with_stats, why)
        return {"question": question, "answer": text, "incidents": [], "retrieved_by": why, "source": "facts",
                "grounding": {"grounded": True, "unverified": [], "checked": 0}, "attempts": [],
                "seconds": round(time.time() - t0, 1)}
    facts = facts_for(sel, reports, incidents, with_stats, why)               # what the model sees
    vfacts = facts_for(sel, reports, incidents, with_stats, why, full=True)   # what claims are checked against
    action_q = bool(re.search(r"\bremediat\w*|\bcontain\w*|\bmitigat\w*|\bplan\b|\bwhat (?:should|do) we do\b|"
                              r"\bnext steps?\b|\brespond\w*|\bfix\b", question.lower()))
    mode = ("- This is a remediation question: the per-incident steps are added automatically below your answer. Write\n"
            "  ONLY 2-3 sentences saying which incident to act on first and why (amount moved, time, threat level).\n"
            "  Do not write any steps yourself.\n") if action_q else ""
    prompt = PROMPT.format(question=question.strip(), facts=facts, mode=mode)
    attempts, best = [], None
    for k in range(1, max_attempts + 1):
        p = prompt if k == 1 else prompt + RETRY.format(problems="; ".join(best["grounding"]["unverified"]))
        text = ask_text(p, temperature=0.1 if k == 1 else 0.4).strip()
        text = re.sub(r"\s*<br\s*/?>\s*", "\n", text)          # the frontend renders markdown, not html
        g = check(text, vfacts, sel) if text else {"grounded": False, "unverified": [], "checked": 0}
        # questions about a specific user / IP / transaction / incident must cover EVERY incident it appears in
        if any(w in ("user/ip/transaction", "incident id") for w in why):
            skipped = [i["id"] for i in sel if i["id"] not in text]
            if skipped:
                g["unverified"] = sorted(g["unverified"] + [f"leaves out {', '.join(skipped)} (all {len(sel)} incidents "
                                                            f"must be covered)"])
                g["grounded"] = False
        if any(i.get("sequence", {}).get("successful_logins") for i in sel) and \
                re.search(r"\bfailed because\b|\bwas unsuccessful because\b", text, re.I):
            g["unverified"] = sorted(g["unverified"] + ["explains a failure, but a login succeeded"])
            g["grounded"] = False
        for m in missing:
            if re.search(rf"\b{re.escape(m)}\b", text, re.I):
                g["unverified"] = sorted(g["unverified"] + [f"repeats '{m}', which is not in the data"])
                g["grounded"] = False
        rp = readability_problems(text)
        if rp:
            g["unverified"] = sorted(g["unverified"] + rp)
            g["grounded"] = False
        attempts.append({"attempt": k, "grounded": g["grounded"], "problems": g["unverified"]})
        if best is None or len(g["unverified"]) < len(best["grounding"]["unverified"]):
            best = {"text": text, "grounding": g}
        if g["grounded"]:
            break
    if best["grounding"]["grounded"]:
        src, text = ("llm" if len(attempts) == 1 else "llm_corrected"), best["text"]
    else:
        src, text = "facts", fallback(sel, incidents, with_stats, why)
        best["grounding"] = check(text, vfacts, sel, llm=False)
    if notes:                                   # the question assumed something false: code corrects it first
        text = " ".join(notes) + "\n\n" + text
    if missing and src != "facts":              # the question named something the data doesn't have: say so first
        text = "".join(f"No incident in the current data involves {m}. " for m in missing) + "\n\n" + text
    # actions come from code, only for the incidents the answer is actually about (a refusal gets none)
    text += containment_section([i for i in sel if i["id"] in text])
    return {"question": question, "answer": text, "incidents": [i["id"] for i in sel], "retrieved_by": why,
            "source": src, "grounding": best["grounding"], "attempts": attempts,
            "seconds": round(time.time() - t0, 1)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("question", nargs="?")
    p.add_argument("--demo", action="store_true", help="run the suggestion chips")
    p.add_argument("--chat", action="store_true", help="type questions one after another (empty line or 'quit' ends)")
    a = p.parse_args()
    if a.chat:
        print(welcome()["answer"].replace("**", ""), "\n")
        while True:
            try:
                q = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not q or q.lower() in ("quit", "exit", "q"):
                break
            print("   thinking...", flush=True)
            try:
                r = answer(q)
            except urllib.error.URLError as e:
                raise SystemExit(f"Can't reach Ollama at {S.OLLAMA_URL} ({e.reason}). Is `ollama serve` running?")
            print(f"Copilot ({r['source']}, {r['seconds']}s, verified: {r['grounding']['grounded']}):")
            print("   " + r["answer"].replace("**", "").replace("\n", "\n   ") + "\n")
        return
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
