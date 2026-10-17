"""
Write a small sample of every generated output to output/samples_for_backend.md, for the backend developer
(the outputs themselves are git-ignored). Synthetic data only - nothing secret.

Run (from repo root, after the pipeline):  python backend/ml/export_samples.py
"""
import json
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent / "output"


def block(title, lang, body):
    return f"## {title}\n\n```{lang}\n{body}\n```\n"


def main():
    parts = ["# Sample of the AI/ML outputs\n",
             f"pipeline_run.json:\n\n```json\n{(OUT / 'pipeline_run.json').read_text()}\n```\n"]
    for f in ("scored_auth.csv", "scored_txn.csv", "rule_alerts.csv"):
        df = pd.read_csv(OUT / f)
        flagged = df[df.is_flagged == 1] if "is_flagged" in df else df
        sample = pd.concat([df.head(2), flagged.head(1)])          # 2 normal rows + 1 flagged row
        parts.append(block(f"{f} (header + 3 rows of {len(df):,})", "csv", sample.to_csv(index=False).strip()))
    inc = json.loads((OUT / "incidents.json").read_text())
    parts.append(block(f"incidents.json (1 of {len(inc)}, highest risk)", "json", json.dumps(inc[0], indent=2,
                                                                                           ensure_ascii=False)))
    rp = OUT / "reports.json"
    if rp.exists():
        reps = json.loads(rp.read_text())
        r = next((x for x in reps if x["id"] == inc[0]["id"]), reps[0] if reps else None)
        if r: parts.append(block(f"reports.json (1 of {len(reps)})", "json", json.dumps(r, indent=2, ensure_ascii=False)))
    w = json.loads((OUT / "watchlist.json").read_text())
    parts.append(block(f"watchlist.json (1 of {len(w)})", "json", json.dumps(w[0], indent=2, ensure_ascii=False)))
    d = json.loads((OUT / "dashboard.json").read_text())
    d["live_events"], d["recent"] = d["live_events"][:3], d["recent"][:3]   # trimmed
    parts.append(block("dashboard.json (live_events and recent trimmed to 3)", "json",
                       json.dumps(d, indent=2, ensure_ascii=False)))
    (OUT / "samples_for_backend.md").write_text("\n".join(parts))
    print(f"wrote {OUT / 'samples_for_backend.md'}")


if __name__ == "__main__":
    main()
