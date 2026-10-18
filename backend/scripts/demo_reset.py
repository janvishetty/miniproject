"""Reset the demo: every non-OPEN incident goes back to OPEN, then the demo states are set.

Run from backend/ with the API running (see README, "Demo reset"):
    python scripts/demo_reset.py --dry-run     # show the plan, change nothing
    python scripts/demo_reset.py               # asks for email + password, then asks to confirm

Needs a manager or admin account (analysts cannot set RESOLVED). Standard library only.
The token stays in memory; neither it nor the password is printed or logged.
"""
import argparse
import getpass
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_API = "http://127.0.0.1:8000"

# Demo end state: incident id -> status.
DEMO_STATES = {
    "INC-2026-0149": "INVESTIGATING",
    "INC-2026-0187": "CONTAINED",
    "INC-2026-0019": "RESOLVED",
}

RESET_STATUSES = ("INVESTIGATING", "CONTAINED", "RESOLVED")
STATUS_ORDER = ("OPEN", "INVESTIGATING", "CONTAINED", "RESOLVED")
TIMEOUT = 20


class Fatal(Exception):
    """Stops the run with a clear message (no row values, no tokens)."""


class Api:
    def __init__(self, base: str):
        if not base.lower().startswith(("http://", "https://")):
            raise Fatal("--api must start with http:// or https://")
        self.base = base.rstrip("/")
        self._token = None  # in memory only

    def call(self, method: str, path: str, body=None, auth: bool = True):
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if auth:
            headers["Authorization"] = "Bearer " + self._token
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.status, json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, _error_code(e)
        except urllib.error.URLError as e:
            if isinstance(e.reason, ConnectionRefusedError):
                raise Fatal(f"Cannot connect to {self.base}: connection refused. Is the API running? "
                            "(from backend/: uvicorn app.main:app)") from None
            raise Fatal(f"Cannot reach {self.base} ({type(e.reason).__name__})") from None
        except TimeoutError:
            raise Fatal(f"The API at {self.base} did not answer within {TIMEOUT}s") from None

    def login(self, email: str, password: str):
        status, payload = self.call("POST", "/auth/login", {"email": email, "password": password}, auth=False)
        if status == 401:
            raise Fatal("Login failed (401): wrong email or password.")
        if status == 429:
            raise Fatal("Login is rate limited (429): wait a minute and try again.")
        if status != 200 or not isinstance(payload, dict) or not payload.get("access_token"):
            raise Fatal(f"Login failed (HTTP {status}{_code(payload)}).")
        self._token = payload["access_token"]
        return (payload.get("profile") or {}).get("role")


def _error_code(e: urllib.error.HTTPError):
    """The API's error code ('forbidden', 'not_found', ...) or None. Never the message text."""
    try:
        code = json.loads(e.read() or b"{}")["error"]["code"]
        return code if isinstance(code, str) else None
    except (ValueError, KeyError, TypeError):
        return None


def _code(payload):
    return f", {payload}" if isinstance(payload, str) else ""


def check(status: int, payload, what: str):
    """Turn the common failures into one clear message. Returns the payload on 2xx."""
    if 200 <= status < 300:
        return payload
    if status == 401:
        raise Fatal(f"{what}: 401 the token was rejected (expired?). Run the script again.")
    if status == 403:
        raise Fatal(f"{what}: 403 this account is not allowed. Log in as a manager or admin "
                    "(analysts cannot set RESOLVED).")
    if status == 409:
        raise Fatal(f"{what}: 409 no pipeline run is loaded yet.")
    raise Fatal(f"{what}: HTTP {status}{_code(payload)}.")


def list_non_open(api: Api) -> dict:
    """{incident id: status} for INVESTIGATING / CONTAINED / RESOLVED, all pages."""
    found = {}
    for status in RESET_STATUSES:
        page = 1
        while True:
            query = urllib.parse.urlencode({"status": status, "page_size": 100, "page": page})
            res = check(*api.call("GET", "/incidents?" + query), f"List {status} incidents")
            items = res.get("items", [])
            for item in items:
                found[item["id"]] = item["status"]
            if not items or page * 100 >= res.get("total", 0):
                break
            page += 1
    return found


def status_counts(api: Api) -> dict:
    res = check(*api.call("GET", "/dashboard"), "Read dashboard")
    return {s: int((res.get("by_status") or {}).get(s, 0)) for s in STATUS_ORDER}


def build_plan(api: Api, non_open: dict):
    """Returns (steps, skipped). steps = [(id, from_status, to_status)] in the order they run."""
    steps, skipped = [], []
    state = dict(non_open)
    for inc_id, target in DEMO_STATES.items():
        if inc_id in state:
            continue
        status, payload = api.call("GET", f"/incidents/{inc_id}")
        if status == 404:
            skipped.append(inc_id)
            continue
        state[inc_id] = check(status, payload, f"Read {inc_id}")["status"]
    for inc_id, cur in non_open.items():
        if DEMO_STATES.get(inc_id) == cur:
            continue  # already in its demo state: leave it (no needless flip-flop in the audit log)
        steps.append((inc_id, cur, "OPEN"))
    for inc_id, target in DEMO_STATES.items():
        if inc_id in skipped or state[inc_id] == target:
            continue
        steps.append((inc_id, "OPEN", target))
    return steps, skipped


def project(counts: dict, steps) -> dict:
    out = dict(counts)
    for _, a, b in steps:
        out[a] -= 1
        out[b] += 1
    return out


def print_counts(label: str, counts: dict):
    print(f"{label}: " + ", ".join(f"{s} {counts[s]}" for s in STATUS_ORDER))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Reset incident statuses for the demo.")
    ap.add_argument("--api", default=DEFAULT_API, help=f"API base URL (default {DEFAULT_API})")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    ap.add_argument("--yes", action="store_true", help="do not ask for confirmation before changing")
    args = ap.parse_args(argv)

    try:
        api = Api(args.api)
        email = input("Email: ").strip()
        password = getpass.getpass("Password: ")
        role = api.login(email, password)
        del password
        if role is not None and role not in ("manager", "admin"):
            raise Fatal(f"403 this account's role is '{role}'. Log in as a manager or admin "
                        "(analysts cannot set RESOLVED). Nothing was changed.")
        print("Logged in.")

        non_open = list_non_open(api)
        before = status_counts(api)
        steps, skipped = build_plan(api, non_open)
        for inc_id in skipped:
            print(f"{inc_id}: not found in the current run, skipped")

        if args.dry_run:
            for inc_id, a, b in steps:
                print(f"[dry-run] {inc_id} {a} -> {b}")
            print_counts("Now", before)
            print_counts("After", project(before, steps))
            print("Dry run: nothing was changed.")
            return 0

        if not steps:
            print("Nothing to change.")
            print_counts("Now", before)
            return 0
        if not args.yes and input(f"Apply {len(steps)} change(s)? Type 'yes': ").strip().lower() != "yes":
            print("Cancelled, nothing changed.")
            return 1

        failed = 0
        for inc_id, a, b in steps:
            status, payload = api.call("PATCH", f"/incidents/{inc_id}", {"status": b})
            if status in (401, 403):
                check(status, payload, f"Update {inc_id}")  # stops the run
            if 200 <= status < 300:
                print(f"{inc_id} {a} -> {b}")
            else:
                failed += 1
                print(f"{inc_id} {a} -> {b}: FAILED (HTTP {status}{_code(payload)})")
        print_counts("Final", status_counts(api))
        if failed:
            print(f"{failed} change(s) failed.")
        return 1 if failed else 0
    except Fatal as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
