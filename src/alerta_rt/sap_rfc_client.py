"""HTTPS client for the ABAP REST wrapper (ZCL_SNOTES_API) on each client's SAP system.

Replaces sap_client when SOURCE_MODE=rfc. Per-client credentials come from the
`clients` table (rfc_endpoint, rfc_auth_user, rfc_auth_pass, rfc_sap_client).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .config import settings
from .sap_client import NoteMeta


@dataclass
class RfcClientConfig:
    endpoint: str          # https://sap.cliente.com/sap/bc/rest/zsnotes
    user: str
    password: str
    sap_client: str | None = None


class SapRfcClient:
    """One instance per customer SAP system."""

    def __init__(self, cfg: RfcClientConfig) -> None:
        self._cfg = cfg
        headers = {"Accept": "application/json"}
        if cfg.sap_client:
            headers["sap-client"] = cfg.sap_client
        self._http = httpx.AsyncClient(
            timeout=settings.http_timeout_s,
            auth=(cfg.user, cfg.password),
            headers=headers,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    @retry(
        stop=stop_after_attempt(settings.retry_max_attempts),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((httpx.HTTPError,)),
    )
    async def discover(self, since_iso: str, components: list[str] | None = None) -> AsyncIterator[NoteMeta]:
        """GET {endpoint}/list?since=...&component=...&page=N  → paginated JSON."""
        page = 1
        while True:
            params = {"since": since_iso, "page": str(page), "page_size": "100"}
            if components:
                params["components"] = ",".join(components)
            r = await self._http.get(f"{self._cfg.endpoint}/list", params=params)
            r.raise_for_status()
            payload = r.json()
            for row in payload.get("notes", []):
                yield NoteMeta(
                    note_number=str(row["note_number"]),
                    title=row.get("title", ""),
                    component=row.get("component"),
                    priority=row.get("priority"),
                    category=row.get("category"),
                    released_on=row.get("released_on"),
                    version=row.get("version"),
                    object_key=None,  # RFC retorna conteúdo direto; sem .sar
                )
            if not payload.get("has_more"):
                break
            page += 1

    @retry(
        stop=stop_after_attempt(settings.retry_max_attempts),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((httpx.HTTPError,)),
    )
    async def fetch_note(self, note_number: str) -> dict:
        """GET {endpoint}/note/{n} → full payload: long_text, releases[], objects[], prereqs[]."""
        r = await self._http.get(f"{self._cfg.endpoint}/note/{note_number}")
        r.raise_for_status()
        return r.json()
