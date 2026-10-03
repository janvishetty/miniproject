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

Run (from repo root):  python backend/ml/incidents.py
"""
import argparse
import json
from pathlib import Path

import pandas as pd

AUTH_THRESHOLD = 70   # login scores 60-70 are mostly single mistyped passwords (checked by score band)
TXN_THRESHOLD = 60

BASE_IMPACT = {"Account Takeover": 70, "Credential Stuffing": 60, "Brute Force": 50,
               "Transaction Anomaly": 45, "Suspicious Login": 35}
ASSET = {"login": "auth-service /api/v1/login", "txn": "payments-api /api/v1/transfer"}
COLOR = {"ai": "#7c3aed", "auth_fail": "#dc2626", "auth_ok": "#d97706", "txn": "#2563eb", "intel": "#64748b"}
THREAT_NAME = {1: "Low", 2: "Medium", 3: "High"}


def load(out: Path):
    a = pd.read_csv(out / "scored_auth.csv", parse_dates=["timestamp"])
    t = pd.read_csv(out / "scored_txn.csv", parse_dates=["timestamp"])
    a = a[a.anomaly_score >= AUTH_THRESHOLD].assign(kind="login", eid=lambda d: d.event_id, amount=0.0, merchant="")
    t = t[t.anomaly_score >= TXN_THRESHOLD].assign(kind="txn", eid=lambda d: d.transaction_id)
    cols = ["eid", "kind", "timestamp", "user_id", "ip_address", "device_id", "location", "status",
            "amount", "merchant", "anomaly_score", "top_reasons", "ip_threat_score", "is_new_device",
            "failed_logins_user_1h", "beneficiary_added_24h", "ip_not_usual", "amount_ratio"]
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
    for _, r in g.sort_values("timestamp").head(12).iterrows():   # cap so big stuffing waves stay readable
        if r.kind == "login":
            ok = r.status == "success"
            rows.append({"time": hm(r.timestamp), "actor": "Auth Service",
                         "msg": f"{'Successful' if ok else 'Failed'} login {r.user_id} from {r.ip_address} ({r.location})",
                         "color": COLOR["auth_ok" if ok else "auth_fail"]})
        else:
            rows.append({"time": hm(r.timestamp), "actor": "Payments API",
                         "msg": f"Transfer {r.eid} ₹{r.amount:,.0f} by {r.user_id} to {r.merchant} ({r.status})",
                         "color": COLOR["txn"]})
    rows.append({"time": hm(g.timestamp.max()), "actor": "AI Engine",
                 "msg": f"Correlated {len(g)} anomalous events (max anomaly score {g.anomaly_score.max():.0f})",
                 "color": COLOR["ai"]})
    return rows[::-1]   # newest first, same as frontend mock


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
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=str(Path(__file__).resolve().parent / "output"))
    out = Path(p.parse_args().out)

    ev = load(out)
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
            inc["_noise"] = noise_reason(part, v)
            incidents.append(inc)

    incidents.sort(key=lambda x: x["start"])
    for i, inc in enumerate(incidents, 1):
        inc["id"] = f"INC-2026-{i:04d}"
    incidents.sort(key=lambda x: -x["risk_score"])
    incidents = [{"id": x.pop("id"), **x} for x in incidents]

    # IDs are assigned BEFORE filtering, so kept incidents keep the same ID with or without the filter
    watch = [{"id": x["id"], "vector": x["vector"], "reason": x["_noise"], "users": x["users"], "ips": x["ips"],
              "start": x["start"], "event_ids": x["event_ids"]} for x in incidents if x.get("_noise")]
    incidents = [{k: v for k, v in x.items() if k != "_noise"} for x in incidents if not x.get("_noise")]
    (out / "watchlist.json").write_text(json.dumps(watch, indent=2, ensure_ascii=False))
    (out / "incidents.json").write_text(json.dumps(incidents, indent=2, ensure_ascii=False))

    df = pd.DataFrame(incidents)
    from collections import Counter
    wc = Counter(w["vector"] for w in watch)
    print(f"{len(ev)} anomalous events -> {len(df)} incidents  (+{len(watch)} low-value moved to watchlist.json: "
          + ", ".join(f"{n} {v}" for v, n in wc.items()) + ")\n")
    print(pd.crosstab(df.vector, df.sev)[[s for s in ["critical", "high", "medium", "low"] if s in df.sev.values]], "\n")
    for x in incidents[:8]:
        print(f"{x['id']}  {x['sev']:8} conf={x['confidence']:3} impact={x['impact']:3}  {x['title']}")


if __name__ == "__main__":
    main()
