"""
Vantix - AI/ML module: ATTACK-INJECTION TEST (recall without an answer key).

Plants attacks with KNOWN labels into a COPY of the raw data, reruns the whole pipeline on the copy, and
measures how many planted attacks end up in an incident (detected) and with the right attack type.
Each attack type comes in an EASY and a STEALTHY variant, so the results also show where detection breaks.
Victims are users who are not in any real incident, so every detection is attributable.

The original data and outputs are never touched (everything happens in output/inject_test/).

Run (from repo root):  python backend/ml/inject_test.py [--per 10] [--seeds 5]   (~1 min per seed)
"""
import argparse
import json
import random
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd

ML = Path(__file__).resolve().parent
ROOT = ML.parents[1]
FOREIGN = ["Lagos, NG", "Moscow, RU", "Hanoi, VN", "Bucharest, RO", "Sao Paulo, BR"]
INDIAN = ["Pune, IN", "Kolkata, IN", "Jaipur, IN", "Lucknow, IN", "Ahmedabad, IN"]
NORMAL_MERCHANTS = ["Amazon India", "Flipkart", "Myntra", "Reliance Retail"]
CASHOUT = ["Crypto Exchange", "Overseas Remittance", "Gift Card Marketplace", "Wire Transfer - New Beneficiary"]

# expected incident type(s) per planted attack
EXPECT = {"brute_force": {"Brute Force", "Account Takeover"}, "credential_stuffing": {"Credential Stuffing"},
          "account_takeover": {"Account Takeover"}, "app_scam": {"Transaction Anomaly"}}


