# Results: Vantix (FSIA)

All figures are measured on the synthetic dataset. Nothing here is projected.

## 1. Data ingested

| Table | Rows |
|---|---|
| authentication_logs | 25,438 |
| api_logs | 49,931 |
| transactions | 8,081 |
| users_devices | 1,031 |
| threat_indicators | 300 |

83,450 events loaded.

## 2. Detection pipeline

- **ML (Isolation Forest + SHAP):** 24,554 login/transaction events scored; 1,072 flagged (952 logins + 120 transfers) = 4.4%.
- **Rules:** 2,067 rule alerts on 1,070 distinct events.

| Event funnel | Count |
|---|---|
| Model-flagged | 1,072 |
| Rule-only | 63 |
| Grouped | 1,135 |
| In incidents | 1,061 |
| Watchlist | 74 |

## 3. Incidents

194 incidents, all detected by ml+rules, with 1,061 linked events. Account-takeover transfers total Rs 2,438,000.

| Severity | Incidents |
|---|---|
| Critical | 34 |
| High | 41 |
| Medium | 119 |
| Low | 0 |

| Type | Incidents |
|---|---|
| Suspicious Login | 69 |
| Brute Force | 40 |
| Transaction Anomaly | 40 |
| Account Takeover | 30 |
| Credential Stuffing | 15 |

## 4. Timings (Apple M4 laptop)

| Step | Time |
|---|---|
| Pipeline | 39.6 s |
| DB load (27,878 rows, 0 rejected) | 42.3 s |
| Force reload | ~46 s |

## 5. LLM reports (llama3.2:3b via Ollama, local)

75/75 critical+high reports verified (100%), about 12 s per report.

| Outcome | Reports |
|---|---|
| Passed first try | 54 |
| Passed after self-correction | 67 |
| Verified template fallback | 8 |

A stricter grounding check (a transaction id used as a login/device) caught 3 earlier reports, which were regenerated.

## 6. Copilot

The welcome summary is built from code (0 s). Free questions are answered by the LLM in about 11-34 s, grounded against incident data.

## 7. Tests

356 backend tests pass. The frontend type-check is clean and the production build passes.

## 8. Evaluation against the answer key

Source: `backend/ml/output/evaluation.json` (Janvi, ML pipeline), read-only.

| | ML only | Hybrid (ML + rules) |
|---|---|---|
| Incidents | 203 | 194 |
| Scenarios caught | 195 / 195 | 195 / 195 |
| False-positive incidents | 9 (all low) | 0 |
| Precision | 95.6% | 100% |
| Severity vs key (195) | 106 match, 4 higher, 85 lower | 191 match, 4 higher |

**Cash-out proxy (Janvi):** 53 cash-out transfers out of 8,081; all 53 caught at score >= 60. The top 41 by score are all cash-out (precision@41 = 100%). At threshold 80, 41 are flagged, all cash-out (recall 77.4%).

**Analyst review precision (Janvi):** 67.6% before noise filters, 88.2% after.

| Type | Round 1 (before filters) | Round 2 (after filters) |
|---|---|---|
| Suspicious Login | 4 / 6 real (66.7%) | 7 / 7 (100%) |
| Transaction Anomaly | 2 / 6 real (33.3%) | 3 / 7 (42.9%) |

Round 2 reviewed only these two types.

**Own attack injection:** 100% of 400 planted attacks. This figure is from the README; it is not in evaluation.json.

README figures match evaluation.json wherever both report a number.

## 9. Caveats

- The data is synthetic.
- Rule thresholds were tuned while looking at the answer key, so detection figures are optimistic.
- Correlation is entity-based (user/IP/time), not graph-based.
- The small LLM can mis-relate facts; the grounding check and the template fallback contain this.
- Analyst status changes belong to one pipeline run.
- There is no response-time data.

## 10. Credits

| Area | Owner |
|---|---|
| ML/LLM pipeline | Janvi |
| Rule engine | Aarushi |
| Backend/API/integration | Anushka |
| Frontend design | Lakshayaa and Ayush |
