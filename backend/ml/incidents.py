"""
Sentra / FSIA - AI/ML module, step 3: group anomalous events into incidents.

Output = backend/ml/output/incidents.json, shaped like the frontend's IncidentsPage `ALL` array
(id, sev, status, title, asset, ip, analyst, vector, created, confidence, impact) plus extra
fields the backend / LLM step use (timeline, reasons, users, events, amounts).

Grouping:
  pass 1 (per IP)  : >=3 different accounts hit from one IP within 2h      -> Credential Stuffing
  pass 2 (per user): remaining events for one user within 24h, classified:
                     login + transaction        -> Account Takeover
                     repeated failed logins     -> Brute Force
                     other suspicious logins    -> Suspicious Login
                     transaction(s) only        -> Transaction Anomaly

Hybrid detection: the rule engine in fsia_cyber/ (Aarushi) runs on the same raw data. Its alerts are merged in:
  - every incident gets `rule_hits` (which rules fired on its events) and `detected_by` (ml / rules / ml+rules)
  - events a strong rule flagged but the model scored below threshold are added to the pool (rules-only catches)
  - severity = the higher of the ML severity and the rule engine's severity; rule-confirmed incidents skip the
    noise filter. If fsia_cyber/ is missing the script still runs ML-only (`--no-rules` forces that).

Run (from repo root):  python backend/ml/incidents.py
"""
import argparse
import importlib.util
import json
from pathlib import Path

import pandas as pd

try:
    from .features import AUTH_THRESHOLD, TXN_THRESHOLD     # single source of truth (model.py uses them too)
except ImportError:
    from features import AUTH_THRESHOLD, TXN_THRESHOLD

BASE_IMPACT = {"Account Takeover": 70, "Credential Stuffing": 60, "Brute Force": 50,
               "Transaction Anomaly": 45, "Suspicious Login": 35}
ASSET = {"login": "auth-service /api/v1/login", "txn": "payments-api /api/v1/transfer"}
COLOR = {"ai": "#7c3aed", "auth_fail": "#dc2626", "auth_ok": "#d97706", "txn": "#2563eb", "intel": "#64748b"}
THREAT_NAME = {1: "Low", 2: "Medium", 3: "High"}
ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent / "output"
RULE_NAMES = {   # no thresholds/numbers in the names: they reach the LLM facts and must not look like counts
    "R_BRUTE_FORCE": "Brute force on one account", "R_FAIL_THEN_SUCCESS": "Failed logins then a success",
    "R_NEW_DEVICE_LOGIN": "Login from an unregistered device", "R_NEW_LOCATION": "Login from a new IP and city",
    "R_TI_MATCH": "Login from a Medium/High threat-intel IP", "R_IMPOSSIBLE_TRAVEL_CANDIDATE": "Possible impossible travel",
    "R_LARGE_TXN": "Transfer far above the user's average", "R_NEW_BENEFICIARY": "Transfer to a new beneficiary",
    "R_MULTI_ACCOUNT_IP": "One IP trying many accounts",
}
WEAK_RULES = {"R_IMPOSSIBLE_TRAVEL_CANDIDATE", "R_NEW_BENEFICIARY"}   # context only: annotate, never create incidents
SEV_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
COLOR["rule"] = "#0891b2"


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)     # by file path: fsia_cyber has its own evaluate.py
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def rule_alerts(data_dir: Path):
    """Run the fsia_cyber rule engine. Returns {event_id: [{rule, severity, attack}]} or None if unavailable."""
    try:
        R = _module("fsia_rules", ROOT / "fsia_cyber" / "rules.py")
        C = _module("fsia_correlate", ROOT / "fsia_cyber" / "correlate.py")
    except FileNotFoundError:
        print("note: fsia_cyber/ not found - running ML-only")
        return None
    logs = R.load(str(data_dir))
    alerts = R.run_all(*logs)
    hits = {}
    for inc in C.correlate(alerts):
        for al in inc["alerts"]:
            for e in al["event_ids"]:
                hits.setdefault(e, []).append({"rule": al["rule"], "severity": inc["severity"].lower(),
                                               "attack": inc["attack_type"],
                                               "mitre": [f"{m['id']} {m['name']}" for m in inc["mitre"]]})
    print(f"rule engine: {len(alerts)} alerts on {len(hits)} events")
    export_rule_alerts(hits, logs, OUT_DIR)
    return hits