class Injector:
    def __init__(self, raw: Path, seed: int):
        self.r = random.Random(seed)
        self.auth = pd.read_csv(raw / "authentication_logs.csv")
        self.txn = pd.read_csv(raw / "transactions.csv")
        self.api = pd.read_csv(raw / "api_logs.csv")
        self.users = pd.read_csv(raw / "users_devices.csv")
        ti = pd.read_csv(raw / "threat_indicators.csv")
        self.bad_ips = ti[ti.threat_level == "High"].ip_address.tolist()
        self.known_ips = set(ti.ip_address) | set(self.auth.ip_address) | set(self.txn.ip_address)
        # ID ranges chosen so they can't collide with real data (real attacker devices already use D90001-D90125)
        self.n = {"E": 900000, "T": 900000, "A": 900000, "D": 990000, "ip": 0}
        self.rows = {"auth": [], "txn": [], "api": []}
        self.truth = []
        self.month = pd.Timestamp(self.auth.timestamp.min()).normalize()

    # ---- helpers
    def nid(self, k):
        self.n[k] += 1
        return f"{k}{self.n[k]}" if k != "D" else f"D{self.n[k]}"

    def clean_ip(self):
        """A fresh IP that is on no threat list and never seen in the data."""
        while True:
            ip = f"{self.r.choice([103, 117, 122, 157, 182])}.{self.r.randint(1, 254)}.{self.r.randint(1, 254)}.{self.r.randint(1, 254)}"
            if ip not in self.known_ips:
                self.known_ips.add(ip)
                return ip

    def when(self, night):
        day = self.r.randint(2, 27)
        hour = self.r.randint(1, 4) if night else self.r.randint(10, 17)
        return self.month + pd.Timedelta(days=day, hours=hour, minutes=self.r.randint(0, 59))

    def profile(self, u):
        p = self.users[self.users.user_id == u].iloc[0]
        return p.device_id, p.usual_ip, p.usual_location, float(p.avg_txn_amount)

    def login(self, ts, u, ip, dev, loc, ok, mfa="passed"):
        e = self.nid("E")
        self.rows["auth"].append({"event_id": e, "timestamp": ts, "user_id": u, "ip_address": ip, "device_id": dev,
                                  "event_type": "login", "status": "success" if ok else "failed", "location": loc,
                                  "mfa_status": mfa if ok else "not_prompted"})
        self.rows["api"].append({"event_id": self.nid("A"), "timestamp": ts, "user_id": u, "ip_address": ip,
                                 "endpoint": "/api/v1/login", "method": "POST", "status_code": 200 if ok else 401})
        return e

    def transfer(self, ts, u, ip, dev, loc, amount, merchant):
        t = self.nid("T")
        self.rows["txn"].append({"transaction_id": t, "timestamp": ts, "user_id": u, "amount": round(amount, 2),
                                 "merchant": merchant, "device_id": dev, "ip_address": ip, "location": loc,
                                 "status": "success"})
        self.rows["api"].append({"event_id": self.nid("A"), "timestamp": ts, "user_id": u, "ip_address": ip,
                                 "endpoint": "/api/v1/transfer", "method": "POST", "status_code": 200})
        return t

    def beneficiary(self, ts, u, ip):
        self.rows["api"].append({"event_id": self.nid("A"), "timestamp": ts, "user_id": u, "ip_address": ip,
                                 "endpoint": "/api/v1/beneficiaries", "method": "POST", "status_code": 201})

    def record(self, kind, level, events, users, note):
        self.truth.append({"attack_id": f"INJ-{len(self.truth) + 1:03d}", "type": kind, "difficulty": level,
                           "event_ids": events, "users": users, "note": note})

    # ---- attack generators
    def brute_force(self, u, easy):
        dev = self.nid("D")
        if easy:
            ip, loc, t0, n, gap = self.r.choice(self.bad_ips), self.r.choice(FOREIGN), self.when(True), 10, 30
        else:
            ip, loc, t0, n, gap = self.clean_ip(), self.r.choice(INDIAN), self.when(False), 6, 300
        ev = [self.login(t0 + pd.Timedelta(seconds=i * gap), u, ip, dev, loc, False) for i in range(n)]
        self.record("brute_force", "easy" if easy else "stealthy", ev, [u], f"{n} failed logins, {ip}, {loc}")

    def credential_stuffing(self, us, easy):
        if easy:
            ip, loc, t0, per, gap = self.r.choice(self.bad_ips), self.r.choice(FOREIGN), self.when(True), 2, 20
        else:
            ip, loc, t0, per, gap = self.clean_ip(), self.r.choice(INDIAN), self.when(False), 1, 600
        ev, k = [], 0
        for u in us:
            dev = self.nid("D")
            for _ in range(per):
                ev.append(self.login(t0 + pd.Timedelta(seconds=k * gap), u, ip, dev, loc, False))
                k += 1
        self.record("credential_stuffing", "easy" if easy else "stealthy", ev, list(us),
                    f"{len(ev)} failed logins on {len(us)} accounts from {ip}")

    def account_takeover(self, u, easy):
        _, _, home, avg = self.profile(u)
        dev = self.nid("D")
        if easy:
            ip, loc, t0 = self.r.choice(self.bad_ips), self.r.choice(FOREIGN), self.when(True)
            ev = [self.login(t0 + pd.Timedelta(seconds=i * 25), u, ip, dev, loc, False) for i in range(6)]
            t1 = t0 + pd.Timedelta(minutes=3)
            ev.append(self.login(t1, u, ip, dev, loc, True, mfa="not_required"))
            self.beneficiary(t1 + pd.Timedelta(minutes=2), u, ip)
            ev.append(self.transfer(t1 + pd.Timedelta(minutes=6), u, ip, dev, loc, avg * 30, self.r.choice(CASHOUT)))
            note = "6 fails -> login (new device, threat IP, abroad, night) -> beneficiary -> 30x transfer"
        else:
            ip, loc, t0 = self.clean_ip(), home, self.when(False)
            ev = [self.login(t0, u, ip, dev, loc, True)]
            ev.append(self.transfer(t0 + pd.Timedelta(minutes=12), u, ip, dev, loc, avg * 5,
                                    self.r.choice(NORMAL_MERCHANTS)))
            note = "1 login from new device + clean IP in home city, daytime -> 5x transfer"
        self.record("account_takeover", "easy" if easy else "stealthy", ev, [u], note)

    def app_scam(self, u, easy):
        dev, ip, home, avg = self.profile(u)
        t0 = self.when(False)
        ev = [self.login(t0, u, ip, dev, home, True)]
        mult = 30 if easy else 4
        ev.append(self.transfer(t0 + pd.Timedelta(minutes=8), u, ip, dev, home, avg * mult,
                                "Wire Transfer - New Beneficiary"))
        self.record("app_scam", "easy" if easy else "stealthy", ev, [u],
                    f"customer's own device + IP, {mult}x transfer to new beneficiary")

    def write(self, dst: Path, raw: Path):
        dst.mkdir(parents=True, exist_ok=True)
        for name, df, key in [("authentication_logs", self.auth, "auth"), ("transactions", self.txn, "txn"),
                              ("api_logs", self.api, "api")]:
            add = pd.DataFrame(self.rows[key])
            add["timestamp"] = add.timestamp.dt.strftime("%Y-%m-%d %H:%M:%S")
            pd.concat([df, add], ignore_index=True).to_csv(dst / f"{name}.csv", index=False)
        for f in ("users_devices.csv", "threat_indicators.csv"):
            shutil.copy(raw / f, dst / f)


def run(cmd):
    r = subprocess.run([sys.executable] + cmd, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"step failed: {' '.join(cmd)}\n{r.stderr[-2000:]}")


