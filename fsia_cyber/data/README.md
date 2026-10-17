# Synthetic Fintech Security Dataset (V1)

Period: 2026-09-01 to 2026-09-30 (timestamps local, IST). Seed 42 (reproducible).

| File | Rows | Purpose |
|---|---|---|
| authentication_logs.csv | ~25.4k | Logins/logouts (core detection input) |
| transactions.csv | ~8.1k | Financial activity |
| api_logs.csv | ~49.9k | Optional API activity |
| threat_indicators.csv | 300 | IP threat intel (60 High, 90 Medium, 150 Low) |
| users_devices.csv | 1,031 | Baseline: 800 users, registered devices, usual/secondary IP, avg_txn_amount |
| ground_truth_scenarios.csv | 195 | One row per injected attack: expected rules, MITRE technique, severity |
| ground_truth_events.csv | 1,271 | Maps event_id/transaction_id -> scenario_id (for testing only; do not feed to detector) |

Join keys: user_id, device_id, ip_address, timestamp.

## Injected scenarios
| Type | Count | MITRE |
|---|---|---|
| brute_force (10-15 fails, no success) | 40 | T1110 |
| suspicious_login (new device + new IP/location) | 40 | T1078 |
| account_takeover (5-9 fails -> success -> new beneficiary -> large transfer) | 30 | T1110, T1078, T1657 |
| suspicious_ip (login from High-threat IP, registered device) | 30 | T1078 |
| multi_account_ip (one IP hits 4-8 users) | 15 | T1110.004 |
| large_transaction (12-30x user's average, normal device/IP) | 40 | T1657 |

## Notes for detection rules
- Normal users only ever have a single failed login before a success, so "5+ failures in 10 min" cleanly separates attacks.
- Unregistered devices use IDs D90001+; registered devices are D00001-D01031.
- 20 Low-level indicators are real user IPs (shared ISP ranges): a false-positive check for threat-intel matching.
- About 65 of the High/Medium TI IPs never appear in the logs (realistic noise: most threat intel never touches you).
- Some attacks use IPs not in threat_indicators (so rules can't rely on TI alone).
