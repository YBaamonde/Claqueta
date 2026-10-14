from __future__ import annotations

from typing import Any

import httpx

from .errors import NotConfigured, ServiceError
from .http import make_client, request_json

# Estados de MediaInfo en Jellyseerr/Overseerr
STATUS_TEXT = {None: "none", 1: "none", 2: "pending", 3: "processing", 4: "partial", 5: "available"}


class Jellyseerr:
    def __init__(self, url: str, api_key: str, public_url: str = "", client: httpx.Client | None = None):
        if not url or not api_key:
            raise NotConfigured("Jellyseerr no está configurado")
        self.url, self.key = url.rstrip("/"), api_key
        self.public_url = (public_url or url).rstrip("/")
        self.client = client or make_client(timeout=20)

    def _req(self, method: str, path: str, **kw: Any) -> Any:
        return request_json(self.client, method, f"{self.url}/api/v1{path}", headers={"X-Api-Key": self.key},
                            name="Jellyseerr", **kw)

    def check(self) -> dict:
        st = self._req("GET", "/status")
        me = self._req("GET", "/auth/me")
        return {"version": st.get("version"), "user": me.get("displayName") or me.get("email")}

    def status(self, tmdb_id: int) -> int | None:
        try:
            data = self._req("GET", f"/movie/{tmdb_id}")
        except ServiceError as e:
            if e.status == 404:
                return None
            raise
        return (data.get("mediaInfo") or {}).get("status")

    def request_movie(self, tmdb_id: int) -> dict:
        data = self._req("POST", "/request", json={"mediaType": "movie", "mediaId": tmdb_id})
        return {"id": data.get("id"), "status": (data.get("media") or {}).get("status", 2)}

    def media_url(self, tmdb_id: int) -> str:
        return f"{self.public_url}/movie/{tmdb_id}"
