"""Deliver pending alerts via outbound webhook per client."""
from __future__ import annotations

import httpx
import structlog

from . import repository as repo
from .config import settings

log = structlog.get_logger()


async def deliver_pending(limit: int = 50) -> int:
    sent = 0
    with repo.pool().connection() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT a.id, a.note_number, c.webhook_url, c.name, n.title, n.component,
                      n.priority, n.released_on
               FROM alerts a
               JOIN clients c ON c.id = a.client_id
               JOIN sap_notes n ON n.note_number = a.note_number
               WHERE a.status = 'pending' AND c.webhook_url IS NOT NULL
               ORDER BY a.matched_at LIMIT %s""",
            (limit,),
        )
        rows = cur.fetchall()

    async with httpx.AsyncClient(timeout=15.0) as http:
        for row in rows:
            payload = {
                "note_number": row["note_number"],
                "title": row["title"],
                "component": row["component"],
                "priority": row["priority"],
                "released_on": row["released_on"].isoformat() if row["released_on"] else None,
                "client": row["name"],
            }
            try:
                r = await http.post(row["webhook_url"], json=payload)
                r.raise_for_status()
                _mark(row["id"], "sent")
                sent += 1
            except Exception as e:
                log.warning("webhook_failed", alert_id=row["id"], err=str(e))
                _mark(row["id"], "failed")
    return sent


def _mark(alert_id: int, status: str) -> None:
    with repo.pool().connection() as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE alerts SET status = %s, attempts = attempts + 1,
                     delivered_at = CASE WHEN %s = 'sent' THEN now() ELSE delivered_at END
               WHERE id = %s""",
            (status, status, alert_id),
        )
