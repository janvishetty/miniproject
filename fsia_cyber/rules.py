"""Detection rules for the FSIA cybersecurity layer (V1).

Inputs only: authentication_logs, transactions, users_devices, threat_indicators.
The ground_truth_* files are NEVER loaded here; they are used only in evaluate.py.
"""
import pandas as pd

# ---- thresholds (tune these, then re-run evaluate.py) ----
BRUTE_FAILS, BRUTE_WINDOW = 5, pd.Timedelta(minutes=10)
FTS_MIN_FAILS, FTS_WINDOW = 2, pd.Timedelta(minutes=15)
LARGE_TXN_MULT = 10
MULTI_USERS, MULTI_WINDOW = 4, pd.Timedelta(minutes=60)
TRAVEL_WINDOW = pd.Timedelta(hours=3)
TI_LEVELS = {"High", "Medium"}   # Low is excluded on purpose: 20 Low IPs are shared ISP ranges used by real users
NEW_BENEFICIARY = "Wire Transfer - New Beneficiary"


def load(path="."):
    a = pd.read_csv(f"{path}/authentication_logs.csv", parse_dates=["timestamp"])
    t = pd.read_csv(f"{path}/transactions.csv", parse_dates=["timestamp"])
    u = pd.read_csv(f"{path}/users_devices.csv")
    ti = pd.read_csv(f"{path}/threat_indicators.csv")
    return a.sort_values("timestamp").reset_index(drop=True), t.sort_values("timestamp").reset_index(drop=True), u, ti


def _alert(rule, user, ip, start, end, events, **details):
    return dict(rule=rule, user_id=user, ip_address=ip, start=start, end=end,
                event_ids=list(events), details=details)


def r_brute_force(a):
    """>=5 failed logins for one user within 10 minutes."""
    out = []
    fails = a[(a.event_type == "login") & (a.status == "failed")]
    for user, g in fails.groupby("user_id"):
        g = g.sort_values("timestamp")
        times = g.timestamp.tolist(); idx = g.index.tolist()
        i, burst = 0, None
        for j in range(len(times)):
            while times[j] - times[i] > BRUTE_WINDOW:
                i += 1
            if j - i + 1 >= BRUTE_FAILS:
                if burst and times[i] <= burst["end"]:
                    burst["end"] = times[j]; burst["idx"].update(idx[i:j + 1])
                else:
                    if burst: out.append(burst)
                    burst = dict(user=user, start=times[i], end=times[j], idx=set(idx[i:j + 1]))
        if burst: out.append(burst)
    res = []
    for b in out:
        rows = a.loc[sorted(b["idx"])]
        res.append(_alert("R_BRUTE_FORCE", b["user"], rows.ip_address.mode()[0], b["start"], b["end"],
                          rows.event_id, failed_logins=len(rows)))
    return res


def r_fail_then_success(a):
    """>=2 failed logins followed by a successful login (same user) within 15 minutes."""
    res = []
    logins = a[a.event_type == "login"]
    for user, g in logins.groupby("user_id"):
        g = g.sort_values("timestamp")
        for pos, (i, row) in enumerate(g.iterrows()):
            if row.status != "success": continue
            prev = g[(g.timestamp < row.timestamp) & (g.timestamp >= row.timestamp - FTS_WINDOW)]
            pf = prev[prev.status == "failed"]
            if len(pf) >= FTS_MIN_FAILS:
                res.append(_alert("R_FAIL_THEN_SUCCESS", user, row.ip_address, pf.timestamp.min(), row.timestamp,
                                  list(pf.event_id) + [row.event_id], failed_before_success=len(pf)))
    return res


def _success_logins(a):
    return a[(a.event_type == "login") & (a.status == "success")]


def r_new_device(a, u):
    """Successful login from a device not registered to that user."""
    reg = set(zip(u.user_id, u.device_id))
    s = _success_logins(a)
    s = s[[(x, y) not in reg for x, y in zip(s.user_id, s.device_id)]]
    return [_alert("R_NEW_DEVICE_LOGIN", r.user_id, r.ip_address, r.timestamp, r.timestamp, [r.event_id],
                   device_id=r.device_id) for r in s.itertuples()]


