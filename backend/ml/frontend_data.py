"""
Sentra / FSIA - AI/ML module, step 6: data for the frontend Dashboard page -> output/dashboard.json

Shaped like the mock constants in frontend/src/DashboardPage.tsx, so the backend can serve it as-is:
  stats       -> the 4 StatCards (active incidents, critical count, platform risk score, events analysed)
  risk_map    -> RISK_NODES  [{id, score, tag, alerts, risk}]  one node per API endpoint (api_logs.csv): the
                 incidents whose attacker IPs called that endpoint during the attack, their mean risk score
  live_events -> STREAM_POOL [{ts, node, msg, type}]  newest first, the flagged events behind the incidents
  recent      -> RECENT      [{id, sev, title, time, status}]  the latest incidents
  by_type / by_severity -> counts for any chart

No LLM: everything is computed from incidents.json + the logs, so it is exact and instant.
Run (from repo root, after incidents.py):  python backend/ml/frontend_data.py
"""
import argparse
import json
from collections import Counter
from pathlib import Path

import pandas as pd

ML = Path(__file__).resolve().parent
ROOT = ML.parents[1]
SEV_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
TAG = {"/api/v1/login": "AUTH", "/api/v1/logout": "AUTH", "/api/v1/transfer": "PAYMENTS",
       "/api/v1/beneficiaries": "PAYEES", "/api/v1/accounts/balance": "ACCOUNTS",
       "/api/v1/transactions/history": "HISTORY", "/api/v1/profile": "PROFILE"}
NAME = {"/api/v1/login": "Login API", "/api/v1/logout": "Logout API", "/api/v1/transfer": "Transfer API",
        "/api/v1/beneficiaries": "Beneficiaries API", "/api/v1/accounts/balance": "Balance API",
        "/api/v1/transactions/history": "Transaction History API", "/api/v1/profile": "Profile API"}


def risk_level(score):
    return "critical" if score >= 85 else "high" if score >= 75 else "medium" if score >= 65 else "low"


def risk_map(incidents, api):
    """For each endpoint: which incidents' attacker IPs called it during the attack window (+1h after)."""
    api = api.assign(timestamp=pd.to_datetime(api.timestamp))
    hits = {e: [] for e in api.endpoint.unique()}
    for inc in incidents:
        attacker = [d["ip"] for d in inc.get("ip_details", []) if not d["usual_for_user"]] or inc["ips"]
        start, end = pd.Timestamp(inc["start"]), pd.Timestamp(inc["end"]) + pd.Timedelta(hours=1)
        rows = api[api.ip_address.isin(attacker) & api.timestamp.between(start, end)]
        for e in rows.endpoint.unique():
            hits[e].append(inc)
    nodes = []
    for e, incs in hits.items():
        score = int(round(sum(i["risk_score"] for i in incs) / len(incs))) if incs else 0   # mean risk
        nodes.append({"id": NAME.get(e, e), "endpoint": e, "tag": TAG.get(e, "API"), "score": score,
                      "alerts": len(incs), "risk": risk_level(score) if incs else "low",
                      "incidents": [i["id"] for i in sorted(incs, key=lambda x: -x["risk_score"])][:10]})
    return sorted(nodes, key=lambda n: (-n["score"], -n["alerts"]))


def live_events(incidents, out, n=50):
    """The flagged events behind the incidents, newest first, in the dashboard feed's shape."""
    a = pd.read_csv(out / "scored_auth.csv")
    t = pd.read_csv(out / "scored_txn.csv")
    owner = {e: i for i in incidents for e in i["event_ids"]}
    rows = []
    for r in a[a.event_id.isin(owner)].itertuples():
        inc = owner[r.event_id]
        ok = r.status == "success"
        rows.append({"ts": str(r.timestamp), "node": "AUTH",
                     "msg": f"{'Successful' if ok else 'Failed'} login {r.user_id} from {r.ip_address} ({r.location})"
                            f" - {inc['vector']}, {inc['id']}",
                     "type": "alert" if inc["sev"] in ("critical", "high") else "warn", "incident": inc["id"],
                     "anomaly_score": round(float(r.anomaly_score), 1)})
    for r in t[t.transaction_id.isin(owner)].itertuples():
        inc = owner[r.transaction_id]
        rows.append({"ts": str(r.timestamp), "node": "PAYMENTS",
                     "msg": f"Transfer {r.transaction_id} ₹{r.amount:,.0f} by {r.user_id} to {r.merchant} ({r.status})"
                            f" - {inc['vector']}, {inc['id']}",
                     "type": "alert" if inc["sev"] in ("critical", "high") else "warn", "incident": inc["id"],
                     "anomaly_score": round(float(r.anomaly_score), 1)})
    return sorted(rows, key=lambda x: x["ts"], reverse=True)[:n]


