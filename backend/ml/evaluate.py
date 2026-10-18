"""
Vantix - AI/ML module: evaluation WITHOUT ground-truth labels.

No answer key exists for this dataset, so we use honest, non-circular checks:

  A. Proxy-label test (transactions): the `merchant` column is NOT a model input. Only a handful of transfers
     go to cash-out channels (crypto, overseas remittance, gift cards, new-beneficiary wires) - the pattern
     of the planted fraud. Question: did the model rank those as anomalous WITHOUT seeing the merchant?
     -> recall on cash-out transfers, and how many of the top-K flagged transfers are cash-out.

  B. Attack-injection test (inject_test.py): attacks with KNOWN labels planted into a copy of the data
     -> recall per attack type, easy vs stealthy. This script just reports the saved results.

  C. Analyst review (review_sheet.py): a human labels a random stratified sample of incidents
     real / false_alarm / unsure -> precision per attack type, weighted by how common each type is.

  D. Ground truth (added later): the dataset's answer key data/ground_truth_*.csv (195 planted attack scenarios)
     arrived with the rule engine. It is read ONLY here, never by the model or the rules. Scores ML-only,
     rules-only and the hybrid incident list: scenarios caught, false-positive incidents, right attack type.

Run (from repo root):  python backend/ml/evaluate.py      -> prints tables, writes output/evaluation.json
"""
import argparse
import json
from collections import Counter
from pathlib import Path

import pandas as pd

from features import TXN_FEATURES, TXN_THRESHOLD   # TXN_THRESHOLD = the cutoff incidents.py uses

from features import CASHOUT_CHANNELS as CASHOUT   # section A scores anomaly_score only, so the guards don't touch it
THRESHOLDS = [50, 60, 70, 80, 90]


def proxy_cashout(out: Path):
    assert not any("merchant" in f for f in TXN_FEATURES), "merchant must not be a model feature (would be circular)"
    t = pd.read_csv(out / "scored_txn.csv")
    t["cashout"] = t.merchant.isin(CASHOUT)
    n_pos = int(t.cashout.sum())
    rank = t.anomaly_score.rank(ascending=False, method="min")

    by_threshold = []
    for th in THRESHOLDS:
        f = t.anomaly_score >= th
        by_threshold.append({"threshold": th, "flagged": int(f.sum()),
                             "cashout_caught": int((f & t.cashout).sum()),
                             "recall": round((f & t.cashout).sum() / n_pos, 3),
                             "cashout_share_of_flagged": round((f & t.cashout).sum() / max(f.sum(), 1), 3)})

    # precision@K: of the K most anomalous transfers, how many are cash-out
    top = t.sort_values("anomaly_score", ascending=False)
    at_k = [{"k": k, "cashout": int(top.head(k).cashout.sum()), "precision": round(top.head(k).cashout.mean(), 3)}
            for k in (10, 25, 41, 53, 100)]

    incidents = json.loads((out / "incidents.json").read_text())
    vec = {e: i["vector"] for i in incidents for e in i["event_ids"]}
    c = t[t.cashout].assign(vector=lambda d: d.transaction_id.map(vec).fillna("not in any incident"))

    # sub-pattern: cash-out from the customer's OWN device/IP in daytime = authorised push-payment (APP) scam
    app = c[(c.is_new_device == 0) & (c.ip_not_usual == 0) & (c.ip_threat_score == 0)]
    return {
        "cashout_transfers": n_pos, "total_transfers": len(t),
        "score_of_cashout": c.anomaly_score.describe().round(1).to_dict(),
        "worst_rank_of_any_cashout": int(rank[t.cashout].max()),
        "by_threshold": by_threshold, "precision_at_k": at_k,
        "cashout_by_incident_type": c.vector.value_counts().to_dict(),
        "app_scam_pattern": {"count": len(app), "caught_at_threshold": int((app.anomaly_score >= TXN_THRESHOLD).sum()),
                             "score_range": [float(app.anomaly_score.min()), float(app.anomaly_score.max())]
                             if len(app) else None},
    }


