"""
Sentra / FSIA - AI/ML module: evaluation WITHOUT ground-truth labels.

No answer key exists for this dataset, so we use honest, non-circular checks:

  A. Proxy-label test (transactions): the `merchant` column is NOT a model input. Only a handful of transfers
     go to cash-out channels (crypto, overseas remittance, gift cards, new-beneficiary wires) - the pattern
     of the planted fraud. Question: did the model rank those as anomalous WITHOUT seeing the merchant?
     -> recall on cash-out transfers, and how many of the top-K flagged transfers are cash-out.

  B. Attack-injection test (inject_test.py): attacks with KNOWN labels planted into a copy of the data
     -> recall per attack type, easy vs stealthy. This script just reports the saved results.

  C. Analyst review (review_sheet.py): a human labels a random stratified sample of incidents
     real / false_alarm / unsure -> precision per attack type, weighted by how common each type is.

Run (from repo root):  python backend/ml/evaluate.py      -> prints tables, writes output/evaluation.json
"""
import argparse
import json
from pathlib import Path

import pandas as pd

from features import TXN_FEATURES

CASHOUT = {"Crypto Exchange", "Overseas Remittance", "Gift Card Marketplace", "Wire Transfer - New Beneficiary"}
THRESHOLDS = [50, 60, 70, 80, 90]
TXN_THRESHOLD = 60   # the cutoff incidents.py uses


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
    r1 = review(out / "review_sheet.csv", pop_before, "round 1 - BEFORE noise filters:")
    if r1 is None:
        print("   no labels yet -> python backend/ml/review_sheet.py, fill the `label` column, rerun evaluate.py")
    else:
        w1 = sum(r["precision"] * r["incidents_of_type"] for r in r1["by_type"]) / sum(r["incidents_of_type"] for r in r1["by_type"])
        print(f"     weighted precision: {w1:.0%}  over {int(pop_before.sum())} incidents (unsure: {r1['unsure']})")
        r1["weighted_precision"] = round(w1, 3)
        result["review_round1_before_filters"] = r1
        r2 = review(out / "review_sheet_2.csv", pop_after, "round 2 - fresh sample AFTER noise filters (noisy types only):")
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

    (out / "evaluation.json").write_text(json.dumps(result, indent=2))
    print(f"\nsaved -> {out / 'evaluation.json'}")


if __name__ == "__main__":
    main()
