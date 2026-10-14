from __future__ import annotations

from typing import Any

import httpx

from .errors import NotConfigured
from .http import make_client, request_json


class Radarr:
    def __init__(self, url: str, api_key: str, client: httpx.Client | None = None):
        if not url or not api_key:
            raise NotConfigured("Radarr no está configurado")
        self.url, self.key = url.rstrip("/"), api_key
        self.client = client or make_client(timeout=15)

    def _get(self, path: str, **params: Any) -> Any:
        return request_json(self.client, "GET", f"{self.url}/api/v3{path}", params=params or None,
                            headers={"X-Api-Key": self.key}, name="Radarr")

    def check(self) -> dict:
        st = self._get("/system/status")
        return {"version": st.get("version"), "name": st.get("instanceName")}

    def progress(self) -> dict[int, dict]:
        """tmdb_id → {pct, eta, state} de lo que se está descargando ahora mismo."""
        res = self._get("/queue", pageSize=200, includeMovie="true")
        out: dict[int, dict] = {}
        for rec in res.get("records", []):
            mv = rec.get("movie") or {}
            tid = mv.get("tmdbId")
            size, left = rec.get("size") or 0, rec.get("sizeleft") or 0
            if tid:
                out[int(tid)] = {
                    "pct": round(100 * (1 - left / size)) if size else 0,
                    "eta": rec.get("timeleft"),
                    "state": rec.get("trackedDownloadState") or rec.get("status"),
                }
        return out