def one_run(raw, seed, per, busy, work):
    shutil.rmtree(work, ignore_errors=True)
    inj = Injector(raw, seed)
    pool = [u for u in inj.users.user_id.unique() if u not in busy]
    inj.r.shuffle(pool)
    take = lambda k: [pool.pop() for _ in range(k)]
    for easy in (True, False):
        for _ in range(per):
            inj.brute_force(take(1)[0], easy)
            inj.credential_stuffing(take(8 if easy else 5), easy)
            inj.account_takeover(take(1)[0], easy)
            inj.app_scam(take(1)[0], easy)
    inj.write(work / "raw", raw)
    (work / "ground_truth_injected.json").write_text(json.dumps(inj.truth, indent=2))

    out = work / "output"
    run([str(ML / "preprocess.py"), "--raw", str(work / "raw"), "--processed", str(work / "processed"),
         "--report", str(out / "preprocessing_report.json")])
    run([str(ML / "features.py"), "--data", str(work / "processed"), "--out", str(out)])
    run([str(ML / "model.py"), "--features", str(out), "--out", str(out)])
    run([str(ML / "incidents.py"), "--out", str(out), "--no-rules"])   # measures the ML alone

    incidents = json.loads((out / "incidents.json").read_text())
    watch = {e for w in json.loads((out / "watchlist.json").read_text()) for e in w["event_ids"]}
    ev2inc = {e: i for i in incidents for e in i["event_ids"]}
    rows = []
    for t in inj.truth:
        hits = [ev2inc[e] for e in t["event_ids"] if e in ev2inc]
        vectors = sorted({h["vector"] for h in hits})
        rows.append({"seed": seed, **{k: t[k] for k in ("attack_id", "type", "difficulty", "note")},
                     "detected": bool(hits), "type_correct": bool(set(vectors) & EXPECT[t["type"]]),
                     "only_on_watchlist": (not hits) and any(e in watch for e in t["event_ids"]),
                     "incident_types": vectors})
    return pd.DataFrame(rows)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--raw", default=str(ROOT / "data"))
    p.add_argument("--per", type=int, default=10, help="attacks per type per difficulty, per seed")
    p.add_argument("--seeds", type=int, default=5, help="repeat with this many different random seeds")
    a = p.parse_args()
    raw, base = Path(a.raw), ML / "output" / "inject_test"
    shutil.rmtree(base, ignore_errors=True)

    # victims: users not involved in any REAL incident or watch-list entry (pool doesn't depend on the filters)
    busy = set()
    for f in ("incidents.json", "watchlist.json"):
        fp = ML / "output" / f
        if fp.exists():
            busy |= {u for i in json.loads(fp.read_text()) for u in i["users"]}

    runs = []
    for k in range(a.seeds):
        seed = 7 + k
        print(f"seed {seed}: planting {a.per * 8} attacks and rerunning the pipeline on a copy...", flush=True)
        runs.append(one_run(raw, seed, a.per, busy, base / f"seed_{seed}"))
    df = pd.concat(runs, ignore_index=True)

    per_seed = (df.groupby(["type", "difficulty", "seed"]).detected.mean().reset_index())
    agg = (per_seed.groupby(["type", "difficulty"]).detected.agg(["mean", "min", "max"]).reset_index()
           .rename(columns={"mean": "recall", "min": "recall_min", "max": "recall_max"}))
    tc = df.groupby(["type", "difficulty"]).type_correct.mean().rename("type_accuracy").reset_index()
    summary = agg.merge(tc, on=["type", "difficulty"]).round(3)
    summary["attacks"] = a.per * a.seeds

    print(f"\nB. ATTACK-INJECTION TEST  ({a.seeds} seeds x {a.per} attacks per row = {a.per * a.seeds} per row)")
    print(f"   {'attack':22}{'difficulty':11}{'recall (mean)':>14}{'range over seeds':>18}{'right type':>12}")
    for _, r in summary.iterrows():
        print(f"   {r.type:22}{r.difficulty:11}{r.recall:>14.0%}{f'{r.recall_min:.0%}-{r.recall_max:.0%}':>18}"
              f"{r.type_accuracy:>12.0%}")
    print(f"   overall: {df.detected.mean():.0%} | easy {df[df.difficulty == 'easy'].detected.mean():.0%} | "
          f"stealthy {df[df.difficulty == 'stealthy'].detected.mean():.0%} | "
          f"misses caused by watch-list filter: {int(df.only_on_watchlist.sum())}")

    df.to_csv(base / "injection_results.csv", index=False)
    (base / "injection_summary.json").write_text(summary.to_json(orient="records", indent=2))
    print(f"\nsaved -> {base}/injection_results.csv, injection_summary.json")


if __name__ == "__main__":
    main()
