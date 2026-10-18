"""Generate one incident report through the bridge and store it, only if it is verified.

Rules (all enforced before anything is written):
* the incident's own pipeline_run_id must equal the current run's fingerprint, before the call
  and again on the result;
* only grounding.grounded == true is stored, whatever the source (llm, llm_corrected or the
  verified template fallback, which keeps source="template"); grounded=false fails the job
  with code "unverified" and nothing is stored;
* same column mapping as ml_loader.parse_reports.
"""
from app import database
from app.report_jobs import ReportFailure
from app.services import ai_bridge, incident_store

_STORABLE_SOURCES = ("llm", "llm_corrected", "template")   # template = the verified fallback


def generate(external_id: str) -> dict:
    try:
        run = incident_store.current_run()
        row = incident_store.get_incident_row(run["id"], external_id, "id,external_id,raw")
    except Exception:  # noqa: BLE001  (409 / 404 / database error: the run is gone or changed)
        raise ReportFailure("stale_run") from None
    incident = row.get("raw")
    if not isinstance(incident, dict) or incident.get("pipeline_run_id") != run.get("source_fingerprint"):
        raise ReportFailure("stale_run")

    try:
        result = ai_bridge.run_bridge("summarize", {"incident": incident})
    except ai_bridge.BridgeError as exc:
        raise ReportFailure({"ai_unavailable": "ai_unavailable", "timeout": "timeout"}
                            .get(exc.code, "error")) from None

    try:
        now = incident_store.current_run()
    except Exception:  # noqa: BLE001
        raise ReportFailure("stale_run") from None
    if now["id"] != run["id"] or result.get("pipeline_run_id") != now.get("source_fingerprint"):
        raise ReportFailure("stale_run")

    grounding = result.get("grounding")
    unverified = grounding.get("unverified") if isinstance(grounding, dict) else None
    if (not isinstance(grounding, dict) or grounding.get("grounded") is not True
            or result.get("source") not in _STORABLE_SOURCES
            or not isinstance(unverified or [], list)):
        raise ReportFailure("unverified")

    database.get_admin_client().table("reports").upsert(
        {"incident_id": row["id"], "summary": result.get("summary"),
         "five_ws": result.get("five_ws"), "mitre": result.get("mitre") or [],
         "containment_actions": result.get("containment_actions") or [],
         "investigation_steps": result.get("investigation_steps") or [],
         "source": result["source"], "grounded": True, "unverified": unverified or [],
         "raw": result}, on_conflict="incident_id").execute()
    return {"incident_id": external_id, "source": result["source"], "grounded": True}
