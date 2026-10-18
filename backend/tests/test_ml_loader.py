"""ml_loader: parsers (no database) and load() against the fake Supabase.
All data is the synthetic set in tests/fixtures/ml_output/."""
import csv
import json
import shutil
from pathlib import Path

import pytest

from app.services import ingestion, ml_loader

FIX = Path(__file__).parent / "fixtures" / "ml_output"
FP = "abc123def456"
ALL_EVENT_IDS = ["E900001", "E900002", "E900003", "T900001", "T900002"]


@pytest.fixture
def out(tmp_path):
    target = tmp_path / "out"
    shutil.copytree(FIX, target)
    return target


def edit_json(path, fn):
    data = json.loads(path.read_text())
    fn(data)                                   # fn mutates in place; its return value is ignored
    path.write_text(json.dumps(data))


def edit_csv(path, fn):
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        header, rows = reader.fieldnames, list(reader)
    fn(rows)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=header, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def seed_events(fake, ids=ALL_EVENT_IDS):
    fake.tables["events"] = [{"event_id": i} for i in ids]


def seed_old_current_run(fake):
    fake.tables["pipeline_runs"] = [{"id": "old-run", "status": "completed", "is_current": True,
                                     "source_fingerprint": "oldfingerp0"}]


def current_runs(fake):
    return [r["id"] for r in fake.tables["pipeline_runs"] if r.get("is_current")]


# ------------------------------------ parsers ------------------------------------
def test_ml_results_use_is_flagged_and_ignore_is_anomaly(out):
    p = ml_loader.parse_outputs(out)
    flags = {r["event_id"]: r["is_anomalous"] for r in p.ml_results}
    assert flags == {"E900001": True, "E900002": False, "E900003": True,
                     "T900001": True, "T900002": True}      # E900002 has is_anomaly=1, flagged=0
    assert p.flagged_count == 4


def test_ml_results_empty_flag_reason_is_null_and_guard_kept(out):
    p = ml_loader.parse_outputs(out)
    reasons = {r["event_id"]: r["flag_reason"] for r in p.ml_results}
    assert reasons["E900002"] is None
    assert reasons["E900001"] == "model"
    assert reasons["T900002"] == "guard: amount"


def test_ml_results_shap_parsed_from_json_string(out):
    p = ml_loader.parse_outputs(out)
    first = next(r for r in p.ml_results if r["event_id"] == "E900001")
    assert isinstance(first["shap_reasons"], list) and first["shap_reasons"][0]["feature"] == "ip_threat_score"
    assert first["anomaly_score"] == 91.5


def test_bad_is_flagged_value_is_skipped_and_counted(out):
    edit_csv(out / "scored_auth.csv", lambda rows: rows[0].update(is_flagged="yes"))
    p = ml_loader.parse_outputs(out)
    assert len(p.ml_results) == 4
    assert p.skips["ml_results"]["bad_is_flagged"] == 1


def test_bad_anomaly_score_and_bad_top_reasons_skipped(out):
    def mutate(rows):
        rows[0]["anomaly_score"] = "abc"
        rows[1]["top_reasons"] = "{not json"
    edit_csv(out / "scored_auth.csv", mutate)
    p = ml_loader.parse_outputs(out)
    assert p.skips["ml_results"] == {"bad_anomaly_score": 1, "bad_top_reasons": 1}
    assert len(p.ml_results) == 3


def test_incident_none_threat_level_becomes_null_but_raw_keeps_it(out):
    row = ml_loader.parse_outputs(out).incidents[0]
    assert row["ip_threat_level"] is None
    assert row["raw"]["ip_threat_level"] == "None"


def test_incident_own_run_id_key_only_in_raw(out):
    row = ml_loader.parse_outputs(out).incidents[0]
    assert "pipeline_run_id" not in row
    assert row["raw"]["pipeline_run_id"] == FP
    assert row["raw"]["created"] == "00:00"          # "created" only lives in raw
    assert "created" not in row


def test_incident_columns_mapped(out):
    row = ml_loader.parse_outputs(out).incidents[0]
    assert row["external_id"] == "INC-2026-9001" and row["source_ip"] == "10.0.0.1"
    assert row["severity"] == "critical" and row["status"] == "OPEN"
    assert row["started_at"] == "2026-09-01T00:00:01+00:00"       # naive -> UTC
    assert row["ended_at"] == "2026-09-01T00:01:01+00:00"
    assert row["event_count"] == 3 and row["amount_total"] == 100.0
    assert row["rule_mitre"] == ["T1110 Brute Force"] and row["threat_intel"] is None


