# Vantix: FinTech Security Investigation Assistant (FSIA)

Hybrid explainable-AI platform for investigating security incidents in FinTech logs. A rule engine and an
unsupervised ML model both flag suspicious events. They are merged into one incident list, each incident is
explained (SHAP plus the rules that fired), and a local LLM writes verified incident reports and answers analyst
questions in the AI Copilot.

```
data/*.csv ──► fsia_cyber/  (rules, correlation, MITRE)  ─┐
          └──► backend/ml/  (Isolation Forest + SHAP)    ─┴─► backend/ml/incidents.py (hybrid merge)
                                                                ──► reports + Copilot (Ollama, verified)
                                                                ──► backend API (FastAPI) ──► frontend/
```

## Folders

| Folder | What | Owner | Guide |
|---|---|---|---|
| `data/` | Synthetic dataset (Sept 2026) + answer key `ground_truth_*.csv` (evaluation only) | Aarushi | [data/README.md](data/README.md) |
| `fsia_cyber/` | Cybersecurity layer: 9 detection rules, alert correlation, MITRE ATT&CK mapping | Aarushi | [fsia_cyber/README.md](fsia_cyber/README.md) |
| `backend/ml/` | AI/ML: preprocessing, anomaly detection, SHAP, hybrid incidents, LLM reports, Copilot, evaluation | Janvi | [backend/ml/README.md](backend/ml/README.md) |
| `backend/` | API (FastAPI) serving incidents, reports and the Copilot | Anushka | |
| `frontend/` | Vite + React dashboard | | `cd frontend && npm install && npm run dev` |
| `docs/` | Labelled analyst-review sheets used in the evaluation | Janvi | |

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate      # Python 3.11+
pip install -r backend/ml/requirements.txt
python3 backend/ml/preprocess.py
python3 backend/ml/features.py
python3 backend/ml/model.py
python3 backend/ml/incidents.py        # runs the fsia_cyber rules too (hybrid)
python3 backend/ml/summarize.py        # needs Ollama + llama3.2:3b
python3 backend/ml/evaluate.py
```

Rules on their own: `python3 fsia_cyber/run.py`.

## Results (against the answer key, 195 planted attacks)

| Detector | Attacks caught | False-positive incidents |
|---|---|---|
| ML only (never sees rules or labels) | 194 / 195 | 9 of 202 (all low severity) |
| Rules only | 195 / 195 | 0 of 195 |
| **Hybrid (ML + rules)** | **195 / 195** | 9 of 203 (all low severity) |

The rule thresholds were set with the dataset generator's settings in mind (see `data/README.md`), so the rules'
perfect score is expected on this data. The ML model was never tuned to it.
