"""
Vantix - AI/ML module, step 2: anomaly detection + SHAP explanations.

Isolation Forest isolates points with random splits; anomalies get isolated in
fewer splits (shorter path). SHAP's TreeExplainer tells us which features made
that path short for a given event = WHY it was flagged.

Run (from repo root):  python backend/ml/model.py         # reads + writes backend/ml/output/
"""
import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import shap
from sklearn.ensemble import IsolationForest

from features import (AUTH_FEATURES, TXN_FEATURES, AUTH_THRESHOLD, TXN_THRESHOLD, EXTREME_RATIO, PAYEE_RATIO,
                      NEWDEV_RATIO, CASHOUT_CHANNELS)

# Human-readable reason for each feature (used in the frontend + LLM prompt)
REASON_TEXT = {
    "is_failed": lambda r: "Attempt failed",
    "is_new_device": lambda r: f"Unregistered device {r.device_id}",
    "ip_not_usual": lambda r: f"IP {r.ip_address} not in user's usual IPs",
    "location_mismatch": lambda r: f"Unusual location: {r.location}",
    "ip_threat_score": lambda r: f"IP on threat list ({ {1:'Low',2:'Medium',3:'High'}.get(int(r.ip_threat_score),'none') })",
    "is_night": lambda r: f"Activity at {int(r.hour):02d}:00 (night)",
    "mfa_not_prompted": lambda r: "MFA not prompted",
    "failed_logins_user_1h": lambda r: f"{int(r.failed_logins_user_1h)} failed logins on account in 1h",
    "failed_logins_ip_1h": lambda r: f"{int(r.failed_logins_ip_1h)} failed logins from this IP in 1h",
    "distinct_users_ip_24h": lambda r: f"IP touched {int(r.distinct_users_ip_24h)} different accounts in 24h",
    "amount_ratio": lambda r: f"Amount ₹{r.amount:,.0f} is {r.amount_ratio:.1f}x user's average",
    "log_amount": lambda r: f"Unusual amount ₹{r.amount:,.0f} for this user",
    "txns_user_1h": lambda r: f"{int(r.txns_user_1h)} transactions in 1h",
    "beneficiary_added_24h": lambda r: "New beneficiary added in previous 24h",
    "new_device_login_1h": lambda r: "Login from new device in previous 1h",
}


def train_and_explain(df: pd.DataFrame, feats: list, name: str, out: Path, top_n=10):
    X = df[feats].astype(float)

    model = IsolationForest(n_estimators=300, contamination="auto", random_state=42)
    model.fit(X)
    joblib.dump(model, out / f"iforest_{name}.joblib")

    # score_samples: higher = more normal. Flip and rescale to 0-100 (100 = most anomalous)
    raw = -model.score_samples(X)
    df["anomaly_score"] = np.round(100 * (raw - raw.min()) / (raw.max() - raw.min()), 1)
    df["is_anomaly"] = (model.predict(X) == -1).astype(int)   # raw Isolation Forest label (loose; NOT what incidents use)
    # is_flagged = what the incidents are built from (score >= threshold). Use THIS for "anomalous" counts.
    df["is_flagged"] = (df.anomaly_score >= {"auth": AUTH_THRESHOLD, "txn": TXN_THRESHOLD}[name]).astype(int)

    # SHAP: for IsolationForest, NEGATIVE values shorten the path = push towards anomaly
    explainer = shap.TreeExplainer(model)
    sv = explainer.shap_values(X)
    contrib = pd.DataFrame(-sv, columns=feats, index=df.index)  # flip so positive = more suspicious

    def reasons(i):
        c = contrib.loc[i]
        c = c[c > 0].sort_values(ascending=False).head(3)
        r = df.loc[i]
        return [{"feature": f, "impact": round(float(v), 3), "text": REASON_TEXT[f](r)} for f, v in c.items()]

    df["top_reasons"] = [json.dumps(reasons(i)) for i in df.index]

    df["flag_reason"] = np.where(df.is_flagged == 1, "model", "")
    if name == "txn":
        extreme = df.amount_ratio >= EXTREME_RATIO
        payee = df.merchant.isin(CASHOUT_CHANNELS) & (df.amount_ratio >= PAYEE_RATIO)
        newdev = (df.new_device_login_1h == 1) & (df.amount_ratio >= NEWDEV_RATIO)
        for mask, tag, text in [
                (extreme, "guard: amount", lambda r: f"Amount ₹{r.amount:,.0f} is {r.amount_ratio:.1f}x user's average"
                                                     f" (above the {EXTREME_RATIO}x limit)"),
                (payee, "guard: payee", lambda r: f"Transfer to {r.merchant} (cash-out channel) at "
                                                  f"{r.amount_ratio:.1f}x user's average"),
                (newdev, "guard: device", lambda r: f"Amount ₹{r.amount:,.0f} ({r.amount_ratio:.1f}x user's average) "
                                                    f"soon after a login from an unregistered device")]:
            new = mask & (df.is_flagged == 0)
            for i in df.index[new]:
                rs = json.loads(df.at[i, "top_reasons"])
                df.at[i, "top_reasons"] = json.dumps([{"feature": tag.split(": ")[1] + "_guard", "impact": 1.0,
                                                       "text": text(df.loc[i])}] + rs[:2])
            df.loc[new, "flag_reason"] = tag
            df.loc[new, "is_flagged"] = 1
    df.to_csv(out / f"scored_{name}.csv", index=False)

    top = df.sort_values("anomaly_score", ascending=False).head(top_n)
    return df, top


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--features", default=str(Path(__file__).resolve().parent / "output"))
    p.add_argument("--out", default=str(Path(__file__).resolve().parent / "output"))
    args = p.parse_args()
    fdir, out = Path(args.features), Path(args.out)
    out.mkdir(exist_ok=True)

    auth = pd.read_csv(fdir / "auth_features.csv")
    txn = pd.read_csv(fdir / "txn_features.csv")

    auth, top_auth = train_and_explain(auth, AUTH_FEATURES, "auth", out)
    txn, top_txn = train_and_explain(txn, TXN_FEATURES, "txn", out)

    for name, df, top, idcol in [("LOGINS", auth, top_auth, "event_id"), ("TRANSACTIONS", txn, top_txn, "transaction_id")]:
        guards = df.flag_reason.str.startswith("guard").sum()
        print(f"\n=== {name}: {df.is_flagged.sum()} flagged of {len(df)} (score cutoff"
              f"{f' + {guards} by guards' if guards else ''}; raw IF label: {df.is_anomaly.sum()}) ===")
        for _, r in top.iterrows():
            rs = "; ".join(x["text"] for x in json.loads(r.top_reasons))
            print(f"{r[idcol]}  {r.user_id}  score={r.anomaly_score:5.1f}  | {rs}")


if __name__ == "__main__":
    main()