def test_incident_severity_lowercased_and_invalid_skipped(out):
    def mutate(items):
        items[0]["sev"] = " CRITICAL "
        extra = dict(items[0], id="INC-2026-9005", sev="urgent")
        items.append(extra)
    edit_json(out / "incidents.json", mutate)
    p = ml_loader.parse_outputs(out)
    assert [r["severity"] for r in p.incidents] == ["critical"]
    assert p.skips["incidents"]["bad_severity"] == 1


def test_incident_status_outside_allowed_set_becomes_open(out):
    edit_json(out / "incidents.json", lambda items: items[0].update(status="WEIRD"))
    assert ml_loader.parse_outputs(out).incidents[0]["status"] == "OPEN"
    edit_json(out / "incidents.json", lambda items: items[0].update(status="CONTAINED"))
    assert ml_loader.parse_outputs(out).incidents[0]["status"] == "CONTAINED"


@pytest.mark.parametrize("field,value", [("confidence", "abc"), ("risk_score", 1000),
                                         ("amount_total", float("inf")), ("event_count", 1.5)])
def test_incident_unparsable_or_out_of_range_numbers_skipped(out, field, value):
    def mutate(items):
        items[0][field] = value
    path = out / "incidents.json"
    data = json.loads(path.read_text())
    mutate(data)
    path.write_text(json.dumps(data))             # json.dumps writes Infinity -> rejected as non-finite
    try:
        p = ml_loader.parse_outputs(out)
    except ml_loader.InconsistentOutputError:
        assert value == float("inf")              # non-finite JSON is refused outright
        return
    assert p.incidents == [] and p.skips["incidents"]["bad_number"] == 1


def test_incident_pairs(out):
    p = ml_loader.parse_outputs(out)
    assert p.incident_pairs == [("INC-2026-9001", "E900001"), ("INC-2026-9001", "E900002"),
                                ("INC-2026-9001", "T900001")]


def test_rule_alerts_parsed_lowercase_utc(out):
    p = ml_loader.parse_outputs(out)
    assert len(p.rule_alerts) == 3
    first = p.rule_alerts[0]
    assert first == {"event_id": "E900001", "rule_id": "R_BRUTE_FORCE", "rule_name": "Brute force",
                     "severity": "critical", "ts": "2026-09-01T00:00:01+00:00"}


def test_rule_alert_bad_severity_bad_timestamp_and_duplicate_skipped(out):
    def mutate(rows):
        rows[0]["severity"] = "CRITICAL"            # lowercased, fine
        rows[1]["severity"] = "urgent"
        rows[2]["timestamp"] = "not a time"
        rows.append(dict(rows[0]))                  # duplicate (event_id, rule_id)
    edit_csv(out / "rule_alerts.csv", mutate)
    p = ml_loader.parse_outputs(out)
    assert len(p.rule_alerts) == 1 and p.rule_alerts[0]["severity"] == "critical"
    assert p.skips["rule_alerts"] == {"bad_severity": 1, "bad_timestamp": 1, "duplicate_pair": 1}


def test_reports_stale_skipped_and_counted_good_one_mapped(out):
    p = ml_loader.parse_outputs(out)
    assert len(p.reports) == 1
    assert p.skips["reports"] == {"stale_run_id": 1}
    r = p.reports[0]
    assert r["external_id"] == "INC-2026-9001" and r["source"] == "llm"
    assert r["grounded"] is True and r["unverified"] == []
    assert r["raw"]["pipeline_run_id"] == FP
    assert r["containment_actions"] == ["Lock the account"]


def test_report_bad_source_and_bad_grounding_skipped(out):
    def mutate(items):
        items[0]["source"] = "gpt"
        items.append(dict(items[0], id="INC-2026-9001", source="llm", grounding={"grounded": "yes"}))
    edit_json(out / "reports.json", mutate)
    p = ml_loader.parse_outputs(out)
    assert p.reports == []
    assert p.skips["reports"]["bad_source"] == 1 and p.skips["reports"]["bad_grounding"] == 1


def test_reports_file_is_optional(out):
    (out / "reports.json").unlink()
    p = ml_loader.parse_outputs(out)
    assert p.reports == [] and p.reports_file_present is False and p.rows_read["reports"] == 0


def test_missing_required_file_says_run_the_pipeline_first(out):
    (out / "scored_txn.csv").unlink()
    with pytest.raises(ml_loader.MissingOutputError) as info:
        ml_loader.read_outputs(out)
    assert "run the pipeline first" in str(info.value) and "scored_txn.csv" in str(info.value)


