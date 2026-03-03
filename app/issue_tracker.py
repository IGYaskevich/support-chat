from __future__ import annotations

from typing import Any

import httpx

from app.config import AppConfig


def _normalize_issue_id(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""

    for key in ("issue_id", "issueId", "id", "ticket_id", "ticketId"):
        value = payload.get(key)
        if value:
            return str(value)
    return ""


async def register_issue(issue_payload: dict[str, Any], config: AppConfig) -> dict[str, Any]:
    if not config.issue_tracker_url:
        return {
            "status": "unavailable",
            "reason": "ISSUE_TRACKER_URL is not configured",
            "issue_draft": issue_payload,
        }

    headers = {"Content-Type": "application/json"}
    if config.issue_tracker_token:
        headers["Authorization"] = f"Bearer {config.issue_tracker_token}"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                config.issue_tracker_url,
                headers=headers,
                json=issue_payload,
            )

        parsed: Any = None
        try:
            parsed = response.json()
        except Exception:
            parsed = None

        if response.status_code >= 400:
            return {
                "status": "error",
                "reason": f"Tracker returned status {response.status_code}",
                "issue_draft": issue_payload,
            }

        issue_id = _normalize_issue_id(parsed)
        if not issue_id:
            return {
                "status": "ok",
                "reason": "Tracker accepted payload but did not return issue_id",
                "issue_draft": issue_payload,
            }

        return {
            "status": "ok",
            "issue_id": issue_id,
        }
    except Exception as error:
        return {
            "status": "error",
            "reason": f"Tracker request failed: {error}",
            "issue_draft": issue_payload,
        }