def export_rule_alerts(hits, logs, out):
    """output/rule_alerts.csv: one row per (event, rule), the shape of the backend's rule_alerts table:
    event_id, rule_id, rule_name, severity, timestamp. severity = the rule engine's severity for the attack the
    alert belongs to (lowercase)."""
    a, t = logs[0], logs[1]
    ts = {**dict(zip(a.event_id, a.timestamp)), **dict(zip(t.transaction_id, t.timestamp))}
    rows = {}
    for e, hs in hits.items():
        for h in hs:
            k = (e, h["rule"])
            if k not in rows or SEV_RANK[h["severity"]] > SEV_RANK[rows[k]["severity"]]:
                rows[k] = {"event_id": e, "rule_id": h["rule"], "rule_name": RULE_NAMES.get(h["rule"], h["rule"]),
                           "severity": h["severity"], "timestamp": str(ts.get(e, ""))}
    df = pd.DataFrame(list(rows.values())).sort_values(["timestamp", "event_id", "rule_id"])
    df.to_csv(out / "rule_alerts.csv", index=False)


def load(out: Path, hits=None):
    """Events the model flagged, plus events a strong rule flagged (hybrid). `by_ml` marks which is which."""
    strong = {e for e, hs in (hits or {}).items() if any(h["rule"] not in WEAK_RULES for h in hs)}
    a = pd.read_csv(out / "scored_auth.csv", parse_dates=["timestamp"])
    t = pd.read_csv(out / "scored_txn.csv", parse_dates=["timestamp"])
    for df, th in ((a, AUTH_THRESHOLD), (t, TXN_THRESHOLD)):     # is_flagged = score cutoff + model.py guards
        df["by_ml"] = df.is_flagged.astype(bool) if "is_flagged" in df else df.anomaly_score >= th
    a = a[a.by_ml | a.event_id.isin(strong)].assign(kind="login", eid=lambda d: d.event_id, amount=0.0, merchant="")
    t = t[t.by_ml | t.transaction_id.isin(strong)].assign(kind="txn", eid=lambda d: d.transaction_id)
    cols = ["eid", "kind", "timestamp", "user_id", "ip_address", "device_id", "location", "status",
            "amount", "merchant", "anomaly_score", "top_reasons", "ip_threat_score", "is_new_device",
            "failed_logins_user_1h", "beneficiary_added_24h", "ip_not_usual", "amount_ratio", "by_ml"]
    for df in (a, t):
        for c in cols:
            if c not in df:
                df[c] = 0
    return pd.concat([a[cols], t[cols]], ignore_index=True).sort_values("timestamp")


def sessions(df, key, gap):
    """Split each key's events into sessions: new session when the time gap exceeds `gap`."""
    df = df.sort_values([key, "timestamp"])
    new = (df[key] != df[key].shift()) | (df.timestamp.diff() > pd.Timedelta(gap))
    return new.cumsum()


def split_by_order(g):
    """A takeover needs the suspicious login FIRST. Transfers that happened before the first suspicious login
    (e.g. the customer's own payment from their usual IP, then an odd login the next day) become their own incident."""
    if set(g.kind) == {"login", "txn"}:
        first_login = g.loc[g.kind == "login", "timestamp"].min()
        pre = g[(g.kind == "txn") & (g.timestamp < first_login)]
        if len(pre):
            return [pre, g.drop(pre.index)]
    return [g]