def r_new_location(a, u):
    """Successful login from an IP that is not the user's usual/secondary IP AND a different city."""
    base = u.groupby("user_id").agg(loc=("usual_location", "first"), ip1=("usual_ip", "first"),
                                    ip2=("secondary_ip", "first"))
    s = _success_logins(a).join(base, on="user_id")
    s = s[(s.ip_address != s.ip1) & (s.ip_address != s.ip2) & (s.location != s["loc"])]
    return [_alert("R_NEW_LOCATION", r.user_id, r.ip_address, r.timestamp, r.timestamp, [r.event_id],
                   location=r.location, usual_location=r.loc) for r in s.itertuples()]


def r_ti_match(a, ti):
    """Login (any status) from an IP present in threat intel at a level in TI_LEVELS."""
    bad = ti[ti.threat_level.isin(TI_LEVELS)].set_index("ip_address")
    s = a[(a.event_type == "login") & a.ip_address.isin(bad.index)]
    return [_alert("R_TI_MATCH", r.user_id, r.ip_address, r.timestamp, r.timestamp, [r.event_id],
                   threat_level=bad.loc[r.ip_address, "threat_level"],
                   ti_description=bad.loc[r.ip_address, "description"]) for r in s.itertuples()]


def r_impossible_travel(a, u):
    """Impossible-travel candidate: successful login from a different COUNTRY than the user's usual one,
    or from a different country than their previous successful login within 3 hours."""
    res = []
    home = u.groupby("user_id").usual_location.first().str.split(",").str[-1].str.strip()
    s = _success_logins(a).copy()
    s["country"] = s.location.str.split(",").str[-1].str.strip()
    for user, g in s.groupby("user_id"):
        g = g.sort_values("timestamp"); prev = None
        for r in g.itertuples():
            foreign = r.country != home.get(user, r.country)
            quick = prev is not None and r.country != prev.country and r.timestamp - prev.timestamp <= TRAVEL_WINDOW
            if foreign or quick:
                res.append(_alert("R_IMPOSSIBLE_TRAVEL_CANDIDATE", user, r.ip_address,
                                  prev.timestamp if (quick and prev is not None) else r.timestamp, r.timestamp,
                                  [r.event_id], login_location=r.location, home_country=home.get(user),
                                  reason="foreign_country" if foreign else "country_change_within_3h"))
            prev = r
    return res


def r_large_txn(t, u):
    """Transaction >= 10x the user's average transaction amount."""
    avg = u.groupby("user_id").avg_txn_amount.first()
    t = t.join(avg, on="user_id")
    big = t[t.amount >= LARGE_TXN_MULT * t.avg_txn_amount]
    return [_alert("R_LARGE_TXN", r.user_id, r.ip_address, r.timestamp, r.timestamp, [r.transaction_id],
                   amount=r.amount, avg_txn_amount=r.avg_txn_amount, multiple=round(r.amount / r.avg_txn_amount, 1),
                   merchant=r.merchant) for r in big.itertuples()]


def r_new_beneficiary(t):
    """Context rule (not in ground-truth list): transfer to a new beneficiary."""
    nb = t[t.merchant == NEW_BENEFICIARY]
    return [_alert("R_NEW_BENEFICIARY", r.user_id, r.ip_address, r.timestamp, r.timestamp, [r.transaction_id],
                   amount=r.amount) for r in nb.itertuples()]


def r_multi_account_ip(a):
    """One IP touching >=4 distinct accounts within 60 minutes."""
    res, seen = [], set()
    login = a[a.event_type == "login"].sort_values("timestamp")
    for ip, g in login.groupby("ip_address"):
        if g.user_id.nunique() < MULTI_USERS: continue
        times = g.timestamp.tolist(); i = 0
        for j in range(len(times)):
            while times[j] - times[i] > MULTI_WINDOW: i += 1
            w = g.iloc[i:j + 1]
            if w.user_id.nunique() >= MULTI_USERS and (ip, w.timestamp.min()) not in seen:
                seen.add((ip, w.timestamp.min()))
                res.append(_alert("R_MULTI_ACCOUNT_IP", ",".join(sorted(w.user_id.unique())), ip,
                                  w.timestamp.min(), w.timestamp.max(), w.event_id, accounts=int(w.user_id.nunique())))
                break
    return res


def run_all(a, t, u, ti):
    alerts = (r_brute_force(a) + r_fail_then_success(a) + r_new_device(a, u) + r_new_location(a, u)
              + r_ti_match(a, ti) + r_impossible_travel(a, u) + r_large_txn(t, u) + r_new_beneficiary(t)
              + r_multi_account_ip(a))
    for n, al in enumerate(alerts, 1):
        al["alert_id"] = f"A{n:05d}"
    return alerts
