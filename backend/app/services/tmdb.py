from __future__ import annotations

import difflib
from typing import Any

import httpx

from ..genres import genres_from_ids
from ..util import norm_title
from .errors import NotConfigured
from .http import Limiter, make_client, request_json

BASE = "https://api.themoviedb.org/3"
_limiter = Limiter(0.03)  # ~30 req/s: muy por debajo del límite de TMDB

ES_CERT_AGE = {"A": 0, "APTA": 0, "TP": 0, "0": 0, "7": 7, "12": 12, "16": 16, "18": 18, "X": 18}
US_CERT_AGE = {"G": 0, "PG": 8, "PG-13": 13, "R": 17, "NC-17": 18, "NR": None}


def _year(date: str | None) -> int | None:
    try:
        return int(date[:4]) if date else None
    except ValueError:
        return None


def parse_list_item(it: dict) -> dict[str, Any]:
    """Elemento de /search, /discover, /recommendations… (ficha parcial, sin duración)."""
    return {
        "tmdb_id": it["id"],
        "title": it.get("title") or it.get("original_title") or "",
        "original_title": it.get("original_title"),
        "year": _year(it.get("release_date")),
        "release_date": it.get("release_date") or None,
        "overview": it.get("overview") or None,
        "genres": genres_from_ids(it.get("genre_ids")),
        "original_language": it.get("original_language"),
        "poster_path": it.get("poster_path"),
        "backdrop_path": it.get("backdrop_path"),
        "vote_average": it.get("vote_average"),
        "vote_count": it.get("vote_count") or 0,
        "popularity": it.get("popularity") or 0.0,
        "adult": bool(it.get("adult")),
        "partial": True,
    }


def parse_details(raw: dict, region: str = "ES") -> dict[str, Any]:
    credits = raw.get("credits") or {}
    crew = credits.get("crew") or []
    cast = sorted(credits.get("cast") or [], key=lambda c: c.get("order", 99))
    directors = [c["name"] for c in crew if c.get("job") == "Director"][:3]
    kw = [k["name"] for k in (raw.get("keywords") or {}).get("keywords", [])][:14]

    min_age = None
    for res in (raw.get("release_dates") or {}).get("results", []):
        if res.get("iso_3166_1") == region:
            certs = [d.get("certification") for d in res.get("release_dates", []) if d.get("certification")]
            if certs and certs[0] in ES_CERT_AGE:
                min_age = ES_CERT_AGE[certs[0]]
    if min_age is None:
        for res in (raw.get("release_dates") or {}).get("results", []):
            if res.get("iso_3166_1") == "US":
                certs = [d.get("certification") for d in res.get("release_dates", []) if d.get("certification")]
                if certs:
                    min_age = US_CERT_AGE.get(certs[0])

    trailer = None
    vids = [v for v in (raw.get("videos") or {}).get("results", [])
            if v.get("site") == "YouTube" and v.get("type") == "Trailer"]
    if vids:
        vids.sort(key=lambda v: (v.get("iso_639_1") != "es", not v.get("official", False)))
        trailer = vids[0].get("key")

    prov = ((raw.get("watch/providers") or {}).get("results") or {}).get(region) or {}
    providers = {
        kind: [{"name": p.get("provider_name"), "logo": p.get("logo_path")} for p in prov.get(kind, [])]
        for kind in ("flatrate", "rent", "buy")
    }
    providers["link"] = prov.get("link")

    genre_ids = [g["id"] for g in raw.get("genres", [])]
    genres = genres_from_ids(genre_ids) or [g["name"] for g in raw.get("genres", [])]
    return {
        "tmdb_id": raw["id"],
        "imdb_id": raw.get("imdb_id") or (raw.get("external_ids") or {}).get("imdb_id"),
        "title": raw.get("title") or raw.get("original_title") or "",
        "original_title": raw.get("original_title"),
        "year": _year(raw.get("release_date")),
        "release_date": raw.get("release_date") or None,
        "runtime": raw.get("runtime") or None,
        "overview": raw.get("overview") or None,
        "tagline": raw.get("tagline") or None,
        "genres": genres,
        "directors": directors,
        "cast": [c["name"] for c in cast[:8]],
        "countries": [c["iso_3166_1"] for c in raw.get("production_countries", [])],
        "original_language": raw.get("original_language"),
        "keywords": kw,
        "min_age": min_age,
        "adult": bool(raw.get("adult")),
        "poster_path": raw.get("poster_path"),
        "backdrop_path": raw.get("backdrop_path"),
        "trailer_key": trailer,
        "vote_average": raw.get("vote_average"),
        "vote_count": raw.get("vote_count") or 0,
        "popularity": raw.get("popularity") or 0.0,
        "providers": providers,
        "partial": False,
    }


