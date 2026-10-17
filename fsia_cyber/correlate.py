"""Event correlation: merge related alerts into one incident, classify it, map to MITRE ATT&CK."""
import pandas as pd

USER_GAP = pd.Timedelta(minutes=15)   # same user, alerts this close together -> same incident
IP_GAP = pd.Timedelta(minutes=60)     # same attacker IP (TI-flagged / multi-account only)

MITRE = {
    "T1110":     "Brute Force",
    "T1110.004": "Credential Stuffing",
    "T1078":     "Valid Accounts",
    "T1657":     "Financial Theft",
}


def _users(al):
    return al["user_id"].split(",")


def _gap(x, y):
    """Time gap between two alert intervals (0 if they overlap)."""
    return max(x["start"] - y["end"], y["start"] - x["end"], pd.Timedelta(0))


def correlate(alerts):
    n = len(alerts)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i

    def union(i, j):
        parent[find(i)] = find(j)

    # IPs worth linking on: threat-intel hits and IPs that hit many accounts
    hot_ips = {x["ip_address"] for x in alerts if x["rule"] in ("R_TI_MATCH", "R_MULTI_ACCOUNT_IP")}

    by_user, by_ip = {}, {}
    for i, al in enumerate(alerts):
        for usr in _users(al):
            by_user.setdefault(usr, []).append(i)
        if al["ip_address"] in hot_ips:
            by_ip.setdefault(al["ip_address"], []).append(i)

    for idxs in by_user.values():
        idxs.sort(key=lambda k: alerts[k]["start"])
        for p in range(len(idxs)):
            for q in range(p + 1, len(idxs)):
                if alerts[idxs[q]]["start"] - alerts[idxs[p]]["end"] > USER_GAP: break
                if _gap(alerts[idxs[p]], alerts[idxs[q]]) <= USER_GAP: union(idxs[p], idxs[q])
    for idxs in by_ip.values():
        idxs.sort(key=lambda k: alerts[k]["start"])
        for p in range(len(idxs)):
            for q in range(p + 1, len(idxs)):
                if alerts[idxs[q]]["start"] - alerts[idxs[p]]["end"] > IP_GAP: break
                union(idxs[p], idxs[q])

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(alerts[i])
    incidents = [build_incident(g) for g in groups.values()]
    incidents.sort(key=lambda x: x["start"])
    for k, inc in enumerate(incidents, 1):
        inc["incident_id"] = f"INC-{k:04d}"
    return incidents


def classify(rules, has_success_login):
    """Return (attack_type, severity, [mitre ids])."""
    r = set(rules)
    if "R_MULTI_ACCOUNT_IP" in r:
        return "Credential Stuffing / Password Spraying", "High", ["T1110.004"]
    if ({"R_BRUTE_FORCE", "R_FAIL_THEN_SUCCESS"} & r) and ({"R_LARGE_TXN", "R_NEW_BENEFICIARY"} & r) \
            and has_success_login:
        return "Account Takeover", "Critical", ["T1110", "T1078", "T1657"]
    if "R_BRUTE_FORCE" in r:
        return "Brute Force", "Medium", ["T1110"]
    if "R_NEW_DEVICE_LOGIN" in r and "R_LARGE_TXN" in r:
        return "Suspicious Login + Large Transaction", "High", ["T1078", "T1657"]
    if "R_TI_MATCH" in r:
        return "Login From Known-Malicious IP", "High", ["T1078"]
    if "R_NEW_DEVICE_LOGIN" in r and "R_NEW_LOCATION" in r:
        return "Suspicious Login", "Medium", ["T1078"]
    if "R_LARGE_TXN" in r:
        return "Anomalous Large Transaction", "Medium", ["T1657"]
    return "Low-Confidence Anomaly", "Low", []


def build_incident(group):
    rules = sorted({a["rule"] for a in group})
    users = sorted({u for a in group for u in _users(a)})
    ips = sorted({a["ip_address"] for a in group})
    events = sorted({e for a in group for e in a["event_ids"]})
    has_success = any(a["rule"] in ("R_FAIL_THEN_SUCCESS", "R_NEW_DEVICE_LOGIN", "R_NEW_LOCATION") for a in group)
    attack, severity, mitre = classify(rules, has_success)
    return dict(
        start=min(a["start"] for a in group), end=max(a["end"] for a in group),
        user_ids=users, ip_addresses=ips, attack_type=attack, severity=severity,
        mitre=[{"id": m, "name": MITRE[m]} for m in mitre], rules_triggered=rules,
        alerts=group, event_ids=events,
    )
