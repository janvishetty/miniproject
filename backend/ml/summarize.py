"""
Sentra / FSIA - AI/ML module, step 4: incident reports with a local LLM (Ollama, llama3.2:3b).

Hallucination control (small models invent details if allowed):
  1. Facts (Five Ws, MITRE technique, evidence) are filled in by Python straight from the data.
  2. The LLM only writes the narrative summary + recommended actions, from a fixed FACTS block,
     in JSON mode, at low temperature.
  3. Grounding check: every IP, user ID and rupee amount in the LLM's text is verified against
     the facts. Anything not found is listed in `grounding.unverified` and the report is marked.

Run (from repo root, with `ollama serve` running):
  python backend/ml/summarize.py              # all critical + high incidents (cached reports are skipped)
  python backend/ml/summarize.py --all        # all 254 incidents
  python backend/ml/summarize.py --sev medium # only medium
  python backend/ml/summarize.py --force      # regenerate even if cached
  python backend/ml/summarize.py --retry-templates   # retry only the reports that fell back to the template
  python backend/ml/summarize.py --id INC-2026-0080
  python backend/ml/summarize.py --dry-run    # print the prompt, don't call Ollama
"""
import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = os.environ.get("SENTRA_LLM", "llama3.2:3b")   # try another Ollama model: SENTRA_LLM=qwen2.5:7b

# Mapping done in code, not by the LLM, so it can't be hallucinated
MITRE = {
    "Account Takeover": ["T1110 Brute Force", "T1078 Valid Accounts", "T1657 Financial Theft"],   # = rule engine + answer key
    "Credential Stuffing": ["T1110.004 Credential Stuffing"],
    "Brute Force": ["T1110.001 Password Guessing"],
    "Suspicious Login": ["T1078 Valid Accounts"],
    "Transaction Anomaly": ["T1657 Financial Theft"],
}

PROMPT = """You are a SOC analyst assistant at a FinTech company. Write an incident report using ONLY the FACTS below.
Rules:
- Do not invent IP addresses, user IDs, transaction IDs, amounts, times, locations or destinations not in FACTS.
- Always name the affected user ID(s) from "Who". Amounts are Indian rupees (₹) only.
- If FACTS say NO transfers, do NOT mention any transfer, transaction, merchant, funds or amount - it was a login attack.
- If FACTS say NO successful logins, state that all attempts failed - do NOT claim anyone logged in.
- summary: 2-3 sentences that narrate the ATTACK SEQUENCE in time order, with the exact counts, times and amounts
  (how many failed logins, when the successful login happened and from where, which transfers followed, when,
  and to which merchant/channel). Describe where money went ONLY using the merchant names given in FACTS.
- investigation_steps: exactly 2 follow-up checks an analyst should do next. Each MUST name a specific IP,
  user ID or transaction ID from FACTS (transaction IDs look like T followed by 6 digits). Containment (blocking/locking/freezing) is already handled - do not repeat it.
  Do NOT suggest improving the AI engine, the model, threat intelligence or general processes.
- No markdown. Respond with JSON only, in exactly this shape:
{{"summary": "<2-3 sentences>", "investigation_steps": ["<step 1>", "<step 2>"]}}

FACTS:
{facts}
"""

# Login-only incidents (no transfers) get a prompt with NO money vocabulary at all: the general prompt's talk of
# transfers, merchants and transaction IDs primed the 3B model to invent them on credential-stuffing incidents.
PROMPT_LOGIN = """You are a SOC analyst assistant at a FinTech company. This was a LOGIN attack. Write an incident
report using ONLY the FACTS below.
Rules:
- Do not invent IP addresses, user IDs, counts, times or locations not in FACTS. Copy numbers exactly.
- Always name the affected user ID(s) from "Who".
- {outcome}
- summary: 2-3 sentences in time order: how many failed logins, from which IP and location, against which
  account(s), between which times, and what happened next. End with: "No money moved."
- investigation_steps: exactly 2 follow-up checks an analyst should do next. Each MUST name a specific IP or
  user ID from FACTS. Blocking and password resets are already handled - do not repeat them.
  Do NOT suggest improving the AI engine, the model, threat intelligence or general processes.
- No markdown. Respond with JSON only, in exactly this shape:
{{"summary": "<2-3 sentences>", "investigation_steps": ["<step 1>", "<step 2>"]}}

FACTS:
{facts}
"""


