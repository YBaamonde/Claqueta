"""Conversión de modelos a JSON para el frontend. Aquí vive todo el «aspecto» de una ficha."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .. import settings_store as S
from ..engine.context import Context
from ..engine.explain import build_texts, match_percent
from ..engine.recommend import Scored, aged_label, attrs_of
from ..engine.taste import Taste
from ..models import Film
from ..services.jellyseerr import STATUS_TEXT

CARD_ATTRS = ["pace", "intensity", "tension", "humor", "warmth", "darkness", "emotional", "complexity"]


def poster_url(path: str | None, size: str = "w500") -> str | None:
    return f"/api/img/{size}{path}" if path and path.startswith("/") else None


def jf_play_url(f: Film) -> str | None:
    if not f.jellyfin_id:
        return None
    base = (S.get("jellyfin_public_url") or S.get("jellyfin_url") or "").rstrip("/")
    if not base:
        return None
    sid = S.get_raw("x_jf_server_id")
    return f"{base}/web/#/details?id={f.jellyfin_id}" + (f"&serverId={sid}" if sid else "")


def seerr_info(f: Film) -> dict[str, Any]:
    if not (S.get("jellyseerr_url") and S.get("jellyseerr_api_key")):
        return {"enabled": False}
    base = (S.get("jellyseerr_public_url") or S.get("jellyseerr_url") or "").rstrip("/")
    status = STATUS_TEXT.get(f.seerr_status, "none")
    return {
        "enabled": True,
        "status": status,
        "url": f"{base}/movie/{f.tmdb_id}" if f.tmdb_id else None,
        "can_request": (not f.jellyfin_id) and status in ("none",) and bool(f.tmdb_id or S.get("tmdb_api_key")),
    }


def availability(f: Film) -> dict[str, Any]:
    prov = f.providers or {}
    flat = [{"name": p.get("name"), "logo": poster_url(p.get("logo"), "w92")} for p in prov.get("flatrate", [])]
    return {
        "jellyfin": {"available": bool(f.jellyfin_id), "url": jf_play_url(f)},
        "seerr": seerr_info(f),
        "streaming": flat[:5],
        "streaming_link": prov.get("link"),
    }


def film_light(f: Film, status: str = "none", rating: float | None = None, liked: bool = False,
               watched_date: str | None = None) -> dict[str, Any]:
    a = attrs_of(f)
    return {
        "id": f.id, "tmdb_id": f.tmdb_id, "title": f.title, "original_title": f.original_title, "year": f.year,
        "runtime": f.runtime, "genres": f.genres[:3], "directors": f.directors[:2],
        "poster": poster_url(f.poster_path), "vote_average": f.vote_average,
        "status": status, "my_rating": rating, "liked": liked, "watched_date": watched_date,
        "availability": availability(f), "aged": aged_label(float(a.get("dated", .2))),
        "lang": f.original_language,
    }


def film_card(db: Session, f: Film, scored: Scored | None, ctx: Context, taste: Taste,
              seed_titles: dict[int, str] | None = None, pitch: str | None = None) -> dict[str, Any]:
    a = attrs_of(f)
    base = film_light(f, taste.status.get(f.id, "none"), taste.rating.get(f.id))
    base.update({
        "overview": f.overview, "tagline": f.tagline, "cast": f.cast[:5], "countries": f.countries[:2],
        "min_age": f.min_age, "vote_count": f.vote_count, "imdb_id": f.imdb_id,
        "backdrop": poster_url(f.backdrop_path, "w780"), "trailer": f.trailer_key,
        "letterboxd": f.letterboxd_uri or (f"https://letterboxd.com/tmdb/{f.tmdb_id}/" if f.tmdb_id else None),
        "attrs": {k: round(float(a.get(k, .5)), 2) for k in CARD_ATTRS},
        "tags": (f.attrs or {}).get("tags", []),
        "attrs_source": f.attrs_source,
    })
    if scored is not None:
        texts = build_texts(scored, ctx, taste, seed_titles or {})
        if pitch:
            texts["pitch"] = pitch
        base.update({
            "match": match_percent(scored.score), "score": round(scored.score, 3),
            "reasons": texts["reasons"],
            "warnings": [{"kind": "gate", "text": t} for t in scored.flags] + texts["warnings"],
            "aged_info": texts["aged"],
            "pitch": texts["pitch"], "suggested_reasons": texts["suggested_reasons"],
            "flags": scored.flags,
            "parts": {k: round(v, 2) for k, v in scored.parts.items() if k in
                      ("taste", "mood", "quality", "focus", "company", "variety", "availability")},
        })
    return base
