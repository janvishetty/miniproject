"""Write rows to the audit_log table (who did what, when).

Never put passwords, tokens, or personal data in `details`.
A failure to write the audit row must not break the request, so errors are
logged (type only) and swallowed.
"""
import logging
from typing import Any

from app import database

log = logging.getLogger("fsia.audit")


def write(actor_id: str | None, action: str, entity: str | None = None,
          entity_id: str | None = None, details: dict[str, Any] | None = None) -> None:
    try:
        database.get_admin_client().table("audit_log").insert({
            "actor_id": actor_id,
            "action": action,
            "entity": entity,
            "entity_id": entity_id,
            "details": details,
        }).execute()
    except Exception as exc:  # noqa: BLE001
        log.warning("audit write failed (%s) for action=%s", type(exc).__name__, action)
