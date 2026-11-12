"""SAP OData client for Notes discovery + .sar download."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import AsyncIterator

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from .config import settings


@dataclass
class NoteMeta:
    note_number: str
    title: str
    component: str | None
    priority: str | None
    category: str | None
    released_on: str | None
    version: int | None
    object_key: str | None


class SapClient:
    def __init__(self) -> None:
        self._token: str | None = None
        self._token_exp: float = 0.0
        self._http = httpx.AsyncClient(timeout=settings.http_timeout_s)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _get_token(self) -> str:
        if self._token and time.time() < self._token_exp - 30:
            return self._token
        resp = await self._http.post(
            settings.sap_oauth_token_url,
            data={"grant_type": "client_credentials"},
            auth=(settings.sap_oauth_client_id, settings.sap_oauth_client_secret),
        )
        resp.raise_for_status()
        payload = resp.json()
        self._token = payload["access_token"]
        self._token_exp = time.time() + int(payload.get("expires_in", 3600))
        return self._token

    async def _authed(self, method: str, url: str, **kw) -> httpx.Response:
        token = await self._get_token()
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json", **kw.pop("headers", {})}
        return await self._http.request(method, url, headers=headers, **kw)

    @retry(
        stop=stop_after_attempt(settings.retry_max_attempts),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((httpx.HTTPError,)),
    )
    async def discover(self, since_iso: str, components: list[str] | None = None) -> AsyncIterator[NoteMeta]:
        """Yield notes released after `since_iso`, optionally filtered by component."""
        url = f"{settings.sap_odata_base}/NotesCollection"
        filters = [f"ReleasedOn gt datetime'{since_iso}'"]
        if components:
            comp_expr = " or ".join(f"ApplicationComponent eq '{c}'" for c in components)
            filters.append(f"({comp_expr})")
        params = {
            "$filter": " and ".join(filters),
            "$orderby": "ReleasedOn asc",
            "$top": "100",
        }
        while True:
            resp = await self._authed("GET", url, params=params)
            resp.raise_for_status()
            data = resp.json().get("d", {})
            for row in data.get("results", []):
                yield NoteMeta(
                    note_number=row["NoteNumber"],
                    title=row.get("Title", ""),
                    component=row.get("ApplicationComponent"),
                    priority=row.get("Priority"),
                    category=row.get("Category"),
                    released_on=row.get("ReleasedOn"),
                    version=row.get("Version"),
                    object_key=row.get("ObjectKey"),
                )
            next_link = data.get("__next")
            if not next_link:
                break
            url, params = next_link, None

    @retry(
        stop=stop_after_attempt(settings.retry_max_attempts),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        retry=retry_if_exception_type((httpx.HTTPError,)),
    )
    async def download_sar(self, object_key: str, dest_path: str) -> str:
        """Stream the .sar package to disk, return sha256."""
        import hashlib

        url = f"{settings.sap_download_base}/{object_key}"
        sha = hashlib.sha256()
        async with self._http.stream("GET", url, headers={"Authorization": f"Bearer {await self._get_token()}"}) as r:
            r.raise_for_status()
            with open(dest_path, "wb") as f:
                async for chunk in r.aiter_bytes(chunk_size=65536):
                    f.write(chunk)
                    sha.update(chunk)
        return sha.hexdigest()
