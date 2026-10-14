from __future__ import annotations

from typing import Any, Iterator

import httpx

from ..genres import canon_genres
from .errors import NotConfigured
from .http import make_client, request_json


def _item(it: dict) -> dict[str, Any]:
    prov = {k.lower(): v for k, v in (it.get("ProviderIds") or {}).items()}
    ticks = it.get("RunTimeTicks") or 0
    ud = it.get("UserData") or {}
    resume = None
    pos = ud.get("PlaybackPositionTicks") or 0
    if ticks and pos:
        resume = round(100 * pos / ticks)
    return {
        "jf_id": it["Id"],
        "title": it.get("Name") or "",
        "original_title": it.get("OriginalTitle"),
        "year": it.get("ProductionYear"),
        "runtime": round(ticks / 600_000_000) if ticks else None,
        "tmdb_id": int(prov["tmdb"]) if str(prov.get("tmdb", "")).isdigit() else None,
        "imdb_id": prov.get("imdb"),
        "genres": canon_genres(it.get("Genres")),
        "overview": it.get("Overview"),
        "played": bool(ud.get("Played")),
        "last_played": ud.get("LastPlayedDate"),
        "play_count": ud.get("PlayCount") or 0,
        "resume_pct": resume,
        "added": it.get("DateCreated"),
    }


class Jellyfin:
    def __init__(self, url: str, api_key: str, user_id: str = "", public_url: str = "",
                 client: httpx.Client | None = None):
        if not url or not api_key:
            raise NotConfigured("Jellyfin no está configurado")
        self.url = url.rstrip("/")
        self.public_url = (public_url or url).rstrip("/")
        self.key = api_key
        self.user_id = user_id
        self.client = client or make_client(timeout=25)
        self._server_id: str | None = None

    def _get(self, path: str, **params: Any) -> Any:
        return request_json(self.client, "GET", f"{self.url}{path}", params=params or None,
                            headers={"Authorization": f'MediaBrowser Token="{self.key}"', "X-Emby-Token": self.key},
                            name="Jellyfin")

    def check(self) -> dict:
        info = self._get("/System/Info")
        return {"name": info.get("ServerName"), "version": info.get("Version"), "id": info.get("Id")}

    def server_id(self) -> str | None:
        if self._server_id is None:
            try:
                self._server_id = self._get("/System/Info/Public").get("Id")
            except Exception:  # noqa: BLE001
                self._server_id = ""
        return self._server_id or None

    def resolve_user(self) -> str:
        if self.user_id:
            return self.user_id
        users = self._get("/Users")
        admin = next((u for u in users if (u.get("Policy") or {}).get("IsAdministrator")), users[0] if users else None)
        if not admin:
            raise NotConfigured("Jellyfin no tiene usuarios")
        self.user_id = admin["Id"]
        return self.user_id

    def _paged(self, path: str, page: int = 300, **params: Any) -> Iterator[dict]:
        start = 0
        while True:
            res = self._get(path, StartIndex=start, Limit=page, **params)
            items = res.get("Items", [])
            yield from items
            start += len(items)
            if not items or start >= res.get("TotalRecordCount", 0):
                break

    FIELDS = "ProviderIds,ProductionYear,RunTimeTicks,Genres,Overview,DateCreated,OriginalTitle"

    def library(self) -> list[dict]:
        return [_item(i) for i in self._paged("/Items", IncludeItemTypes="Movie", Recursive="true", Fields=self.FIELDS)]

    def played(self) -> list[dict]:
        uid = self.resolve_user()
        return [_item(i) for i in self._paged(f"/Users/{uid}/Items", IncludeItemTypes="Movie", Recursive="true",
                                              Filters="IsPlayed", Fields=self.FIELDS,
                                              SortBy="DatePlayed", SortOrder="Descending")]

    def resumable(self) -> list[dict]:
        uid = self.resolve_user()
        res = self._get(f"/Users/{uid}/Items", IncludeItemTypes="Movie", Recursive="true", Filters="IsResumable",
                        Fields=self.FIELDS, SortBy="DatePlayed", SortOrder="Descending", Limit=12)
        return [_item(i) for i in res.get("Items", [])]

    def play_url(self, jf_id: str) -> str:
        sid = self.server_id()
        suffix = f"&serverId={sid}" if sid else ""
        return f"{self.public_url}/web/#/details?id={jf_id}{suffix}"
