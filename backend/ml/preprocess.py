"""
Vantix - AI/ML module, step 0: data validation + cleaning.

Reads raw CSVs from data/, checks quality, cleans, and writes:
  data/processed/*.csv                      cleaned files (used by features.py)
  backend/ml/output/preprocessing_report.json   what was checked / removed per file

Checks: duplicates, duplicate IDs, unparseable timestamps, out-of-range timestamps, non-positive amounts,
invalid IPs, unknown users (not in users_devices), unexpected category values, missing values,
conflicting threat levels for one IP, text whitespace/case.

Run (from repo root):  python backend/ml/preprocess.py
"""
import argparse
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
IP_RE = r"^(25[0-5]|2[0-4]\d|1?\d?\d)(\.(25[0-5]|2[0-4]\d|1?\d?\d)){3}$"

ID_COL = {"authentication_logs": "event_id", "transactions": "transaction_id", "api_logs": "event_id"}
ALLOWED = {
    "authentication_logs": {"event_type": {"login", "logout"}, "status": {"success", "failed"},
                            "mfa_status": {"passed", "not_required", "not_prompted", "n/a"}},
    "transactions": {"status": {"success", "failed"}},
    "users_devices": {"registered_device": {"Y", "N"}, "device_type": {"web", "ios", "android"}},
    "threat_indicators": {"threat_level": {"Low", "Medium", "High"}},
    "api_logs": {"method": {"GET", "POST", "PUT", "PATCH", "DELETE"}},
}
LOWER = {"event_type", "status", "mfa_status", "device_type"}   # normalise case of these columns


def drop(df, mask, reason, log):
    n = int(mask.sum())
    log[reason] = n
    idcol = next((c for c in ("event_id", "transaction_id") if c in df), None)
    if n and idcol:   # which events were removed, so the backend can tell a dropped ID from a missing one
        log.setdefault("dropped_ids", {})[reason] = df.loc[mask, idcol].astype(str).tolist()
    return df[~mask]


def clean_text(df, log):
    """Strip whitespace everywhere; fix case of categorical columns."""
    changed = 0
    for c in [c for c in df.columns if pd.api.types.is_string_dtype(df[c])]:
        new = df[c].str.strip()
        if c in LOWER:
            new = new.str.lower()
        changed += int((new != df[c]).sum())
        df[c] = new
    log["text_values_normalised"] = changed
    return df


def clean_events(name, df, log, valid_users=None, start=None, end=None):
    log["rows_in"] = len(df)
    df = clean_text(df, log)
    df = drop(df, df.duplicated(), "exact_duplicates", log)
    if name in ID_COL:
        df = drop(df, df[ID_COL[name]].duplicated(), "duplicate_ids", log)
    if "timestamp" in df:
        df["timestamp"] = pd.to_datetime(df.timestamp, errors="coerce")
        df = drop(df, df.timestamp.isna(), "bad_timestamps", log)
        if start is not None:
            df = drop(df, (df.timestamp < start) | (df.timestamp > end), "timestamps_out_of_range", log)
    if "ip_address" in df:
        df = drop(df, ~df.ip_address.astype(str).str.match(IP_RE), "invalid_ips", log)
    if "amount" in df:
        df = drop(df, ~(pd.to_numeric(df.amount, errors="coerce") > 0), "non_positive_amounts", log)
    if valid_users is not None and "user_id" in df:
        df = drop(df, ~df.user_id.isin(valid_users), "unknown_users", log)
    for col, allowed in ALLOWED.get(name, {}).items():
        if col in df:
            df = drop(df, df[col].notna() & ~df[col].isin(allowed), f"unexpected_{col}", log)
    if "timestamp" in df:
        df = df.sort_values("timestamp", kind="mergesort")   # stable: equal timestamps keep file order
    return df


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--raw", default=str(ROOT / "data"))
    p.add_argument("--processed", default=str(ROOT / "data" / "processed"))
    p.add_argument("--report", default=str(Path(__file__).resolve().parent / "output" / "preprocessing_report.json"))
    a = p.parse_args()
    raw, proc = Path(a.raw), Path(a.processed)
    proc.mkdir(parents=True, exist_ok=True)
    Path(a.report).parent.mkdir(parents=True, exist_ok=True)

    rd = lambda n: pd.read_csv(raw / f"{n}.csv")
    report, out = {}, {}

    # users_devices first: it defines the valid users
    log = report.setdefault("users_devices", {})
    u = clean_events("users_devices", rd("users_devices"), log)
    u = drop(u, u.duplicated(["user_id", "device_id"]), "duplicate_user_device_pairs", log)
    u = drop(u, ~(u.avg_txn_amount > 0), "non_positive_avg_txn", log)
    out["users_devices"] = u
    users = set(u.user_id)

    # threat indicators: one level per IP (keep the highest if a feed lists it twice)
    log = report.setdefault("threat_indicators", {})
    ti = clean_events("threat_indicators", rd("threat_indicators"), log)
    log["conflicting_levels"] = int(ti.groupby("ip_address").threat_level.nunique().gt(1).sum())
    rank = {"Low": 1, "Medium": 2, "High": 3}
    ti = ti.assign(_r=ti.threat_level.map(rank)).sort_values("_r").drop_duplicates("ip_address", keep="last").drop(columns="_r")
    out["threat_indicators"] = ti

    # event logs: dataset window from the 0.1%-99.9% quantiles (+/- 7 days), so a few bad
    # timestamps (e.g. a stray 2019 row) can't stretch the window and validate themselves
    auth_raw, txn_raw = rd("authentication_logs"), rd("transactions")
    ts = pd.to_datetime(pd.concat([auth_raw.timestamp, txn_raw.timestamp]), errors="coerce").dropna()
    start = ts.quantile(0.001) - pd.Timedelta(days=7)
    end = ts.quantile(0.999) + pd.Timedelta(days=7)
    report["dataset_window"] = {"start": str(start), "end": str(end)}

    log = report.setdefault("authentication_logs", {})
    a_ = auth_raw.copy()
    log["missing_mfa_status_filled"] = int(a_.mfa_status.isna().sum())
    a_["mfa_status"] = a_.mfa_status.fillna("n/a")     # logouts never have MFA
    out["authentication_logs"] = clean_events("authentication_logs", a_, log, users, start, end)

    log = report.setdefault("transactions", {})
    out["transactions"] = clean_events("transactions", txn_raw, log, users, start, end)

    log = report.setdefault("api_logs", {})
    out["api_logs"] = clean_events("api_logs", rd("api_logs"), log, users, start, end)

    for n, df in out.items():
        report[n]["rows_out"] = len(df)
        report[n]["remaining_nulls"] = int(df.isna().sum().sum())
        df.to_csv(proc / f"{n}.csv", index=False)

    Path(a.report).write_text(json.dumps(report, indent=2))

    print(f"{'file':22}{'in':>8}{'out':>8}{'removed':>9}  issues found")
    for n, r in report.items():
        if n == "dataset_window":
            continue
        issues = {k: v for k, v in r.items() if k not in ("rows_in", "rows_out", "remaining_nulls") and v}
        print(f"{n:22}{r['rows_in']:8}{r['rows_out']:8}{r['rows_in'] - r['rows_out']:9}  {issues or 'none'}")
    print(f"\ncleaned files -> {proc}\nreport        -> {a.report}")


if __name__ == "__main__":
    main()
