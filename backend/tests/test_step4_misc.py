"""Small Step 4 checks: httpx logging level, force-reload keeps status/analyst."""
import logging
import shutil
from pathlib import Path

import pytest

from app.services import ml_loader

FIX = Path(__file__).parent / "fixtures" / "ml_output"


def test_httpx_and_httpcore_log_at_warning(client):
    assert logging.getLogger("httpx").getEffectiveLevel() == logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() == logging.WARNING
    assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)


@pytest.fixture
def out(tmp_path):
    target = tmp_path / "out"
    shutil.copytree(FIX, target)
    return target


def _events(fake):
    fake.tables["events"] = [{"event_id": i} for i in
                             ["E900001", "E900002", "E900003", "T900001", "T900002"]]


def test_force_reload_keeps_status_and_analyst(fake, out):
    _events(fake)
    first = ml_loader.load(out)
    incident = fake.tables["incidents"][0]
    incident["status"], incident["analyst"] = "CONTAINED", "Ravi Kumar"
    forced = ml_loader.load(out, force=True)
    assert forced["outcome"] == "reloaded" and forced["run_id"] == first["run_id"]
    row = fake.tables["incidents"][0]
    assert (row["status"], row["analyst"]) == ("CONTAINED", "Ravi Kumar")
    assert row["title"] == "Synthetic Account Takeover" and row["raw"]["status"] == "OPEN"


def test_force_reload_still_refreshes_other_fields(fake, out):
    _events(fake)
    ml_loader.load(out)
    fake.tables["incidents"][0].update(status="RESOLVED", risk_score=1.0, title="stale")
    ml_loader.load(out, force=True)
    row = fake.tables["incidents"][0]
    assert row["status"] == "RESOLVED" and row["risk_score"] == 95.0 and row["title"].startswith("Synthetic")


def test_new_run_still_starts_from_the_file_status(fake, out):
    _events(fake)
    fake.tables["pipeline_runs"] = [{"id": "old", "status": "completed", "is_current": True,
                                     "source_fingerprint": "oldfingerp0"}]
    fake.tables["incidents"] = [{"pipeline_run_id": "old", "external_id": "INC-2026-9001",
                                 "status": "RESOLVED", "analyst": "Someone"}]
    ml_loader.load(out)
    new = [r for r in fake.tables["incidents"] if r["pipeline_run_id"] != "old"]
    assert len(new) == 1 and new[0]["status"] == "OPEN" and new[0]["analyst"] == "Unassigned"