def build_prompt(inc, facts):
    sq = inc.get("sequence", {})
    if sq.get("transfers"):
        return PROMPT.format(facts=facts)
    oks = sq.get("successful_logins", [])
    outcome = (f"The attacker DID get in: successful login to {oks[0]['user']} at {oks[0]['time']}. Say so; do NOT "
               "write that all attempts failed." if oks else
               "Every login attempt FAILED - say that no account was accessed. Do NOT claim anyone logged in.")
    if not sq.get("failed_logins"):     # a single suspicious login: don't let the template talk about failures
        outcome += " There were NO failed logins: do not mention failed logins or attempts at all."
    return PROMPT_LOGIN.format(facts=facts, outcome=outcome)


def mitre_for(inc):
    """MITRE for THIS incident: the attack-type table, plus what the rule engine mapped on its events; T1110 Brute
    Force only when there were failed logins; a parent technique is dropped when its sub-technique is listed."""
    tags = list(MITRE.get(inc["vector"], []))
    if not inc.get("sequence", {}).get("failed_logins"):
        tags = [m for m in tags if not m.startswith("T1110 ")]
    for m in inc.get("rule_mitre", []):
        if m.split()[0] == "T1110" and not inc.get("sequence", {}).get("failed_logins"):
            continue
        if m.split()[0] not in {t.split()[0] for t in tags}:
            tags.append(m)
    ids = {t.split()[0] for t in tags}
    return [t for t in tags if not any(o.startswith(t.split()[0] + ".") for o in ids)]


def five_ws(inc):
    users = ", ".join(inc["users"][:5]) + (f" (+{len(inc['users']) - 5} more)" if len(inc["users"]) > 5 else "")
    return {
        "who": f"User account(s) {users}; source IP(s) {', '.join(inc['ips'][:5])}",
        "what": f"{inc['vector']}: {inc['event_count']} anomalous events"
                + (f", ₹{inc['amount_total']:,.0f} transferred" if inc["amount_total"] else ""),
        "when": f"{inc['start'].replace('T', ' ')} to {inc['end'].replace('T', ' ')}",
        "where": inc["asset"],
        "why_flagged": [r["text"] for r in inc["reasons"]],
    }


def containment_actions(inc):
    """Playbook per attack type, built from the data (not the LLM), proportionate to what actually happened."""
    v, users = inc["vector"], inc["users"]
    sq = inc.get("sequence", {})
    details = inc.get("ip_details") or [{"ip": ip, "threat": inc["ip_threat_level"], "usual_for_user": False}
                                        for ip in inc["ips"]]
    attackers = [d for d in details if not d["usual_for_user"] or d["threat"] != "None"]
    usual = [d for d in details if d not in attackers]
    feed = lambda d: f"threat feed: {d['threat']}" if d["threat"] != "None" else "not on threat feed - flagged by behaviour"
    ok_txn = [t for t in sq.get("transfers", []) if t["status"] == "success"]
    acts = []

    def block_ips(only_feed=False):
        for d in attackers[:5]:
            if only_feed and d["threat"] == "None":
                acts.append(f"Monitor IP {d['ip']} ({feed(d)}); block if it reappears")
            else:
                acts.append(f"Block IP {d['ip']} at WAF/API gateway ({feed(d)})")
        if len(attackers) > 5:
            acts.append(f"Block remaining {len(attackers) - 5} attacker IPs listed in the incident")

    if v == "Account Takeover":
        block_ips()
        acts += [f"Lock account {u}, revoke active sessions and force password reset" for u in users[:5]]
        acts += [f"Freeze/recall transaction {t['id']} (₹{t['amount']:,.0f} to {t.get('merchant', '')})" for t in ok_txn]
    elif v == "Credential Stuffing":
        block_ips()
        acts.append(f"Force password reset for {len(users)} targeted accounts: {', '.join(users[:8])}"
                    + (" ..." if len(users) > 8 else ""))
        acts.append(f"Rate-limit /api/v1/login for source IP(s) {', '.join(d['ip'] for d in attackers[:3])}")
        for o in sq.get("successful_logins", [])[:3]:
            acts.append(f"Revoke the session opened on {o['user']} at {o['time']}")
    elif v == "Brute Force":
        block_ips()
        got_in = sq.get("successful_logins", [])
        for u in users[:3]:
            acts.append(f"Lock account {u} and force password reset" if got_in
                        else f"Temporarily lock {u} after repeated failures and require MFA on next login")
    elif v == "Transaction Anomaly":
        block_ips(only_feed=True)
        acts += [f"Hold transaction {t['id']} (₹{t['amount']:,.0f} to {t.get('merchant', '')}) pending customer "
                 f"confirmation" for t in ok_txn]
        acts += [f"Call {u} on their registered number to confirm the payment" for u in users[:3]]
    else:  # Suspicious Login
        block_ips(only_feed=True)
        acts += [f"Force re-authentication with MFA for {u}" for u in users[:3]]
    for d in usual:
        acts.append(f"Do NOT block {d['ip']} - it is the customer's usual IP; verify the activity with them first")
    return acts