@pytest.mark.parametrize("name,change", [
    ("dashboard.json", lambda d: d.update(pipeline_run_id="ffffffffffff")),
    ("pipeline_run.json", lambda d: d.update(pipeline_run_id="ffffffffffff")),
    ("incidents.json", lambda d: d[0].update(pipeline_run_id="ffffffffffff")),
    ("incidents.json", lambda d: d[0].pop("pipeline_run_id")),
])
def test_mismatched_fingerprint_is_inconsistent(out, name, change):
    edit_json(out / name, change)
    with pytest.raises(ml_loader.InconsistentOutputError) as info:
        ml_loader.parse_outputs(out)
    assert "pipeline_run_id differs" in str(info.value)


def test_non_finite_json_is_refused(out):
    (out / "dashboard.json").write_text('{"pipeline_run_id": "abc123def456", "x": NaN}')
    with pytest.raises(ml_loader.InconsistentOutputError):
        ml_loader.parse_outputs(out)


def test_only_allowlisted_filenames(out):
    with pytest.raises(ValueError):
        ml_loader._path(out, "scored_auth.csv.bak")
    with pytest.raises(ValueError):
        ml_loader._path(out, "../secrets.json")


def test_dry_parse_counts_and_checks(out):
    r = ml_loader.dry_parse(out)
    assert r["fingerprint"] == FP and r["flagged_count"] == 4 and r["stale_reports"] == 1
    assert r["ready"] == {"pipeline_runs": 1, "ml_results": 5, "incidents": 1, "incident_events": 3,
                          "rule_alerts": 3, "reports": 1, "dashboard_snapshots": 1}
    assert {t["table"]: t["rows_read"] for t in r["tables"]}["ml_results"] == 5
    assert r["checks"]["funnel_adds_up"] is True
    assert r["checks"]["event_count_matches_event_ids"] is True
    assert r["checks"]["severity_matches_dashboard"] is True
    assert r["checks"]["pipeline_run_incident_count_matches"] is True
    assert r["source_created_at"] == "2026-10-18T09:11:13"


# ------------------------------------ load() ------------------------------------
def test_load_success_writes_everything_once(fake, out):
    seed_events(fake)
    seed_old_current_run(fake)
    report = ml_loader.load(out)
    assert report["outcome"] == "loaded"

    runs = [r for r in fake.tables["pipeline_runs"] if r["id"] != "old-run"]
    assert len(runs) == 1
    run = runs[0]
    assert run["status"] == "completed" and run["is_current"] is True and run["trigger"] == "api"
    assert run["source_fingerprint"] == FP
    assert run["events_scored"] == 5 and run["incident_count"] == 1
    assert run["notes"] == "source_created_at=2026-10-18T09:11:13"
    assert current_runs(fake) == [run["id"]]                       # old run switched off by the rpc

    assert len(fake.tables["ml_results"]) == 5
    assert {r["pipeline_run_id"] for r in fake.tables["ml_results"]} == {run["id"]}
    incident = fake.tables["incidents"][0]
    assert incident["pipeline_run_id"] == run["id"] != FP
    assert incident["raw"]["pipeline_run_id"] == FP and incident["ip_threat_level"] is None
    assert [r["incident_id"] for r in fake.tables["incident_events"]] == [incident["id"]] * 3
    assert len(fake.tables["rule_alerts"]) == 3
    assert fake.tables["reports"][0]["incident_id"] == incident["id"]
    assert fake.tables["dashboard_snapshots"][0]["pipeline_run_id"] == run["id"]
    assert fake.rpc_calls == [("set_current_run", {"run_id": run["id"]})]    # exactly once

    tables = {t["table"]: t for t in report["tables"]}
    assert tables["ml_results"]["rows_written"] == 5 and tables["reports"]["rows_written"] == 1
    assert report["stale_reports"] == 1


def test_unknown_event_ids_are_skipped_and_counted(fake, out):
    seed_events(fake, ["E900001", "E900002", "T900001"])          # no E900003, no T900002
    report = ml_loader.load(out)
    tables = {t["table"]: t for t in report["tables"]}
    assert tables["ml_results"]["rows_written"] == 3
    assert tables["ml_results"]["skip_reasons"] == {"unknown_event_id": 2}
    assert tables["rule_alerts"]["rows_written"] == 2
    assert tables["rule_alerts"]["skip_reasons"] == {"unknown_event_id": 1}
    assert tables["incident_events"]["rows_written"] == 3
    assert len(fake.tables["ml_results"]) == 3 and len(fake.tables["rule_alerts"]) == 2


def test_same_completed_fingerprint_is_already_loaded(fake, out):
    seed_events(fake)
    first = ml_loader.load(out)
    before = {t: len(rows) for t, rows in fake.tables.items()}
    second = ml_loader.load(out)
    assert second["outcome"] == "already_loaded" and second["run_id"] == first["run_id"]
    assert all(t["rows_written"] == 0 for t in second["tables"])
    assert {t: len(rows) for t, rows in fake.tables.items()} == before
    assert len(fake.rpc_calls) == 1