class TMDB:
    def __init__(self, api_key: str, language: str = "es-ES", region: str = "ES",
                 client: httpx.Client | None = None, base: str = BASE):
        if not api_key:
            raise NotConfigured("Falta la clave de API de TMDB")
        self.key, self.language, self.region, self.base = api_key.strip(), language, region, base
        self.client = client or make_client()
        self._bearer = self.key.startswith("eyJ")

    def get(self, path: str, **params: Any) -> Any:
        params = {k: v for k, v in params.items() if v is not None}
        params.setdefault("language", self.language)
        headers = {}
        if self._bearer:
            headers["Authorization"] = f"Bearer {self.key}"
        else:
            params["api_key"] = self.key
        _limiter.wait()
        return request_json(self.client, "GET", f"{self.base}{path}", params=params, headers=headers, name="TMDB")

    # --- lecturas ---------------------------------------------------------
    def check(self) -> dict:
        return self.get("/configuration")

    def details(self, tmdb_id: int) -> dict[str, Any]:
        raw = self.get(f"/movie/{tmdb_id}",
                       append_to_response="credits,keywords,release_dates,watch/providers,videos,external_ids",
                       include_video_language="es,en,null")
        return parse_details(raw, self.region)

    def search(self, title: str, year: int | None = None) -> list[dict]:
        res = self.get("/search/movie", query=title, year=year, include_adult="false")
        return [parse_list_item(r) for r in res.get("results", [])]

    def recommendations(self, tmdb_id: int, pages: int = 1) -> list[dict]:
        out: list[dict] = []
        for p in range(1, pages + 1):
            out += [parse_list_item(r) for r in self.get(f"/movie/{tmdb_id}/recommendations", page=p).get("results", [])]
        return out

    def similar(self, tmdb_id: int) -> list[dict]:
        return [parse_list_item(r) for r in self.get(f"/movie/{tmdb_id}/similar").get("results", [])]

    def top_rated(self, page: int = 1) -> list[dict]:
        return [parse_list_item(r) for r in self.get("/movie/top_rated", page=page, region=self.region).get("results", [])]

    def popular(self, page: int = 1) -> list[dict]:
        return [parse_list_item(r) for r in self.get("/movie/popular", page=page, region=self.region).get("results", [])]

    def discover(self, **params: Any) -> list[dict]:
        return [parse_list_item(r) for r in self.get("/discover/movie", include_adult="false", **params).get("results", [])]


def best_match(results: list[dict], titles: list[str], year: int | None) -> dict | None:
    """Elige el resultado de búsqueda que mejor corresponde a (título, año)."""
    wanted = [norm_title(t) for t in titles if t]
    best, best_score = None, 0.0
    for r in results:
        cand = [norm_title(r.get("title")), norm_title(r.get("original_title"))]
        score = 0.0
        if any(c and c in wanted for c in cand):
            score += 3.0
        else:
            score += max((difflib.SequenceMatcher(None, w, c).ratio() for w in wanted for c in cand if c), default=0) * 2
        ry = r.get("year")
        if year and ry:
            d = abs(ry - year)
            score += 2.0 if d == 0 else 1.0 if d == 1 else -3.0 if d > 2 else 0.0
        score += min(.4, (r.get("popularity") or 0) / 500)
        if score > best_score:
            best, best_score = r, score
    return best if best_score >= 3.4 else None