def noise_reason(g, vector):
    """Low-value alerts found in the analyst review -> watch-list instead of incident list."""
    if vector == "Transaction Anomaly" and (g.status == "failed").all() and g.amount_ratio.max() < 5:
        return "only failed, small payments (declined card/bill), < 5x the user's normal amount"
    if vector == "Suspicious Login" and (g.ip_not_usual == 0).all() and (g.is_new_device == 0).all() \
            and g.ip_threat_score.max() <= 1:
        return "login activity from the user's usual IP on a registered device (no Medium/High threat intel)"
    return None


def classify(g):
    kinds = set(g.kind)
    if kinds == {"login", "txn"} or (kinds == {"txn"} and (g.is_new_device.max() or g.beneficiary_added_24h.max())):
        return "Account Takeover"
    if kinds == {"txn"}:
        return "Transaction Anomaly"
    if g.failed_logins_user_1h.max() >= 5:
        return "Brute Force"
    return "Suspicious Login"


def title(vector, g):
    users = g.user_id.nunique()
    money = g.loc[g.kind == "txn", "amount"].sum()
    loc = g.location.mode().iat[0]
    fails = int((g.status == "failed").sum())
    return {
        "Credential Stuffing": f"Credential Stuffing from {loc} Across {users} Accounts",
        "Account Takeover": f"Account Takeover: ₹{money:,.0f} Transferred After Suspicious Access",
        "Brute Force": f"Brute-Force Login Attempts on Account {g.user_id.iat[0]} ({fails} failures)",
        "Suspicious Login": f"Suspicious Login to {g.user_id.iat[0]} from {loc}",
        "Transaction Anomaly": f"Anomalous Transfer of ₹{money:,.0f} by {g.user_id.iat[0]}",
    }[vector]


def time_fmt(g):
    """HH:MM, or MM-DD HH:MM when the incident spans more than one day (so order can't be misread)."""
    multi = g.timestamp.dt.date.nunique() > 1
    return (lambda ts: ts.strftime("%m-%d %H:%M")) if multi else (lambda ts: ts.strftime("%H:%M"))


def timeline(g):
    hm = time_fmt(g)
    rows = []
    max_threat = int(g.ip_threat_score.max())
    if max_threat:
        ip = g.loc[g.ip_threat_score.idxmax(), "ip_address"]
        rows.append({"time": hm(g.timestamp.min()), "actor": "Threat Intel",
                     "msg": f"{ip} matches threat feed ({THREAT_NAME[max_threat]})", "color": COLOR["intel"]})
    g = g.sort_values("timestamp")
    # cap so big stuffing waves stay readable, but never drop a successful login or a transfer (the LLM reads this:
    # a timeline that shows only failures made it write "all attempts failed")
    key = (g.kind == "txn") | (g.status == "success")
    shown = g[key | g.index.isin(g[~key].head(max(0, 12 - int(key.sum()))).index)]
    hidden = int((~g.index.isin(shown.index) & (g.kind == "login") & (g.status == "failed")).sum())
    if hidden:
        rows.append({"time": hm(g[~g.index.isin(shown.index)].timestamp.min()), "actor": "Auth Service",
                     "msg": f"+{hidden} more failed logins not listed", "color": COLOR["auth_fail"]})
    for _, r in shown.iterrows():
        if r.kind == "login":
            ok = r.status == "success"
            rows.append({"time": hm(r.timestamp), "actor": "Auth Service",
                         "msg": f"{'Successful' if ok else 'Failed'} login {r.user_id} from {r.ip_address} ({r.location})",
                         "color": COLOR["auth_ok" if ok else "auth_fail"]})
        else:
            rows.append({"time": hm(r.timestamp), "actor": "Payments API",
                         "msg": f"Transfer {r.eid} ₹{r.amount:,.0f} by {r.user_id} to {r.merchant} ({r.status})",
                         "color": COLOR["txn"]})
    for rule, (ts, n) in sorted(rule_summary(g).items(), key=lambda kv: kv[1][0]):
        rows.append({"time": hm(ts), "actor": "Rule Engine", "msg": f"Rule {rule} fired: {RULE_NAMES.get(rule, rule)}",
                     "color": COLOR["rule"]})
    rows.sort(key=lambda r: r["time"])
    rows.append({"time": hm(g.timestamp.max()), "actor": "AI Engine",
                 "msg": f"Correlated {len(g)} anomalous events (max anomaly score {g.anomaly_score.max():.0f})",
                 "color": COLOR["ai"]})
    return rows[::-1]   # newest first, same as frontend mock


