from __future__ import annotations

import json

import httpx
import structlog

from app.providers.log_storage.base import LogStorageBase

log = structlog.get_logger()


class ElasticsearchProvider(LogStorageBase):
    def __init__(self, url: str, api_key: str | None = None):
        self._url = url.rstrip("/")
        self._headers: dict = {"Content-Type": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"ApiKey {api_key}"

    async def search(self, index: str, body: dict, size: int = 10) -> dict:
        from app.config import settings
        body_with_size = {**body, "size": body.get("size", size)}
        async with httpx.AsyncClient(timeout=settings.es_logs_timeout, verify=False) as client:
            resolved_index = await self._resolve_index(client, index)
            resp = await client.post(
                f"{self._url}/{resolved_index}/_search",
                headers=self._headers,
                json=body_with_size,
            )
            resp.raise_for_status()
            data = resp.json()
        hits = data.get("hits", {})
        return {
            "index": resolved_index,
            "total": (
                hits.get("total", {}).get("value", 0)
                if isinstance(hits.get("total"), dict)
                else hits.get("total", 0)
            ),
            "hits": [h.get("_source", {}) for h in hits.get("hits", [])],
            "aggs": data.get("aggregations", {}),
        }

    async def _resolve_index(self, client: httpx.AsyncClient, index: str) -> str:
        index = index.strip().strip("/")
        if not index or "*" in index or "," in index:
            return index

        resp = await client.head(f"{self._url}/{index}", headers=self._headers)
        if resp.status_code < 400:
            return index

        wildcard_index = f"{index}-*"
        wildcard_resp = await client.get(
            f"{self._url}/_cat/indices/{wildcard_index}",
            headers=self._headers,
            params={"format": "json", "h": "index"},
        )
        if wildcard_resp.status_code < 400 and wildcard_resp.json():
            log.info("elasticsearch_index_resolved", index=index, resolved=wildcard_index)
            return wildcard_index

        return index

    async def bulk_index(self, index: str, docs: list[dict]) -> dict:
        lines = []
        for doc in docs:
            doc_id = doc.pop("_id", None)
            meta: dict = {"index": {"_index": index}}
            if doc_id:
                meta["index"]["_id"] = doc_id
            lines.append(meta)
            lines.append(doc)
        body = "\n".join(json.dumps(line) for line in lines) + "\n"
        async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
            resp = await client.post(
                f"{self._url}/_bulk",
                headers={**self._headers, "Content-Type": "application/x-ndjson"},
                content=body,
            )
            resp.raise_for_status()
            return resp.json()
