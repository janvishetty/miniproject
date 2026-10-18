"""AI Copilot. Any authenticated role.

POST /copilot: 10 questions/minute per user (429 + Retry-After), one call at a time (429 busy).
The question goes to the bridge on stdin only. The audit entry records the question LENGTH,
the answer source and the incident ids mentioned; never the question text."""
import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, StringConstraints
from typing import Annotated

from app import audit
from app.security import CurrentUser, get_current_user
from app.services import ai_bridge, copilot_guard, incident_store

router = APIRouter(prefix="/copilot", tags=["copilot"])
_INCIDENT_ID = re.compile(incident_store.EXTERNAL_ID_PATTERN)


class CopilotBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


def _answer(result: dict) -> dict:
    ids = [i for i in result.get("incidents", []) if isinstance(i, str) and _INCIDENT_ID.match(i)]
    return {"answer": result.get("answer"), "incidents": ids, "source": result.get("source"),
            "grounding": result.get("grounding"), "seconds": result.get("seconds")}


@router.post("")
def ask(body: CopilotBody, user: CurrentUser = Depends(get_current_user)):
    copilot_guard.check_rate(user.id)
    with copilot_guard.exclusive():
        data = incident_store.copilot_data(incident_store.current_run()["id"], include_resolved=True)
        try:
            result = ai_bridge.run_bridge("copilot", {"question": body.question, **data})
        except ai_bridge.BridgeError as exc:
            raise ai_bridge.to_http(exc) from None
    answer = _answer(result)
    audit.write(user.id, "copilot.ask", "copilot", None,
                {"question_length": len(body.question), "source": answer["source"],
                 "incidents": answer["incidents"]})
    return answer


@router.get("/welcome")
def welcome(user: CurrentUser = Depends(get_current_user)):
    data = incident_store.copilot_data(incident_store.current_run()["id"], include_resolved=False)
    try:
        result = ai_bridge.run_bridge("welcome", data)
    except ai_bridge.BridgeError as exc:
        raise ai_bridge.to_http(exc) from None
    return _answer(result)
