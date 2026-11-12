"""Postgres repository — idempotent upserts for notes + alert matching."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import settings
from .extractor import NoteContent
from .sap_client import NoteMeta

_pool: ConnectionPool | None = None


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(settings.database_url, min_size=1, max_size=8, kwargs={"row_factory": dict_row})
    return _pool


def get_last_run(job_name: str) -> datetime:
    with pool().connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT last_run_at FROM sync_state WHERE job_name = %s", (job_name,))
        row = cur.fetchone()
        return row["last_run_at"] if row else datetime(2000, 1, 1, tzinfo=timezone.utc)


def set_last_run(job_name: str, ts: datetime) -> None:
    with pool().connection() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO sync_state (job_name, last_run_at) VALUES (%s, %s)
               ON CONFLICT (job_name) DO UPDATE SET last_run_at = EXCLUDED.last_run_at""",
            (job_name, ts),
        )


def enqueue_download(meta: NoteMeta) -> None:
    with pool().connection() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO download_queue (note_number, object_key) VALUES (%s, %s)
               ON CONFLICT (note_number) DO NOTHING""",
            (meta.note_number, meta.object_key),
        )


def next_to_download(limit: int) -> list[dict]:
    with pool().connection() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT note_number, object_key FROM download_queue
               WHERE attempts < 5 ORDER BY enqueued_at LIMIT %s""",
            (limit,),
        )
        return cur.fetchall()


def mark_download_failed(note_number: str, err: str) -> None:
    with pool().connection() as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE download_queue SET attempts = attempts + 1, last_error = %s
               WHERE note_number = %s""",
            (err[:2000], note_number),
        )


def upsert_note(meta: NoteMeta, content: NoteContent, sar_path: str, sar_sha256: str) -> None:
    with pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO sap_notes (note_number, title, component, priority, category,
                                          released_on, version, long_text, raw_xml, sar_path, sar_sha256)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (note_number) DO UPDATE SET
                     title = EXCLUDED.title,
                     component = EXCLUDED.component,
                     priority = EXCLUDED.priority,
                     category = EXCLUDED.category,
                     released_on = EXCLUDED.released_on,
                     version = EXCLUDED.version,
                     long_text = EXCLUDED.long_text,
                     raw_xml = EXCLUDED.raw_xml,
                     sar_path = EXCLUDED.sar_path,
                     sar_sha256 = EXCLUDED.sar_sha256,
                     updated_at = now()""",
                (meta.note_number, meta.title, meta.component, meta.priority, meta.category,
                 meta.released_on, meta.version, content.long_text, content.raw_xml, sar_path, sar_sha256),
            )
            cur.execute("DELETE FROM sap_note_releases WHERE note_number = %s", (meta.note_number,))
            cur.execute("DELETE FROM sap_note_objects  WHERE note_number = %s", (meta.note_number,))
            cur.execute("DELETE FROM sap_note_prereqs  WHERE note_number = %s", (meta.note_number,))
            if content.releases:
                cur.executemany(
                    """INSERT INTO sap_note_releases (note_number, software_component, release, sp_from, sp_to)
                       VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                    [(meta.note_number, r["software_component"], r["release"], r.get("sp_from"), r.get("sp_to"))
                     for r in content.releases],
                )
            if content.objects:
                cur.executemany(
                    """INSERT INTO sap_note_objects (note_number, obj_type, obj_name, version_from, version_to)
                       VALUES (%s,%s,%s,%s,%s)""",
                    [(meta.note_number, o["obj_type"], o["obj_name"], o.get("version_from"), o.get("version_to"))
                     for o in content.objects],
                )
            if content.prereqs:
                cur.executemany(
                    """INSERT INTO sap_note_prereqs (note_number, prereq_note) VALUES (%s,%s)
                       ON CONFLICT DO NOTHING""",
                    [(meta.note_number, p) for p in content.prereqs],
                )
            cur.execute("DELETE FROM download_queue WHERE note_number = %s", (meta.note_number,))


def match_clients_for_note(note_number: str) -> list[int]:
    """Return client_ids whose (release + component) matches this note."""
    sql = """
        INSERT INTO alerts (client_id, note_number)
        SELECT c.id, %s
        FROM clients c
        WHERE c.active
          AND EXISTS (
            SELECT 1 FROM sap_note_releases r
            WHERE r.note_number = %s
              AND r.software_component = ANY(c.components)
              AND r.release = c.sap_release
          )
        ON CONFLICT (client_id, note_number) DO NOTHING
        RETURNING client_id
    """
    with pool().connection() as conn, conn.cursor() as cur:
        cur.execute(sql, (note_number, note_number))
        return [r["client_id"] for r in cur.fetchall()]
