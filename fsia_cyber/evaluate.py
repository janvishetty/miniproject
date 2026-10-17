"""Score the detector against the ground-truth answer key (run AFTER detection)."""
import pandas as pd

def evaluate(incidents, alerts, gt_scen, gt_events, verbose=True):
    gt_events = gt_events[gt_events.table != "api"]
    key = {r.event_id: (r.scenario_id, r.scenario_type) for r in gt_events.itertuples()}
    scen_keys = list(zip(gt_scen.scenario_id, gt_scen.scenario_type))

    # which incidents touch which scenarios
    inc_scen = {}
    for inc in incidents:
        s = {key[e] for e in inc["event_ids"] if e in key}
        inc_scen[inc["incident_id"]] = s
    detected = {sk: [] for sk in scen_keys}
    for iid, s in inc_scen.items():
        for sk in s: detected[sk].append(iid)

    rows = []
    for r in gt_scen.itertuples():
        sk = (r.scenario_id, r.scenario_type)
        incs = [i for i in incidents if i["incident_id"] in detected[sk]]
        exp_rules = set(r.expected_rules.split(";"))
        fired = {x for i in incs for x in i["rules_triggered"]}
        exp_mitre = set(r.mitre_technique.split(";"))
        got_mitre = {m["id"] for i in incs for m in i["mitre"]}
        rows.append(dict(scenario_id=r.scenario_id, scenario_type=r.scenario_type, detected=bool(incs),
                         rules_recall=len(exp_rules & fired) / len(exp_rules), missing_rules=sorted(exp_rules - fired),
                         mitre_ok=exp_mitre <= got_mitre, severity_ok=any(i["severity"] == r.expected_severity for i in incs),
                         merged_with_others=any(len(inc_scen[i["incident_id"]]) > 1 for i in incs)))
    res = pd.DataFrame(rows)
    summary = res.groupby("scenario_type").agg(
        scenarios=("detected", "size"), detected=("detected", "sum"), rule_recall=("rules_recall", "mean"),
        mitre_ok=("mitre_ok", "sum"), severity_ok=("severity_ok", "sum"))
    summary["detection_rate"] = (summary.detected / summary.scenarios).round(3)
    summary["rule_recall"] = summary.rule_recall.round(3)

    false_pos = [i for i in incidents if not inc_scen[i["incident_id"]]]
    out = dict(summary=summary, per_scenario=res, false_positive_incidents=false_pos,
               total_incidents=len(incidents), true_incidents=len(incidents) - len(false_pos),
               incident_precision=round(1 - len(false_pos) / max(len(incidents), 1), 3),
               overall_recall=round(res.detected.mean(), 3))
    if verbose:
        print(summary.to_string()); print()
        print(f"Incidents: {out['total_incidents']}  | false positives: {len(false_pos)}  "
              f"| precision: {out['incident_precision']}  | scenario recall: {out['overall_recall']}")
    return out