def sequence_line(inc):
    sq = inc.get("sequence", {})
    parts = []                     # in true time order: a login BEFORE the failures is listed first
    timed = []
    if sq.get("failed_logins"):
        a, b = sq["failed_window"]
        timed.append((a, f"{sq['failed_logins']} failed logins between {a} and {b}"))
    for s in sq.get("successful_logins", [])[:2]:
        timed.append((s["time"], f"successful login to {s['user']} at {s['time']} from {s['ip']} ({s['location']})"))
    parts += [t for _, t in sorted(timed, key=lambda x: x[0])]
    if sq.get("failed_logins") and not sq.get("successful_logins"):
        parts.append("NO successful logins (all attempts failed - attacker did not get in)")
    tr = sq.get("transfers", [])
    if tr:
        parts.append(f"{len(tr)} transfer(s): " + ", ".join(
            f"{t['id']} ₹{t['amount']:,.0f} to {t.get('merchant') or 'unknown merchant'} at {t['time']} ({t['status']})"
            for t in tr))
    else:
        parts.append("NO transfers or transactions in this incident (no money moved)")
    return " -> ".join(parts)


def facts_block(inc):
    w = five_ws(inc)
    lines = [
        f"Incident: {inc['id']} | Type: {inc['vector']} | Severity: {inc['sev']} | "
        f"Model confidence: {inc['confidence']}/100 | Impact: {inc['impact']}/100",
        f"Who: {w['who']}", f"Accounts involved: {len(inc['users'])} | Source IPs: {len(inc['ips'])}",
        # every account by ID: with only "(+3 more)" the LLM invented the missing IDs and fell back to the template
        *([f"All accounts: {', '.join(inc['users'][:20])}"] if len(inc["users"]) > 5 else []),
        f"What: {w['what']}", f"When: {w['when']}", f"Where: {w['where']}",
        f"IP threat-intel level: {inc['ip_threat_level']}",
        "Why flagged (top model reasons): " + "; ".join(w["why_flagged"]),
        "Attack sequence: " + sequence_line(inc),
        "Timeline (oldest first):",
    ]
    # Rule Engine rows stay out of the LLM facts: rule names like "Transfer far above the user's average" made the
    # 3B model invent transfers on login-only incidents. Rules reach the report through code (`rule_hits` below).
    lines += [f"  {t['time']} [{t['actor']}] {t['msg']}" for t in reversed(inc["timeline"])
              if t["actor"] != "Rule Engine" and not t["msg"].endswith("not listed")]   # "+N more" note: frontend only
    return "\n".join(lines)


def ask_ollama(prompt, temperature=0.1, timeout=180):
    body = json.dumps({"model": MODEL, "prompt": prompt, "format": "json", "stream": False,
                       "options": {"temperature": temperature, "num_predict": 400}}).encode()
    req = urllib.request.Request(OLLAMA_URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["response"]


DEST_CLAIM = re.compile(r"\b(?:transferr?ed|sent|moved|paid|wired)\b[^.]*?\bto (?:the same|his|her|their|own|"
                        r"the user's|the victim's|another|a different) account\b", re.I)
# allows up to 2 words in between, e.g. "the user then successfully transferred"
OWNER_BLAME = re.compile(r"\bthe (?:user|account owner|customer|victim)(?:\s+[a-z]+){0,2}?\s+"
                         r"(?:transferr?ed|sent|moved|paid|wired|made (?:a |two |the |\w+ )?transfers?)\b", re.I)


MONEY_WORDS = re.compile(r"\b(?:transfer\w*|transactions?|merchants?|funds|payments?|remittance)\b", re.I)
WORD_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
            "ten": 10, "a single": 1, "single": 1}
