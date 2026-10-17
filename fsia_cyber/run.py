"""Pipeline: logs -> rules -> alerts -> correlation -> incidents (JSON for the AI module) -> evaluation.
Usage: python run.py <data_dir> [out_dir]
"""
import sys, os, json, pandas as pd
import rules, correlate, evaluate

D = sys.argv[1] if len(sys.argv) > 1 else "."
OUT = sys.argv[2] if len(sys.argv) > 2 else "output"
os.makedirs(OUT, exist_ok=True)

# 1-3. detection + correlation + MITRE mapping (no ground truth used)
a, t, u, ti = rules.load(D)
alerts = rules.run_all(a, t, u, ti)
incidents = correlate.correlate(alerts)


def evidence(inc):
    """Structured evidence handed to the AI investigation module."""
    ev = {"incident_id": inc["incident_id"], "users": inc["user_ids"], "ip_addresses": inc["ip_addresses"],
          "start": str(inc["start"]), "end": str(inc["end"]), "possible_attack": inc["attack_type"],
          "severity": inc["severity"], "mitre": inc["mitre"], "rules_triggered": inc["rules_triggered"],
          "alerts": []}
    for al in sorted(inc["alerts"], key=lambda x: x["start"]):
        ev["alerts"].append({"rule": al["rule"], "user_id": al["user_id"], "ip_address": al["ip_address"],
                             "time": str(al["start"]), "details": {k: (v.item() if hasattr(v, "item") else v)
                                                                   for k, v in al["details"].items()}})
    return ev


with open(f"{OUT}/incidents.json", "w") as f:
    json.dump([evidence(i) for i in incidents], f, indent=2, default=str)
pd.DataFrame([{k: (str(v) if k in ("start", "end") else v) for k, v in al.items() if k != "event_ids"}
              | {"details": json.dumps(al["details"], default=str)} for al in alerts]).to_csv(f"{OUT}/alerts.csv", index=False)

# 4. evaluation against the answer key (ground truth is loaded ONLY here)
gt_s = pd.read_csv(f"{D}/ground_truth_scenarios.csv"); gt_e = pd.read_csv(f"{D}/ground_truth_events.csv")
res = evaluate.evaluate(incidents, alerts, gt_s, gt_e)
res["summary"].to_csv(f"{OUT}/evaluation_summary.csv")
res["per_scenario"].to_csv(f"{OUT}/evaluation_per_scenario.csv", index=False)
print(f"\nAlerts: {len(alerts)}  ->  Incidents: {len(incidents)}   (files written to {OUT}/)")