def rule_summary(g):
    """{rule: (first time it fired in this incident, number of events)} from the `rule_hits` column."""
    out = {}
    for ts, hs in zip(g.timestamp, g.rule_hits):
        for h in hs:
            first, n = out.get(h["rule"], (ts, 0))
            out[h["rule"]] = (min(first, ts), n + 1)
    return out


def reasons(g):
    """Most frequent SHAP reasons across the incident's events."""
    feats = {}
    for js in g.top_reasons:
        for r in json.loads(js):
            f = feats.setdefault(r["feature"], {"feature": r["feature"], "impact": 0.0, "text": r["text"],
                                                 "count": 0, "_best": -1.0})
            f["impact"] += r["impact"]; f["count"] += 1
            if r["impact"] > f["_best"]:          # keep the text of the event where this feature mattered most
                f["_best"], f["text"] = r["impact"], r["text"]
    top = sorted(feats.values(), key=lambda x: -x["impact"])[:4]
    for f in top:
        f["impact"] = round(f["impact"] / f["count"], 3)
        del f["_best"]
    return top


def sequence(g):
    """Explicit attack-sequence facts (counts, times, IDs) so the LLM narrates them instead of guessing."""
    logins = g[g.kind == "login"].sort_values("timestamp")
    fails, ok = logins[logins.status == "failed"], logins[logins.status == "success"]
    txns = g[g.kind == "txn"].sort_values("timestamp")
    hm = time_fmt(g)
    return {
        "failed_logins": int(len(fails)),
        "failed_window": [hm(fails.timestamp.min()), hm(fails.timestamp.max())] if len(fails) else None,
        "successful_logins": [{"time": hm(r.timestamp), "user": r.user_id, "ip": r.ip_address, "location": r.location}
                              for _, r in ok.iterrows()][:5],
        "transfers": [{"id": r.eid, "time": hm(r.timestamp), "amount": float(r.amount), "merchant": r.merchant,
                       "status": r.status}
                      for _, r in txns.iterrows()][:10],
    }