_N = r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|a single|single)"
TYPED_COUNT = re.compile(
    r"(?<![\d:.,₹])\b" + _N + r"\s+(?:"
    r"(?P<failed>failed\s+(?:log\s?-?ins?|login\s+attempts?|attempts?))|"
    r"(?P<successful>successful\s+(?:log\s?-?ins?|login\s+attempts?))|"
    r"(?P<transfer>(?:\w+\s+)?transfers?)|"
    r"(?P<account>(?:different\s+|user\s+|targeted\s+)?accounts?)|"
    r"(?P<event>anomalous\s+events?))\b", re.I)
NOBODY_IN = re.compile(r"\ball (?:of the )?(?:\w+ )?(?:login )?(?:attempts|logins) (?:failed|were unsuccessful)|\bno account was accessed|"
                       r"\bdid not get in\b|\bno successful logins?\b", re.I)
LOCATION = re.compile(r"\b[A-Z][a-z]+(?: [A-Z][a-z]+)?, [A-Z]{2}\b")
COUNT = re.compile(r"(?<![\d:.])\b(\d+)\s+(?:failed\s+|successful\s+|anomalous\s+|different\s+|user\s+)?"
                   r"(?:log\s?-?ins?|attempts?|accounts?|events?|transfers?|transactions?|IPs?)\b", re.I)
LOGIN_OK = re.compile(r"\bsuccessful(?:ly)?\s+(?:log\s?-?ins?|logged\s+in|authenticat\w*)|\blogged\s+in(?:to)?\b|"
                      r"\bgained\s+access\b|\bcompromised\b", re.I)
FOREIGN_CCY = re.compile(r"\$\s?\d[\d,.]*|\bUSD\b|\bdollars?\b|€\s?\d|\bEUR\b", re.I)
BAD_ID = re.compile(r"\b(?:T\d{1,5}|T\d{7,}|U\d{1,3}|U\d{5,}|[TU]\d+-\d+|[A-Z]\d{3}(?=\)))\b")
USER_AS_TXN = re.compile(r"\btransactions?(?: IDs?)?\s+U\d{4}\b", re.I)
QUOTED = re.compile(r"['\"]([A-Z][A-Za-z0-9 .&-]{1,40})['\"]")


