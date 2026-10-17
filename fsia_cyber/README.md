# FSIA Cybersecurity Layer

Detection rules, event correlation and MITRE ATT&CK mapping for the synthetic fintech security dataset.

## What it does
logs -> 9 detection rules -> alerts -> correlation -> incidents
-> MITRE ATT&CK mapping -> incidents.json (evidence for the AI module)

The AI module (`backend/ml/incidents.py`) imports `rules.py` and `correlate.py` directly and merges the rule
hits into its incidents (hybrid detection), so nothing has to be exported by hand.

## Run (from the repo root)
pip install pandas
python3 fsia_cyber/run.py
python3 fsia_cyber/rule_metrics.py

Defaults: data from `data/`, results to `fsia_cyber/output/`. Both take optional `[data_dir] [out_dir]` arguments.

## Files
- rules.py: detection rules and thresholds
- correlate.py: groups alerts into incidents, classifies, maps to MITRE
- evaluate.py: scores results against the ground-truth files
- run.py: runs the whole pipeline
- rule_metrics.py: precision and recall per rule
- output/: generated results (incidents.json, alerts.csv, metrics)

## Notes
data/ground_truth_*.csv are used only for evaluation, never for detection.
