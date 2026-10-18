"""
Vantix - AI/ML module: analyst review sample (to estimate PRECISION without an answer key).

Draws a random, stratified sample of incidents (same number per attack type) and writes the evidence for each
into a CSV with an empty `label` column. A human analyst fills `label` with one of:
    real          - this is a genuine attack / fraud that deserves an alert
    false_alarm   - normal customer behaviour, should not have been an incident
    unsure        - not enough evidence either way
evaluate.py then reads the labels and reports precision per attack type (and weighted overall).

The sheet deliberately shows only evidence from the data - no model verdict text - so the label is the
analyst's own judgement. Re-running this script will NOT overwrite a sheet that already has labels.

Run (from repo root):  python backend/ml/review_sheet.py [--per 8] [--seed 11]
"""
import argparse
import json
from pathlib import Path

import pandas as pd

ML = Path(__file__).resolve().parent


def evidence(i):
    sq = i.get("sequence", {})
    parts = []
    if sq.get("failed_logins"):
        parts.append(f"{sq['failed_logins']} failed logins {sq['failed_window'][0]}-{sq['failed_window'][1]}")
    for o in sq.get("successful_logins", [])[:3]:
        parts.append(f"login OK {o['user']} {o['time']} from {o['ip']} ({o['location']})")
    for t in sq.get("transfers", [])[:4]:
        parts.append(f"{t['id']} Rs{t['amount']:,.0f} to {t['merchant']} at {t['time']} ({t['status']})")
    return " | ".join(parts)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=str(ML / "output"))
    p.add_argument("--per", type=int, default=8, help="incidents per attack type")
    p.add_argument("--seed", type=int, default=11)
    p.add_argument("--round", type=int, default=1,
                   help="2 = fresh sample AFTER the noise filters: only the noisy types, excluding round-1 incidents")
    a = p.parse_args()
    out = Path(a.out)
    sheet = out / ("review_sheet.csv" if a.round == 1 else f"review_sheet_{a.round}.csv")
    if sheet.exists() and pd.read_csv(sheet)["label"].notna().any():
        raise SystemExit(f"{sheet} already has labels - not overwriting. Delete it first to draw a new sample.")

    inc = json.loads((out / "incidents.json").read_text())
    rows = []
    for i in inc:
        ips = i.get("ip_details") or [{"ip": ip, "threat": i["ip_threat_level"], "usual_for_user": False} for ip in i["ips"]]
        rows.append({
            "incident_id": i["id"], "attack_type": i["vector"], "severity": i["sev"],
            "users": ", ".join(i["users"][:8]) + (" ..." if len(i["users"]) > 8 else ""),
            "n_users": len(i["users"]),
            "ips": "; ".join(f"{d['ip']} (feed: {d['threat']}, usual: {'yes' if d['usual_for_user'] else 'no'})"
                             for d in ips[:4]),
            "start": i["start"].replace("T", " "), "end": i["end"].replace("T", " "),
            "events": i["event_count"], "amount_total": i["amount_total"],
            "evidence": evidence(i),
            "model_reasons": "; ".join(r["text"] for r in i["reasons"]),
            "label": "", "notes": "",
        })
    df = pd.DataFrame(rows)
    if a.round > 1:
        seen = set(pd.read_csv(out / "review_sheet.csv").incident_id)
        df = df[~df.incident_id.isin(seen) & df.attack_type.isin(["Suspicious Login", "Transaction Anomaly"])]
        a.per = 10
    pieces = [g.sample(min(a.per, len(g)), random_state=a.seed) for _, g in df.groupby("attack_type")]
    sample = pd.concat(pieces).sample(frac=1, random_state=a.seed)   # shuffle so types are mixed while reviewing
    sample.to_csv(sheet, index=False)
    print(f"wrote {len(sample)} incidents -> {sheet}")
    print(sample.attack_type.value_counts().to_string())
    print("\nFill the `label` column with: real / false_alarm / unsure, then run evaluate.py")


if __name__ == "__main__":
    main()