# which of our attack types counts as the right label for each ground-truth scenario type
GT_VECTOR = {"brute_force": {"Brute Force"}, "account_takeover": {"Account Takeover"},
             "multi_account_ip": {"Credential Stuffing"}, "large_transaction": {"Transaction Anomaly"},
             "suspicious_login": {"Suspicious Login"}, "suspicious_ip": {"Suspicious Login"}}


def ground_truth(incidents, data: Path, watch=()):
    """Score incident lists against the answer key. Scenario IDs repeat across types, so the key is (id, type)."""
    ge = pd.read_csv(data / "ground_truth_events.csv")
    ge = ge[ge.table != "api"]                     # api_logs are not a detection input
    gs = pd.read_csv(data / "ground_truth_scenarios.csv")
    key = dict(zip(ge.event_id, zip(ge.scenario_id, ge.scenario_type)))
    scen = list(zip(gs.scenario_id, gs.scenario_type))

    def score(name, incs, ev_field):
        hit, fp, typed = {}, [], set()
        for i in incs:
            s = {key[e] for e in i[ev_field] if e in key}
            if not s:
                fp.append(i)
            for sk in s:
                hit.setdefault(sk, []).append(i)
                if i["vector"] in GT_VECTOR[sk[1]]:
                    typed.add(sk)
        per_type = []
        for t, n in Counter(t for _, t in scen).items():
            sks = [sk for sk in scen if sk[1] == t]
            per_type.append({"type": t, "scenarios": n, "caught": sum(sk in hit for sk in sks),
                             "right_type": sum(sk in typed for sk in sks)})
        caught = sum(sk in hit for sk in scen)
        return {"name": name, "incidents": len(incs), "scenarios": len(scen), "caught": caught,
                "recall": round(caught / len(scen), 3), "false_positive_incidents": len(fp),
                "precision": round(1 - len(fp) / max(len(incs), 1), 3),
                "false_positives_by_severity": dict(Counter(i["sev"] for i in fp)),
                "missed": [f"{a} ({b})" for a, b in scen if (a, b) not in hit], "per_type": per_type}

    exp_sev = dict(zip(scen, gs.expected_severity.str.lower()))
    rank = {"low": 0, "medium": 1, "high": 2, "critical": 3}

    def severity(incs, field):
        """Severity of the incident(s) holding each scenario vs the answer key's expected severity."""
        c = Counter()
        for i in incs:
            for sk in {key[e] for e in i["event_ids"] if e in key}:
                d = rank[i.get(field, i["sev"])] - rank[exp_sev[sk]]
                c["match" if d == 0 else "higher" if d > 0 else "lower"] += 1
        return dict(c)

    has_rules = any("detected_by" in i for i in incidents)
    # ML only = what the model reported BEFORE the hybrid triage (unconfirmed low incidents went to the watch list)
    ml = [i for i in incidents if i.get("ml_event_ids", i["event_ids"])] + [w for w in watch if w.get("unconfirmed")]
    res = [score("ML only", ml, "ml_event_ids" if has_rules else "event_ids")]
    res[0]["severity_vs_key"] = severity(ml, "ml_severity" if has_rules else "sev")
    if has_rules:
        res.append(score("Hybrid (ML + rules)", incidents, "event_ids"))
        res[1]["severity_vs_key"] = severity(incidents, "sev")
        # how the two detectors relate: false positives by who detected the incident
        fp = {i["id"] for i in incidents if not {key[e] for e in i["event_ids"] if e in key}}
        res[1]["false_positives_by_detector"] = {d: f"{sum(i['id'] in fp for i in incidents if i['detected_by'] == d)}"
                                                    f" of {sum(i['detected_by'] == d for i in incidents)}"
                                                 for d in ("ml+rules", "ml", "rules")}
    return res


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=str(Path(__file__).resolve().parent / "output"))
    out = Path(p.parse_args().out)

    A = proxy_cashout(out)
    incidents = json.loads((out / "incidents.json").read_text())
    print("A. PROXY-LABEL TEST - cash-out transfers (merchant column is NOT a model input)")
    print(f"   {A['cashout_transfers']} cash-out transfers out of {A['total_transfers']}; "
          f"every one ranks in the top {A['worst_rank_of_any_cashout']} most anomalous")
    print(f"   {'threshold':>9} {'flagged':>8} {'caught':>7} {'recall':>7} {'cash-out share':>15}")
    for r in A["by_threshold"]:
        mark = "  <- used" if r["threshold"] == TXN_THRESHOLD else ""
        print(f"   {r['threshold']:>9} {r['flagged']:>8} {r['cashout_caught']:>4}/{A['cashout_transfers']}"
              f" {r['recall']:>7.0%} {r['cashout_share_of_flagged']:>15.0%}{mark}")
    print("   precision@K: " + " | ".join(f"top {r['k']}: {r['cashout']}/{r['k']} ({r['precision']:.0%})"
                                         for r in A["precision_at_k"]))
    print(f"   cash-out transfers by incident type: {A['cashout_by_incident_type']}")
    s = A["app_scam_pattern"]
    print(f"   APP-scam pattern (customer's own device + IP, no threat intel): {s['count']} transfers, "
          f"{s['caught_at_threshold']}/{s['count']} caught at threshold {TXN_THRESHOLD}, scores {s['score_range']}")

    result = {"proxy_cashout": A}

    # B. injection test (run inject_test.py first)
    inj = out / "inject_test" / "injection_summary.json"
    print("\nB. ATTACK-INJECTION TEST (planted attacks with known labels)")
    if inj.exists():
        B = json.loads(inj.read_text())
        print(f"   {'attack':22}{'difficulty':11}{'recall (mean)':>14}{'range over seeds':>18}{'right type':>12}")
        for r in B:
            rng = f"{r['recall_min']:.0%}-{r['recall_max']:.0%}"
            print(f"   {r['type']:22}{r['difficulty']:11}{r['recall']:>14.0%}{rng:>18}{r['type_accuracy']:>12.0%}")
        n = sum(r["attacks"] for r in B)
        print(f"   overall recall: {sum(r['recall'] * r['attacks'] for r in B) / n:.0%}  ({n} planted attacks)")
        result["injection"] = B
    else:
        print("   not run yet -> python backend/ml/inject_test.py")

    # C. analyst review: round 1 = before noise filters, round 2 = fresh sample after filters
    watch = json.loads((out / "watchlist.json").read_text()) if (out / "watchlist.json").exists() else []
    pop_after = pd.Series([i["vector"] for i in incidents]).value_counts()
    pop_before = pop_after.add(pd.Series([w["vector"] for w in watch]).value_counts(), fill_value=0)

    def review(path, pop, title):
        if not (path.exists() and pd.read_csv(path)["label"].notna().any()):
            return None
        rv = pd.read_csv(path)
        rv["label"] = rv.label.astype(str).str.strip().str.lower()
        done = rv[rv.label.isin(["real", "false_alarm"])]
        print(f"   {title}")
        rows = []
        for v, g in done.groupby("attack_type"):
            prec = (g.label == "real").mean()
            rows.append({"attack_type": v, "reviewed": len(g), "real": int((g.label == "real").sum()),
                         "precision": round(prec, 3), "incidents_of_type": int(pop.get(v, 0))})
            print(f"     {v:22} {rows[-1]['real']}/{len(g)} real  precision {prec:.0%}  ({int(pop.get(v, 0))} incidents)")
        return {"by_type": rows, "unsure": int((rv.label == "unsure").sum())}

    print("\nC. ANALYST REVIEW (precision on random stratified samples)")
    docs = Path(__file__).resolve().parents[2] / "docs"     # labelled copies are committed here
    pick = lambda name, saved: out / name if (out / name).exists() else docs / saved
    r1 = review(pick("review_sheet.csv", "review_sheet_labelled.csv"), pop_before, "round 1 - BEFORE noise filters:")
    if r1 is None:
        print("   no labels yet -> python backend/ml/review_sheet.py, fill the `label` column, rerun evaluate.py")
    else:
        w1 = sum(r["precision"] * r["incidents_of_type"] for r in r1["by_type"]) / sum(r["incidents_of_type"] for r in r1["by_type"])
        print(f"     weighted precision: {w1:.0%}  over {int(pop_before.sum())} incidents (unsure: {r1['unsure']})")
        r1["weighted_precision"] = round(w1, 3)
        result["review_round1_before_filters"] = r1
        r2 = review(pick("review_sheet_2.csv", "review_sheet_2_labelled.csv"), pop_after,
                    "round 2 - fresh sample AFTER noise filters (noisy types only):")
        if r2 is None:
            print("   round 2 not labelled yet -> python backend/ml/review_sheet.py --round 2")
        else:
            # types not re-sampled in round 2 keep their round-1 precision (filters don't touch them)
            p2 = {r["attack_type"]: r["precision"] for r in r2["by_type"]}
            p1 = {r["attack_type"]: r["precision"] for r in r1["by_type"]}
            w2 = sum(p2.get(v, p1.get(v, 0)) * n for v, n in pop_after.items()) / pop_after.sum()
            print(f"     weighted precision: {w2:.0%}  over {int(pop_after.sum())} incidents "
                  f"(+{len(watch)} moved to watch-list) (unsure: {r2['unsure']})")
            r2["weighted_precision"] = round(w2, 3)
            result["review_round2_after_filters"] = r2

    # D. ground truth
    data = Path(__file__).resolve().parents[2] / "data"
    print("\nD. GROUND TRUTH (answer key data/ground_truth_*.csv - used only here)")
    if (data / "ground_truth_scenarios.csv").exists():
        D = ground_truth(incidents, data, json.loads((out / "watchlist.json").read_text())
                         if (out / "watchlist.json").exists() else [])
        for r in D:
            print(f"   {r['name']:20} caught {r['caught']}/{r['scenarios']} scenarios ({r['recall']:.1%})  | "
                  f"{r['false_positive_incidents']} false-positive incidents of {r['incidents']} "
                  f"(precision {r['precision']:.1%}, severity {r['false_positives_by_severity']})  | missed: {r['missed'] or 'none'}")
        print(f"   {'':20}" + "".join(f"{r['name']:>26}" for r in D))
        print(f"   {'scenario type':20}" + "".join(f"{'caught  right type':>26}" for r in D))
        for k in range(len(D[0]["per_type"])):
            t = D[0]["per_type"][k]["type"]
            print(f"   {t:20}" + "".join(f"{str(x['caught']) + '/' + str(x['scenarios']):>14}{str(x['right_type']) + '/' + str(x['scenarios']):>12}"
                                         for x in (next(p for p in r['per_type'] if p['type'] == t) for r in D)))
        for r in D:
            sv = r["severity_vs_key"]
            print(f"   severity vs answer key, {r['name']:20}: {sv.get('match', 0)} match, {sv.get('higher', 0)} higher, "
                  f"{sv.get('lower', 0)} lower")
        if len(D) > 1:
            print(f"   false positives by detector: {D[1]['false_positives_by_detector']}")
        print("   rules only (fsia_cyber/run.py): see fsia_cyber/output/evaluation_summary.csv")
        result["ground_truth"] = D
    else:
        print("   no answer key in data/")

    (out / "evaluation.json").write_text(json.dumps(result, indent=2))
    print(f"\nsaved -> {out / 'evaluation.json'}")


if __name__ == "__main__":
    main()
