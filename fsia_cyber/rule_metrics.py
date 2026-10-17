"""Per-rule accuracy table. Run AFTER detection: python rule_metrics.py <data_dir> [out_dir]"""
import sys, pandas as pd
import rules, correlate

D = sys.argv[1] if len(sys.argv) > 1 else "."
OUT = sys.argv[2] if len(sys.argv) > 2 else "output"

a, t, u, ti = rules.load(D)
alerts = rules.run_all(a, t, u, ti)
incidents = correlate.correlate(alerts)
gs = pd.read_csv(f"{D}/ground_truth_scenarios.csv")
ge = pd.read_csv(f"{D}/ground_truth_events.csv"); ge = ge[ge.table != "api"]
key = {r.event_id: (r.scenario_id, r.scenario_type) for r in ge.itertuples()}

# scenario -> rules that fired on its events (alert level)
fired = {}
noise = {}                                   # alerts that touch no injected attack = false-positive alerts
total = {}
for al in alerts:
    total[al["rule"]] = total.get(al["rule"], 0) + 1
    scen = {key[e] for e in al["event_ids"] if e in key}
    if not scen:
        noise[al["rule"]] = noise.get(al["rule"], 0) + 1
    for s in scen:
        fired.setdefault(s, set()).add(al["rule"])

rows = {}
for r in gs.itertuples():
    sk = (r.scenario_id, r.scenario_type)
    exp = set(r.expected_rules.split(";"))
    f = fired.get(sk, set())
    for rule in exp:
        d = rows.setdefault(rule, dict(expected=0, caught=0))
        d["expected"] += 1; d["caught"] += rule in f
table = pd.DataFrame(rows).T.fillna(0)
for rule in total:
    table.loc[rule, "total_alerts"] = total[rule]
    table.loc[rule, "false_alerts"] = noise.get(rule, 0)
table = table.fillna(0).astype(int)
table["recall_%"] = (100 * table.caught / table.expected.where(table.expected > 0)).round(1)
table["precision_%"] = (100 * (table.total_alerts - table.false_alerts) / table.total_alerts).round(1)
table.index.name = "rule"
print(table.to_string()); table.to_csv(f"{OUT}/rule_metrics.csv")
