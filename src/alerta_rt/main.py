"""Orchestrator: scheduler + jobs (discover → download → extract → match → deliver)."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from . import repository as repo
from .config import settings
from .extractor import extract
from .matcher import deliver_pending
from .sap_client import SapClient

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
                from .sap_client import NoteMeta
                meta = NoteMeta(note_number=note, title="", component=None, priority=None,
                                category=None, released_on=None, version=None, object_key=key)
                repo.upsert_note(meta, content, dest, sha)
                matched = repo.match_clients_for_note(note)
                log.info("note_ingested", note=note, matched=len(matched))
            except Exception as e:
                log.warning("download_failed", note=note, err=str(e))
                repo.mark_download_failed(note, str(e))

    await asyncio.gather(*(one(r) for r in pending))


async def job_deliver() -> None:
    sent = await deliver_pending()
    if sent:
        log.info("alerts_delivered", count=sent)


async def run() -> None:
    structlog.configure(processors=[structlog.processors.TimeStamper(fmt="iso"),
                                    structlog.processors.JSONRenderer()])
    client = SapClient()
    sched = AsyncIOScheduler()
    sched.add_job(job_discover, "interval", minutes=settings.discover_interval_min,
                  args=[client], next_run_time=datetime.now(timezone.utc))
    sched.add_job(job_download, "interval", seconds=60, args=[client])
    sched.add_job(job_deliver, "interval", seconds=30)
    sched.start()
    log.info("scheduler_started")
    try:
        await asyncio.Event().wait()
    finally:
        await client.aclose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