def test_force_reupserts_into_the_same_run(fake, out):
    seed_events(fake)
    first = ml_loader.load(out)
    forced = ml_loader.load(out, force=True)
    assert forced["outcome"] == "reloaded" and forced["run_id"] == first["run_id"]
    assert len(fake.tables["pipeline_runs"]) == 1                  # no second run row
    assert fake.tables["pipeline_runs"][0]["is_current"] is True and current_runs(fake) == [first["run_id"]]
    assert len(fake.tables["ml_results"]) == 5 and len(fake.tables["incidents"]) == 1
    assert {t["table"]: t["rows_written"] for t in forced["tables"]}["ml_results"] == 5
    assert len(fake.rpc_calls) == 1                                # force does not switch current again


def test_mismatched_fingerprint_writes_nothing(fake, out):
    seed_events(fake)
    edit_json(out / "dashboard.json", lambda d: d.update(pipeline_run_id="ffffffffffff"))
    with pytest.raises(ml_loader.InconsistentOutputError):
        ml_loader.load(out)
    assert not fake.tables.get("pipeline_runs") and not fake.tables.get("ml_results")
    assert fake.rpc_calls == []


def test_missing_file_writes_nothing(fake, out):
    (out / "incidents.json").unlink()
    with pytest.raises(ml_loader.MissingOutputError):
        ml_loader.load(out)
    assert not fake.tables.get("pipeline_runs") and fake.rpc_calls == []


def test_count_mismatch_fails_run_and_keeps_previous_current(fake, out):
    seed_events(fake)
    seed_old_current_run(fake)
    fake.silent_drop_upserts["ml_results"] = 1                     # DB ends up with one row fewer
    with pytest.raises(ml_loader.LoadError) as info:
        ml_loader.load(out)
    assert info.value.public_message == "ValueError at step verify"
    new = [r for r in fake.tables["pipeline_runs"] if r["id"] != "old-run"][0]
    assert new["status"] == "failed" and new["error_message"] == "ValueError at step verify"
    assert new["is_current"] is False and current_runs(fake) == ["old-run"]
    assert fake.rpc_calls == []                                    # never on failure
    assert "E900001" not in new["error_message"]


def test_upsert_failure_fails_run_without_rpc(fake, out, monkeypatch):
    monkeypatch.setattr(ingestion, "RETRY_BASE_DELAY", 0)
    seed_events(fake)
    seed_old_current_run(fake)
    fake.fail_upserts_times["incidents"] = 99
    with pytest.raises(ml_loader.LoadError) as info:
        ml_loader.load(out)
    assert info.value.public_message == "IngestionError at step incidents"
    new = [r for r in fake.tables["pipeline_runs"] if r["id"] != "old-run"][0]
    assert new["status"] == "failed" and new["error_message"] == "IngestionError at step incidents"
    assert current_runs(fake) == ["old-run"] and fake.rpc_calls == []


def test_missing_set_current_run_function_fails_run_with_clear_message(fake, out):
    seed_events(fake)
    seed_old_current_run(fake)
    fake.fail_rpc = "missing"
    with pytest.raises(ml_loader.LoadError) as info:
        ml_loader.load(out)
    assert info.value.public_message == "set_current_run missing: run migration 004"
    new = [r for r in fake.tables["pipeline_runs"] if r["id"] != "old-run"][0]
    assert new["status"] == "failed"
    assert new["error_message"] == "set_current_run missing: run migration 004"
    assert current_runs(fake) == ["old-run"]
    assert len(fake.rpc_calls) == 1                                # tried once, never retried


def test_other_rpc_failure_fails_run_and_is_not_retried(fake, out):
    seed_events(fake)
    seed_old_current_run(fake)
    fake.fail_rpc = "error"
    with pytest.raises(ml_loader.LoadError) as info:
        ml_loader.load(out)
    assert info.value.public_message == "RuntimeError at step set_current_run"
    assert current_runs(fake) == ["old-run"] and len(fake.rpc_calls) == 1


def test_failed_run_with_same_fingerprint_does_not_block_a_new_load(fake, out):
    seed_events(fake)
    fake.fail_rpc = "missing"
    with pytest.raises(ml_loader.LoadError):
        ml_loader.load(out)
    fake.fail_rpc = None
    report = ml_loader.load(out)                                   # failed run is not "completed"
    assert report["outcome"] == "loaded"
    assert sorted(r["status"] for r in fake.tables["pipeline_runs"]) == ["completed", "failed"]


def test_fetch_existing_event_ids_pages_through_everything(fake):
    fake.tables["events"] = [{"event_id": f"E{i:06d}"} for i in range(2500)]
    assert len(ml_loader.fetch_existing_event_ids()) == 2500
