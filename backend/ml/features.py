"""
Sentra / FSIA - AI/ML module, step 1: feature engineering.

Turns raw logs into one numeric row per event so the anomaly model can score them.
  - auth_features.csv : one row per LOGIN attempt
  - txn_features.csv  : one row per TRANSACTION

Run (from repo root):  python backend/ml/features.py      # reads data/processed/*.csv (run preprocess.py first), writes backend/ml/output/
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

THREAT_SCORE = {"Low": 1, "Medium": 2, "High": 3}  # 0 = IP not on the threat list
# score cutoffs for "flagged": the ONE place they live (model.py writes is_flagged, incidents.py groups on it)
AUTH_THRESHOLD = 70   # login scores 60-70 are mostly single mistyped passwords (checked by score band)
TXN_THRESHOLD = 60


def load(data_dir: Path):
    rd = lambda n: pd.read_csv(data_dir / f"{n}.csv")
    auth, txn, users, threats, api = (rd(n) for n in
        ["authentication_logs", "transactions", "users_devices", "threat_indicators", "api_logs"])
    for df in (auth, txn, api):
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    return auth, txn, users, threats, api


def user_baselines(users: pd.DataFrame):
    """What 'normal' looks like for each user (a user can own several devices)."""
    known_devices = set(zip(users.user_id, users.device_id))
    known_ips = set(zip(users.user_id, users.usual_ip)) | set(zip(users.user_id, users.secondary_ip))
    usual_loc = set(zip(users.user_id, users.usual_location))
    avg_amt = users.groupby("user_id")["avg_txn_amount"].mean()
    return known_devices, known_ips, usual_loc, avg_amt


def rolling_count(df, key, flag_col, window="1h"):
    """For each row: how many rows with flag_col==1 for the same key in the previous `window` (incl. this one)."""
    out = pd.Series(0.0, index=df.index)
    for _, g in df.groupby(key):
        s = g.set_index("timestamp")[flag_col].rolling(window).sum()
        out.loc[g.index] = s.values
    return out


def add_common(df, known_devices, known_ips, usual_loc, threat_map):
    df["is_new_device"] = [int((u, d) not in known_devices) for u, d in zip(df.user_id, df.device_id)]
    df["ip_not_usual"] = [int((u, ip) not in known_ips) for u, ip in zip(df.user_id, df.ip_address)]
    df["location_mismatch"] = [int((u, l) not in usual_loc) for u, l in zip(df.user_id, df.location)]
    df["ip_threat_score"] = df.ip_address.map(threat_map).fillna(0).astype(int)
    df["hour"] = df.timestamp.dt.hour
    df["is_night"] = df.hour.between(0, 5).astype(int)
    return df


def build_auth_features(auth, known_devices, known_ips, usual_loc, threat_map):
    a = auth[auth.event_type == "login"].sort_values("timestamp").copy()
    a = add_common(a, known_devices, known_ips, usual_loc, threat_map)
    a["is_failed"] = (a.status == "failed").astype(int)
    a["mfa_not_prompted"] = (a.mfa_status == "not_prompted").astype(int)
    # brute force: many failures on one account; credential stuffing: many failures from one IP
    a["failed_logins_user_1h"] = rolling_count(a, "user_id", "is_failed")
    a["failed_logins_ip_1h"] = rolling_count(a, "ip_address", "is_failed")
    # one IP trying lots of different accounts
    a["one"] = 1
    a["distinct_users_ip_24h"] = 0
    for ip, g in a.groupby("ip_address"):
        g = g.set_index("timestamp")
        codes = g.user_id.astype("category").cat.codes.astype(float)
        a.loc[a.ip_address == ip, "distinct_users_ip_24h"] = (
            codes.rolling("24h").apply(lambda x: len(set(x)), raw=True).values)
    return a.drop(columns="one")


def build_txn_features(txn, auth, api, known_devices, known_ips, usual_loc, threat_map, avg_amt):
    t = txn.sort_values("timestamp").copy()
    t = add_common(t, known_devices, known_ips, usual_loc, threat_map)
    t["is_failed"] = (t.status == "failed").astype(int)
    t["amount_ratio"] = (t.amount / t.user_id.map(avg_amt)).round(2)
    t["log_amount"] = np.log1p(t.amount)
    t["one"] = 1
    t["txns_user_1h"] = rolling_count(t, "user_id", "one")

    # account-takeover pattern: beneficiary added, or new-device login, shortly before the transfer
    ben = api[api.endpoint == "/api/v1/beneficiaries"][["user_id", "timestamp"]]
    newdev_logins = auth[(auth.event_type == "login") & (auth.status == "success")].copy()
    newdev_logins = newdev_logins[[(u, d) not in known_devices
                                   for u, d in zip(newdev_logins.user_id, newdev_logins.device_id)]]

    def happened_before(events, hours):
        ev = events.groupby("user_id")["timestamp"].apply(list).to_dict()
        win = pd.Timedelta(hours=hours)
        return [int(any(ts - win <= e <= ts for e in ev.get(u, []))) for u, ts in zip(t.user_id, t.timestamp)]

    t["beneficiary_added_24h"] = happened_before(ben, 24)
    t["new_device_login_1h"] = happened_before(newdev_logins, 1)
    return t.drop(columns="one")


AUTH_FEATURES = ["is_failed", "is_new_device", "ip_not_usual", "location_mismatch", "ip_threat_score",
                 "is_night", "mfa_not_prompted", "failed_logins_user_1h", "failed_logins_ip_1h",
                 "distinct_users_ip_24h"]
TXN_FEATURES = ["is_failed", "is_new_device", "ip_not_usual", "location_mismatch", "ip_threat_score",
                "is_night", "amount_ratio", "log_amount", "txns_user_1h", "beneficiary_added_24h",
                "new_device_login_1h"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", default=str(Path(__file__).resolve().parents[2] / "data" / "processed"))
    p.add_argument("--out", default=str(Path(__file__).resolve().parent / "output"))
    args = p.parse_args()
    out = Path(args.out); out.mkdir(exist_ok=True)

    auth, txn, users, threats, api = load(Path(args.data))
    known_devices, known_ips, usual_loc, avg_amt = user_baselines(users)
    threat_map = threats.set_index("ip_address")["threat_level"].map(THREAT_SCORE)

    af = build_auth_features(auth, known_devices, known_ips, usual_loc, threat_map)
    tf = build_txn_features(txn, auth, api, known_devices, known_ips, usual_loc, threat_map, avg_amt)

    af.to_csv(out / "auth_features.csv", index=False)
    tf.to_csv(out / "txn_features.csv", index=False)
    print(f"auth_features.csv: {af.shape}   txn_features.csv: {tf.shape}")


if __name__ == "__main__":
    main()