def grounding_check(text, facts, inc=None, summary=None):
    """
    1. Every IP / user ID / transaction ID / rupee amount the LLM wrote must appear in the facts.
    2. No invented money destinations ("transferred ... to the same account") - data only has merchant names.
    3. Transfers must not be blamed on the account owner ("the user transferred") - the attacker made them.
    4. For incidents with 1-3 users, the summary must name the affected user ID(s).
    5. No money talk when no transfers happened; rupees only; no malformed / made-up IDs or names.
    """
    ips = set(re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", text))
    ids = set(re.findall(r"\bU\d{4}\b", text)) | set(re.findall(r"\b[TE]\d{6}\b", text))
    amounts = {a.replace(",", "") for a in re.findall(r"₹\s?([\d,]+)", text)}
    fact_amounts = {a.replace(",", "") for a in re.findall(r"₹\s?([\d,]+)", facts)}
    problems = [x for x in ips | ids if x not in facts] + [f"₹{a}" for a in amounts - fact_amounts]
    problems += [f'claim: "{m.group(0)}"' for m in DEST_CLAIM.finditer(text)]
    problems += [f'blames account owner: "{m.group(0)}"' for m in OWNER_BLAME.finditer(text)]
    # money talk when no money moved (e.g. credential stuffing inventing PayPal/Amazon transfers)
    if inc is not None and not inc.get("sequence", {}).get("transfers"):
        words = sorted({m.group(0).lower() for m in MONEY_WORDS.finditer(text)})
        if words:
            problems.append(f"mentions money movement ({', '.join(words)}) but no transfers occurred")
    if inc is not None and inc.get("sequence", {}).get("failed_logins") and not inc["sequence"].get("successful_logins"):
        hits = sorted({m.group(0).lower() for m in LOGIN_OK.finditer(text)})
        if hits:
            problems.append(f"claims a successful login ({', '.join(hits)}) but all attempts failed")
    problems += [f'non-rupee currency: "{m.group(0)}"' for m in FOREIGN_CCY.finditer(text)]
    problems += [f"malformed ID: {m.group(0)}" for m in BAD_ID.finditer(text)]
    problems += [f'user ID used as transaction: "{m.group(0)}"' for m in USER_AS_TXN.finditer(text)]
    for q in QUOTED.findall(text):                     # quoted names (merchants etc.) must exist in facts
        if q.lower() not in facts.lower():
            problems.append(f"name not in facts: '{q}'")
    # every clock time must be one that appears in the facts
    fact_times = set(re.findall(r"\b\d{2}:\d{2}\b", facts))
    problems += [f"time not in facts: {t}" for t in sorted(set(re.findall(r"\b\d{2}:\d{2}\b", text)) - fact_times)]
    # typed counts: each kind of number must equal ITS OWN true value, not just appear somewhere in the facts
    if inc is not None:
        sq = inc.get("sequence", {})
        stated_fails = {int(n) for n in re.findall(r"(\d+) failed logins", facts)}
        allowed = {
            "failed": {sq.get("failed_logins", 0)} | stated_fails,
            "successful": {len(sq.get("successful_logins", []))},
            "transfer": {len(sq.get("transfers", []))},
            "account": {len(inc["users"])} | {int(n) for n in re.findall(r"touched (\d+) different accounts", facts)},
            "event": {inc["event_count"]},
        }
        for m in TYPED_COUNT.finditer(text):
            n = WORD_NUM.get(m.group(1).lower(), None) if not m.group(1).isdigit() else int(m.group(1))
            kind = next(k for k in ("failed", "successful", "transfer", "account", "event") if m.group(k))
            if n is not None and n not in allowed[kind]:
                problems.append(f'wrong count: "{m.group(0)}" (facts: {sorted(allowed[kind])})')
        if re.search(r"\b(?:0|zero|no)\s+failed\s+(?:log\s?-?ins?|attempts?)\b", text, re.I) and not sq.get("failed_logins"):
            problems.append('mentions failed logins ("0 failed logins") when there were none - leave them out')
        # "and 5 additional/more/other accounts" = the users NOT named in the text (Who lists only 5 of 8)
        if inc is not None:
            named = len({u for u in inc["users"] if u in text})
            for m in re.finditer(r"\b" + _N + r"\s+(?:additional|more|other|further)\s+(?:user\s+)?accounts?\b", text, re.I):
                n = WORD_NUM.get(m.group(1).lower()) if not m.group(1).isdigit() else int(m.group(1))
                if n is not None and n != len(inc["users"]) - named:
                    problems.append(f'wrong count: "{m.group(0)}" ({len(inc["users"])} accounts, {named} named)')
        # durations must match a real gap between two times in the facts
        mins = sorted({int(h) * 60 + int(mm) for h, mm in re.findall(r"\b(\d{2}):(\d{2})\b", facts)})
        gaps = {abs(x - y) for x in mins for y in mins}
        for m in re.finditer(r"\b(\d+)[- ]minutes?\b", text, re.I):
            if int(m.group(1)) not in gaps:
                problems.append(f'duration not in facts: "{m.group(0)}"')
        # contradiction: someone DID get in, but the text says nobody did
        if sq.get("successful_logins"):
            for m in NOBODY_IN.finditer(text):
                problems.append(f'contradiction: "{m.group(0)}" but a login succeeded')
    # places like "Moscow, RU" must exist in the facts
    problems += [f"location not in facts: {m.group(0)}" for m in LOCATION.finditer(text) if m.group(0) not in facts]
    if inc is not None and summary is not None and 0 < len(inc["users"]) <= 3:
        if not any(u in summary for u in inc["users"]):
            problems.append(f"missing user id ({', '.join(inc['users'])}) in summary")
    return {"checked": len(ips) + len(ids) + len(amounts), "unverified": sorted(problems),
            "grounded": not problems}


def template_report(inc):
    """Correct-by-construction summary + steps, built only from incident data. Used when the LLM can't pass."""
    sq = inc.get("sequence", {})
    users, ips = inc["users"], inc["ips"]
    who = ", ".join(users[:5]) + (f" and {len(users) - 5} more" if len(users) > 5 else "")   # same 5 as the facts
    loc = (sq.get("successful_logins") or [{}])[0].get("location") or inc["title"].split(" from ")[-1].split(" Across")[0]
    parts = []
    oks = sq.get("successful_logins", [])
    fail_txt = ok_txt = None
    if sq.get("failed_logins"):
        a, b = sq["failed_window"]
        tgt = f"against {len(users)} accounts ({who})" if len(users) > 1 else f"against {who}"
        fail_txt = f"{sq['failed_logins']} failed logins from {', '.join(ips[:3])} {tgt} between {a} and {b}."
    if oks:
        ok_txt = "Successful login " + "; ".join(f"to {o['user']} at {o['time']} from {o['ip']} ({o['location']})"
                                                 for o in oks[:3]) + "."
    if fail_txt and ok_txt and oks[0]["time"] < sq["failed_window"][0]:
        parts += [ok_txt, "Later, " + fail_txt[0].lower() + fail_txt[1:]]      # keep time order
    else:
        parts += [x for x in (fail_txt, ok_txt) if x]
    if fail_txt and not oks:
        parts.append("All attempts failed; no account was accessed.")
    tr = sq.get("transfers", [])
    if tr:
        who_did = "The attacker then made" if oks or sq.get("failed_logins") else f"{who} made"
        parts.append(f"{who_did} {len(tr)} transfer{'s' if len(tr) > 1 else ''}: " + ", ".join(
            f"{t['id']} ₹{t['amount']:,.0f} to {t.get('merchant') or 'unknown merchant'} at {t['time']} ({t['status']})"
            for t in tr) + ".")
    elif sq.get("failed_logins") or oks:
        parts.append("No money moved.")
    if not parts:   # nothing in sequence: fall back to reasons
        parts.append(f"{inc['vector']} involving {who} from {', '.join(ips[:3])}.")
    parts.append("Flagged because: " + "; ".join(r["text"] for r in inc["reasons"][:3]) + ".")

    ip, u = ips[0], users[0]
    steps = [f"Check all other activity from {ip} in the 24h around this incident for further targets."]
    if tr:
        steps.append(f"Contact {u} to confirm they did not authorise {', '.join(t['id'] for t in tr[:3])}.")
    elif oks:
        steps.append(f"Review sessions and account changes for {oks[0]['user']} after the {oks[0]['time']} login.")
    else:
        steps.append(f"Confirm whether {who} reuse passwords leaked elsewhere and enforce MFA on them.")
    return " ".join(parts), steps


RETRY_NOTE = """
Your previous answer had these problems: {problems}
Write it again and fix them. Name the affected user ID. If there were transfers, say the ATTACKER made them and
only use merchant names from FACTS. If FACTS say NO transfers, do not mention transfers, transactions,
merchants, funds or amounts at all. If FACTS say NO successful logins, say all attempts failed - do not claim
anyone logged in. Only use IDs exactly as written in FACTS."""
RETRY_LOGIN = """
Your previous answer had these problems: {problems}
Write it again and fix them. This was a login attack only: describe the failed logins, the IP, the targeted
account(s) and whether anyone got in, exactly as in FACTS, and end with "No money moved." Only use IDs, counts
and times exactly as written in FACTS."""


def generate(prompt, temperature):
    raw = ask_ollama(prompt, temperature=temperature)
    try:
        llm = json.loads(raw)
    except json.JSONDecodeError:
        llm = {"summary": raw.strip(), "investigation_steps": []}
    summary = str(llm.get("summary", ""))
    steps = [str(x) for x in llm.get("investigation_steps", [])][:2]
    return summary, steps


def summarize(inc, dry_run=False, max_attempts=3):
    facts = facts_block(inc)
    prompt = build_prompt(inc, facts)
    if dry_run:
        print(prompt)
        return None
    t0 = time.time()
    best, attempts = None, []
    for attempt in range(1, max_attempts + 1):
        note = RETRY_NOTE if inc.get("sequence", {}).get("transfers") else RETRY_LOGIN
        p = prompt if attempt == 1 else prompt + note.format(problems="; ".join(best["grounding"]["unverified"]))
        summary, steps = generate(p, temperature=0.1 if attempt == 1 else 0.4)
        g = grounding_check(summary + " " + " ".join(steps), facts, inc, summary)
        attempts.append({"attempt": attempt, "grounded": g["grounded"], "problems": g["unverified"]})
        cand = {"summary": summary, "steps": steps, "grounding": g}
        if best is None or len(g["unverified"]) < len(best["grounding"]["unverified"]):
            best = cand
        if g["grounded"]:
            break
    if best["grounding"]["grounded"]:
        source = "llm" if len(attempts) == 1 else "llm_corrected"
    else:   # LLM never passed: use the deterministic template so no unverified text is published
        t_sum, t_steps = template_report(inc)
        best = {"summary": t_sum, "steps": t_steps,
                "grounding": grounding_check(t_sum + " " + " ".join(t_steps), facts, inc, t_sum)}
        source = "template"
    secs = round(time.time() - t0, 1)
    return {
        "source": source,                                  # llm | llm_corrected | template
        "id": inc["id"], "title": inc["title"], "sev": inc["sev"], "vector": inc["vector"],
        "confidence": inc["confidence"], "impact": inc["impact"],
        "five_ws": five_ws(inc), "mitre": mitre_for(inc),
        "detected_by": inc.get("detected_by", "ml"), "rule_hits": inc.get("rule_hits", []),   # from code, not the LLM
        "pipeline_run_id": inc.get("pipeline_run_id"),
        "summary": best["summary"],
        "containment_actions": containment_actions(inc),   # from data
        "investigation_steps": best["steps"],              # from LLM, grounding-checked
        "recommended_actions": containment_actions(inc) + best["steps"],
        "grounding": best["grounding"],
        "attempts": attempts,                              # self-correction log
        "model": MODEL, "generation_seconds": secs,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=str(Path(__file__).resolve().parent / "output"))
    p.add_argument("--sev", default="critical,high", help="severities to summarise (default: critical,high)")
    p.add_argument("--all", action="store_true", help="summarise all incidents")
    p.add_argument("--top", type=int, help="only the N highest-risk incidents")
    p.add_argument("--id", help="one incident, e.g. INC-2026-0080")
    p.add_argument("--force", action="store_true", help="regenerate reports that already exist")
    p.add_argument("--retry-templates", action="store_true",
                   help="regenerate only cached reports that fell back to the template")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    out = Path(a.out)

    incidents = json.loads((out / "incidents.json").read_text())   # already sorted by risk
    if a.id:
        todo = [i for i in incidents if i["id"] == a.id]
    elif a.all:
        todo = incidents
    else:
        sevs = {x.strip() for x in a.sev.split(",")}
        todo = [i for i in incidents if i["sev"] in sevs]
    if a.top:
        todo = todo[:a.top]
    if not todo:
        raise SystemExit("No matching incidents")

    if a.dry_run:
        summarize(todo[0], dry_run=True)
        return

    # cache: keep existing reports, only generate missing ones (unless --force)
    path = out / "reports.json"
    cache = {r["id"]: r for r in json.loads(path.read_text())} if path.exists() else {}
    cache = {k: v for k, v in cache.items() if "source" in v}            # drop reports from older script versions
    # drop reports whose incident no longer exists or changed (IDs can be renumbered by incidents.py): the backend
    # serves reports.json by ID, so a stale report would tell the wrong story for that ID
    by_id = {i["id"]: i for i in incidents}
    gone = [k for k, r in cache.items() if k not in by_id or r.get("title") != by_id[k]["title"]
            or not grounding_check(r["summary"] + " " + " ".join(r["investigation_steps"]),
                                   facts_block(by_id[k]), by_id[k], r["summary"])["grounded"]]
    gone = [k for k in gone if k not in {i["id"] for i in todo}]       # selected ones are regenerated below
    for k in gone:
        del cache[k]
    if gone:
        print(f"   dropped {len(gone)} stale reports (incident renumbered or changed)")
        path.write_text(json.dumps(list(cache.values()), indent=2, ensure_ascii=False))
    # re-verify cached reports against the CURRENT checks + incident data; regenerate any that no longer pass
    stale = []
    for inc in todo:
        r = cache.get(inc["id"])
        if r and not a.force:
            g = grounding_check(r["summary"] + " " + " ".join(r["investigation_steps"]), facts_block(inc), inc, r["summary"])
            if not g["grounded"] or r.get("title") != inc["title"]:
                stale.append(inc["id"])
                print(f"   re-check failed for cached {inc['id']}: {g['unverified'] or 'incident changed'} -> regenerating")
    # code-built fields (MITRE, containment, 5 Ws, severity, rule hits) are refreshed on cached reports every run,
    # so a change in the playbook or the rule merge reaches them without regenerating the LLM text
    for inc in todo:
        r = cache.get(inc["id"])
        if r and inc["id"] not in stale:
            r.update({"sev": inc["sev"], "vector": inc["vector"], "confidence": inc["confidence"], "impact": inc["impact"],
                      "five_ws": five_ws(inc), "mitre": mitre_for(inc),
                      "containment_actions": containment_actions(inc),
                      "detected_by": inc.get("detected_by", "ml"), "rule_hits": inc.get("rule_hits", []),
                      "pipeline_run_id": inc.get("pipeline_run_id")})
    path.write_text(json.dumps(list(cache.values()), indent=2, ensure_ascii=False))
    pending = [i for i in todo if a.force or i["id"] not in cache or i["id"] in stale
               or (a.retry_templates and cache[i["id"]].get("source") == "template")]
    print(f"{len(todo)} incidents selected | {len(todo) - len(pending)} cached & re-verified | {len(pending)} to generate")

    done = []
    for n, inc in enumerate(pending, 1):
        try:
            r = summarize(inc)
        except urllib.error.URLError as e:
            raise SystemExit(f"Can't reach Ollama at {OLLAMA_URL} ({e.reason}). Is `ollama serve` running?")
        cache[r["id"]] = r
        done.append(r)
        path.write_text(json.dumps(list(cache.values()), indent=2, ensure_ascii=False))   # save as we go
        flag = "OK" if r["grounding"]["grounded"] else f"UNVERIFIED {r['grounding']['unverified']}"
        flag += {"llm": "", "llm_corrected": f" after {len(r['attempts'])} attempts",
                 "template": " - LLM failed 3x, used verified template"}[r["source"]]
        print(f"\n[{n}/{len(pending)}] {r['id']} [{r['sev']}] {r['title']}  ({r['generation_seconds']}s, grounding: {flag})")
        for att in (r["attempts"] if r["source"] == "template" else r["attempts"][:-1]):
            print(f"   (attempt {att['attempt']} rejected: {att['problems']})")
        print("  " + r["summary"])
        for act in r["containment_actions"]:
            print("   [contain] " + act)
        for st in r["investigation_steps"]:
            print("   [investigate] " + st)

    # stats over everything selected (new + cached)
    sel = [cache[i["id"]] for i in todo if i["id"] in cache]
    n = len(sel)
    from collections import Counter
    src = Counter(r["source"] for r in sel)
    final = sum(r["grounding"]["grounded"] for r in sel)
    avg = sum(r.get("generation_seconds", 0) for r in sel) / n
    print(f"\nSaved -> {path}  ({len(cache)} reports total)")
    print(f"FINAL: {final}/{n} reports verified ({100 * final / n:.0f}%) | avg {avg:.1f}s per report")
    print(f"  LLM passed first try: {src['llm']}/{n} | after self-correction: {src['llm'] + src['llm_corrected']}/{n}"
          f" | template fallback: {src['template']}/{n}")
    by_vec = {}
    for r in sel:
        by_vec.setdefault(r["vector"], Counter())[r["source"]] += 1
    for v, c in sorted(by_vec.items(), key=lambda x: -sum(x[1].values())):
        t = sum(c.values())
        print(f"   {v:20} {t:3} | llm {c['llm']:3} | llm_corrected {c['llm_corrected']:3} | template {c['template']:3}")


if __name__ == "__main__":
    main()
