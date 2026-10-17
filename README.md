# FSIA Cybersecurity Layer

Detection rules, event correlation and MITRE ATT&CK mapping for the
synthetic fintech security dataset.

## What it does
logs -> 9 detection rules -> alerts -> correlation -> incidents
-> MITRE ATT&CK mapping -> incidents.json (evidence for the AI module)

## Run
pip install pandas
python run.py data output
python rule_metrics.py data output

## Files
- rules.py: detection rules and thresholds
- correlate.py: groups alerts into incidents, classifies, maps to MITRE
- evaluate.py: scores results against the ground-truth files
- run.py: runs the whole pipeline
- rule_metrics.py: precision and recall per rule
- output/: generated results (incidents.json, alerts.csv, metrics)

## Notes
ground_truth_*.csv are used only for evaluation, never for detection.
