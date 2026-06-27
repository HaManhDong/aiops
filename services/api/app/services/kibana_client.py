from __future__ import annotations
import httpx
import structlog

log = structlog.get_logger()


class KibanaClient:
    def __init__(self, url: str, api_key: str | None = None):
        self._url = url.rstrip("/")
        self._headers = {"kbn-xsrf": "true", "Content-Type": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"ApiKey {api_key}"

    async def get_active_alerts(self, rule_type_ids: list[str] | None = None) -> list[dict]:
        """Fetch active alerts from Kibana Alerting API."""
        from app.config import settings
        params: dict = {"status": "active", "per_page": 50}
        if rule_type_ids:
            params["rule_type_ids"] = ",".join(rule_type_ids)
        try:
            async with httpx.AsyncClient(timeout=settings.kibana_timeout, verify=False) as client:
                resp = await client.get(
                    f"{self._url}/api/alerting/alerts",
                    headers=self._headers,
                    params=params,
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("data", data.get("alerts", []))
        except Exception as e:
            log.warning("kibana_alerts_failed", url=self._url, error=str(e))
            return []

    async def get_alert_count(self) -> dict:
        """Fetch total alert counts by severity."""
        alerts = await self.get_active_alerts()
        counts: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for a in alerts:
            sev = a.get("severity", a.get("params", {}).get("severity", "low")).lower()
            counts[sev] = counts.get(sev, 0) + 1
        return {"total": len(alerts), **counts}

    async def test_connection(self) -> bool:
        """Test Kibana connectivity."""
        from app.config import settings
        try:
            async with httpx.AsyncClient(timeout=settings.kibana_timeout, verify=False) as client:
                resp = await client.get(f"{self._url}/api/status", headers=self._headers)
                return resp.status_code < 400
        except Exception:
            return False