def build_incident(g, vector):
    money = float(g.loc[g.kind == "txn", "amount"].sum())
    max_threat = int(g.ip_threat_score.max())
    success_after_fail = bool(((g.kind == "login") & (g.status == "success")).any() and (g.status == "failed").any())
    confidence = int(round(g.anomaly_score.max()))
    impact = BASE_IMPACT[vector] + min(20, money / 50000 * 20) + (5 if max_threat == 3 else 0) \
        + (10 if success_after_fail else 0) + min(10, g.user_id.nunique() - 1)
    impact = int(min(99, round(impact)))
    risk = 0.5 * confidence + 0.5 * impact
    sev = "critical" if risk >= 85 else "high" if risk >= 75 else "medium" if risk >= 65 else "low"
    rules = rule_summary(g)
    rule_sev = max((h["severity"] for hs in g.rule_hits for h in hs if h["rule"] not in WEAK_RULES),
                   key=SEV_RANK.get, default="low")
    ml_sev = sev
    if SEV_RANK[rule_sev] > SEV_RANK[sev]:
        sev = rule_sev
    by_ml, by_rule = bool(g.by_ml.any()), any(r not in WEAK_RULES for r in rules)
    main_ip = g.ip_address.mode().iat[0]
    return {
        "sev": sev, "status": "OPEN", "title": title(vector, g),
        "asset": ASSET["txn" if (g.kind == "txn").any() else "login"],
        "ip": main_ip, "analyst": "Unassigned", "vector": vector,
        "created": g.timestamp.min().strftime("%H:%M"),
        "confidence": confidence, "impact": impact, "risk_score": round(risk, 1),
        # extra context for backend + LLM summary step
        "start": g.timestamp.min().isoformat(), "end": g.timestamp.max().isoformat(),
        "users": sorted(g.user_id.unique().tolist()), "ips": sorted(g.ip_address.unique().tolist()),
        "event_ids": g.eid.tolist(), "event_count": len(g), "amount_total": money,
        "ip_threat_level": THREAT_NAME.get(max_threat, "None"),
        "ip_details": [{"ip": ip, "threat": THREAT_NAME.get(int(d.ip_threat_score.max()), "None"),
                        "usual_for_user": bool((d.ip_not_usual == 0).all())}
                       for ip, d in g.groupby("ip_address")],
        "reasons": reasons(g), "sequence": sequence(g), "timeline": timeline(g),
        # hybrid detection
        "detected_by": "ml+rules" if by_ml and by_rule else "ml" if by_ml else "rules",
        "ml_severity": ml_sev, "rule_severity": rule_sev if by_rule else None,
        "rule_hits": [{"rule": r, "name": RULE_NAMES.get(r, r), "events": n, "first": ts.isoformat()}
                      for r, (ts, n) in sorted(rules.items(), key=lambda kv: kv[1][0])],
        "ml_event_ids": g.loc[g.by_ml, "eid"].tolist(),
        "rule_mitre": sorted({m for hs in g.rule_hits for h in hs if h["rule"] not in WEAK_RULES
                              for m in h.get("mitre", [])}),
    }


