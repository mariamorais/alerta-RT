"""Orchestrator: scheduler + jobs (discover → download → extract → match → deliver)."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from . import repository as repo
from .classifier import classify
from .config import settings
from .extractor import NoteContent, extract
from .matcher import deliver_pending
from .sap_client import NoteMeta, SapClient
from .sap_rfc_client import RfcClientConfig, SapRfcClient

log = structlog.get_logger()


async def job_discover(client: SapClient) -> None:
    since = repo.get_last_run("discover")
    log.info("discover_start", since=since.isoformat())
    count = 0
    async for meta in client.discover(since_iso=since.strftime("%Y-%m-%dT%H:%M:%S")):
        repo.enqueue_download(meta)
        count += 1
    repo.set_last_run("discover", datetime.now(timezone.utc))
    log.info("discover_done", enqueued=count)


async def job_download(client: SapClient) -> None:
    pending = repo.next_to_download(limit=settings.download_concurrency * 4)
    if not pending:
        return
    sem = asyncio.Semaphore(settings.download_concurrency)

    async def one(row: dict) -> None:
        async with sem:
            note = row["note_number"]
            key = row["object_key"]
            if not key:
                repo.mark_download_failed(note, "missing object_key")
                return
            Path(settings.sar_dir).mkdir(parents=True, exist_ok=True)
            dest = os.path.join(settings.sar_dir, f"{note}.sar")
            try:
                sha = await client.download_sar(key, dest)
                content = extract(dest)
                meta = NoteMeta(note_number=note, title="", component=None, priority=None,
                                category=None, released_on=None, version=None, object_key=key)
                cls = classify(meta.title, content.long_text, meta.component, meta.category, meta.priority)
                repo.upsert_note(meta, content, dest, sha, source="download",
                                 is_tax_reform=cls.is_tax_reform,
                                 classification_score=cls.score,
                                 matched_keywords=cls.matched)
                matched = repo.match_clients_for_note(note)
                log.info("note_ingested", note=note, tax_reform=cls.is_tax_reform,
                         score=cls.score, matched=len(matched))
            except Exception as e:
                log.warning("download_failed", note=note, err=str(e))
                repo.mark_download_failed(note, str(e))

    await asyncio.gather(*(one(r) for r in pending))


async def job_discover_rfc() -> None:
    """Modo RFC: itera sobre cada cliente com rfc_endpoint cadastrado."""
    since = repo.get_last_run("discover")
    since_iso = since.strftime("%Y-%m-%dT%H:%M:%S")
    clients = repo.list_rfc_clients()
    total = 0
    for crow in clients:
        cfg = RfcClientConfig(endpoint=crow["rfc_endpoint"], user=crow["rfc_auth_user"],
                              password=crow["rfc_auth_pass"], sap_client=crow["rfc_sap_client"])
        rc = SapRfcClient(cfg)
        try:
            async for meta in rc.discover(since_iso=since_iso, components=crow["components"] or None):
                payload = await rc.fetch_note(meta.note_number)
                content = NoteContent(
                    long_text=payload.get("long_text", "") or "",
                    raw_xml="",
                    releases=payload.get("releases", []),
                    objects=payload.get("objects", []),
                    prereqs=payload.get("prereqs", []),
                )
                cls = classify(meta.title, content.long_text, meta.component, meta.category, meta.priority)
                repo.upsert_note(meta, content, None, None, source="rfc",
                                 is_tax_reform=cls.is_tax_reform,
                                 classification_score=cls.score,
                                 matched_keywords=cls.matched)
                matched = repo.match_clients_for_note(meta.note_number, client_id=crow["id"])
                total += 1
                log.info("rfc_note_ingested", client=crow["name"], note=meta.note_number,
                         tax_reform=cls.is_tax_reform, matched=len(matched))
        except Exception as e:
            log.warning("rfc_discover_failed", client=crow["name"], err=str(e))
        finally:
            await rc.aclose()
    repo.set_last_run("discover", datetime.now(timezone.utc))
    log.info("rfc_discover_done", clients=len(clients), notes=total)


async def job_deliver() -> None:
    sent = await deliver_pending()
    if sent:
        log.info("alerts_delivered", count=sent)


async def run() -> None:
    structlog.configure(processors=[structlog.processors.TimeStamper(fmt="iso"),
                                    structlog.processors.JSONRenderer()])
    sched = AsyncIOScheduler()
    client: SapClient | None = None
    if settings.source_mode == "rfc":
        sched.add_job(job_discover_rfc, "interval", minutes=settings.discover_interval_min,
                      next_run_time=datetime.now(timezone.utc))
    else:
        client = SapClient()
        sched.add_job(job_discover, "interval", minutes=settings.discover_interval_min,
                      args=[client], next_run_time=datetime.now(timezone.utc))
        sched.add_job(job_download, "interval", seconds=60, args=[client])
    sched.add_job(job_deliver, "interval", seconds=30)
    sched.start()
    log.info("scheduler_started", mode=settings.source_mode)
    try:
        await asyncio.Event().wait()
    finally:
        if client is not None:
            await client.aclose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