def event_funnel(out, incidents):
    a = pd.read_csv(out / "scored_auth.csv", usecols=["event_id", "is_flagged"])
    t = pd.read_csv(out / "scored_txn.csv", usecols=["transaction_id", "is_flagged"])
    flagged = set(a.event_id[a.is_flagged == 1]) | set(t.transaction_id[t.is_flagged == 1])
    watch = json.loads((out / "watchlist.json").read_text()) if (out / "watchlist.json").exists() else []
    in_inc = {e for i in incidents for e in i["event_ids"]}
    in_watch = {e for w in watch for e in w["event_ids"]}
    pool = in_inc | in_watch
    return {"flagged_by_model": len(flagged), "flagged_by_rules_only": len(pool - flagged), "grouped": len(pool),
            "in_incidents": len(in_inc), "in_watchlist": len(in_watch)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=str(ML / "output"))
    p.add_argument("--data", default=str(ROOT / "data"))
    a = p.parse_args()
    out, data = Path(a.out), Path(a.data)

    incidents = json.loads((out / "incidents.json").read_text())
    api = pd.read_csv(data / "api_logs.csv")
    auth_n = len(pd.read_csv(out / "scored_auth.csv", usecols=["event_id"]))
    txn_n = len(pd.read_csv(out / "scored_txn.csv", usecols=["transaction_id"]))
    sev = Counter(i["sev"] for i in incidents)
    open_inc = [i for i in incidents if i["status"] != "RESOLVED"]
    w = {"critical": 4, "high": 3, "medium": 2, "low": 1}          # severity-weighted mean risk of open incidents
    platform = int(round(sum(i["risk_score"] * w[i["sev"]] for i in open_inc) /
                         max(sum(w[i["sev"]] for i in open_inc), 1)))

    dash = {
        "stats": {
            "active_incidents": len(open_inc),
            "critical": sev.get("critical", 0), "high": sev.get("high", 0),
            "active_incidents_sub": f"{sev.get('critical', 0)} critical need action",
            "platform_risk_score": platform,
            "platform_risk_sub": "severity-weighted mean risk of open incidents",
            "events_analysed": auth_n + txn_n,
            "events_analysed_sub": f"{auth_n:,} logins + {txn_n:,} transfers scored by the model",
            "anomalous_events": sum(i["event_count"] for i in incidents),     # events inside the incident list
            # the full funnel: model+guard flags + rule-only events -> grouped -> incidents or watch list
            "event_funnel": event_funnel(out, incidents),
            "amount_at_risk": round(sum(i["amount_total"] for i in incidents
                                        if i["vector"] == "Account Takeover"), 2),
            "detected_by": dict(Counter(i.get("detected_by", "ml") for i in incidents)),
        },
        "risk_map": risk_map(incidents, api),
        "live_events": live_events(incidents, out),
        "recent": [{"id": i["id"], "sev": i["sev"], "title": i["title"], "time": i["created"],
                    "date": i["start"][:10], "status": i["status"]}
                   for i in sorted(incidents, key=lambda x: x["start"], reverse=True)[:10]],
        "by_type": dict(Counter(i["vector"] for i in incidents).most_common()),
        "by_severity": {s: sev.get(s, 0) for s in ("critical", "high", "medium", "low")},
        "pipeline_run_id": incidents[0].get("pipeline_run_id") if incidents else None,
        "model": {"detector": "Isolation Forest + SHAP, hybrid with rule engine", "llm": "llama3.2:3b (Ollama)"},
    }
    (out / "dashboard.json").write_text(json.dumps(dash, indent=2, ensure_ascii=False))
    s = dash["stats"]
    print(f"dashboard.json: {s['active_incidents']} active incidents ({s['critical']} critical), platform risk "
          f"{s['platform_risk_score']}/100, {s['events_analysed']:,} events analysed")
    for nd in dash["risk_map"]:
        print(f"   {nd['tag']:9} {nd['id']:26} score {nd['score']:3}  {nd['alerts']:3} incidents  {nd['risk']}")
    print(f"   live_events: {len(dash['live_events'])} | recent: {len(dash['recent'])}")


if __name__ == "__main__":
    main()