def add_frontend_fields(incidents, data_dir: Path):
    """Fields the Incidents page shows that aren't detection output:
    threat_intel / threat_actor -> the "Threat Actor" card (from the threat feed, worst-level IP of the incident)
    ai_summary                  -> the "AI Analysis" paragraph for EVERY incident (code-built, verified facts;
                                   the backend can swap in the LLM summary from reports.json when one exists)"""
    try:
        from . import summarize as S
    except ImportError:
        import summarize as S
    ti_path = data_dir / "processed" / "threat_indicators.csv"
    ti = pd.read_csv(ti_path if ti_path.exists() else data_dir / "threat_indicators.csv")
    rank = {"High": 3, "Medium": 2, "Low": 1}
    ti = ti.assign(r=ti.threat_level.map(rank)).sort_values("r", ascending=False).drop_duplicates("ip_address")
    feed = ti.set_index("ip_address")
    for inc in incidents:
        hits = [ip for ip in inc["ips"] if ip in feed.index]
        if hits:
            ip = max(hits, key=lambda x: feed.loc[x, "r"])
            f = feed.loc[ip]
            inc["threat_intel"] = {"ip": ip, "level": f.threat_level, "description": f.description, "source": f.source,
                                   "last_seen": f.last_seen}
            inc["threat_actor"] = f"{f.description} ({f.source}, {f.threat_level})"
        else:
            inc["threat_intel"] = None
            inc["threat_actor"] = "Unknown - IP not on any threat feed"
        inc["ai_summary"] = S.template_report(inc)[0]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=str(Path(__file__).resolve().parent / "output"))
    p.add_argument("--data", default=str(ROOT / "data"), help="raw CSVs for the rule engine")
    p.add_argument("--no-rules", action="store_true", help="ML only (skip the fsia_cyber rule engine)")
    a = p.parse_args()
    out = Path(a.out)

    global OUT_DIR
    OUT_DIR = out
    hits = None if a.no_rules else rule_alerts(Path(a.data))
    ev = load(out, hits)
    ev["rule_hits"] = ev.eid.map(lambda e: (hits or {}).get(e, []))
    incidents = []

    # pass 1: credential stuffing (one IP, many accounts, short window)
    logins = ev[ev.kind == "login"].copy()
    logins["sess"] = sessions(logins, "ip_address", "2h")
    used = set()
    for _, g in logins.groupby("sess"):
        if g.user_id.nunique() >= 3:
            incidents.append(build_incident(g, "Credential Stuffing"))
            used |= set(g.eid)

    # pass 2: per-user sessions for everything else
    rest = ev[~ev.eid.isin(used)].copy()
    rest["sess"] = sessions(rest, "user_id", "24h")
    for _, g in rest.groupby("sess"):
        for part in split_by_order(g):
            v = classify(part)
            inc = build_incident(part, v)
            inc["_noise"] = None if inc["rule_severity"] else noise_reason(part, v)   # rule-confirmed: keep
            # hybrid triage: low severity and no rule agrees -> watch list (all 9 such were false alarms vs the key)
            if hits is not None and not inc["_noise"] and inc["detected_by"] == "ml" and inc["sev"] == "low":
                inc["_noise"] = "low severity and not confirmed by any rule (ML-only)"
            incidents.append(inc)

    incidents.sort(key=lambda x: x["start"])
    for i, inc in enumerate(incidents, 1):
        inc["id"] = f"INC-2026-{i:04d}"
    incidents.sort(key=lambda x: -x["risk_score"])
    incidents = [{"id": x.pop("id"), **x} for x in incidents]

    add_frontend_fields(incidents, Path(a.data))

    # IDs are assigned BEFORE filtering, so kept incidents keep the same ID with or without the filter
    watch = [{"id": x["id"], "vector": x["vector"], "reason": x["_noise"], "users": x["users"], "ips": x["ips"],
              "start": x["start"], "event_ids": x["event_ids"], "sev": x["sev"],
              "ml_event_ids": x.get("ml_event_ids", x["event_ids"]),
              "unconfirmed": x["_noise"].startswith("low severity and not confirmed")}
             for x in incidents if x.get("_noise")]
    incidents = [{k: v for k, v in x.items() if k != "_noise"} for x in incidents if not x.get("_noise")]
    # pipeline_run_id: a fingerprint of the exact incident set (IDs + their events). Same data + code -> same id,
    # so the backend can tell whether a stored INC-... still means the same incident after a rerun.
    import hashlib, datetime
    run_id = hashlib.sha256(json.dumps([(x["id"], x["event_ids"]) for x in incidents]).encode()).hexdigest()[:12]
    for x in incidents:
        x["pipeline_run_id"] = run_id
    (out / "pipeline_run.json").write_text(json.dumps({
        "pipeline_run_id": run_id, "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "incidents": len(incidents), "watchlist": len(watch), "rules_used": hits is not None}, indent=2))
    (out / "watchlist.json").write_text(json.dumps(watch, indent=2, ensure_ascii=False))
    (out / "incidents.json").write_text(json.dumps(incidents, indent=2, ensure_ascii=False))

    df = pd.DataFrame(incidents)
    from collections import Counter
    wc = Counter(w["vector"] for w in watch)
    print(f"{len(ev)} anomalous events -> {len(df)} incidents  (+{len(watch)} low-value moved to watchlist.json: "
          + ", ".join(f"{n} {v}" for v, n in wc.items()) + ")\n")
    print("detected by:", df.detected_by.value_counts().to_dict(), "\n")
    print(pd.crosstab(df.vector, df.sev)[[s for s in ["critical", "high", "medium", "low"] if s in df.sev.values]], "\n")
    for x in incidents[:8]:
        print(f"{x['id']}  {x['sev']:8} conf={x['confidence']:3} impact={x['impact']:3}  {x['title']}")


if __name__ == "__main__":
    main()
