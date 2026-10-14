"""Películas: búsqueda, ficha, estado del usuario, biblioteca, onboarding, rutas de cine y Jellyseerr."""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .. import settings_store as S
from ..data.paths import PATHS
from ..db import get_db
from ..engine import taste as taste_mod
from ..engine.recommend import aged_label, attrs_of
from ..engine.taste import build_taste
from ..models import Film, UserFilm
from ..services import catalog
from ..services.errors import NotConfigured, ServiceError
from ..util import norm_title, utcnow
from .serializers import film_card, film_light

log = logging.getLogger("claqueta.api.films")
router = APIRouter(prefix="/api")
PROFILE = 1


def _row(db: Session, film_id: int) -> UserFilm | None:
    return db.query(UserFilm).filter_by(profile_id=PROFILE, film_id=film_id).one_or_none()


def _light(db: Session, f: Film) -> dict[str, Any]:
    r = _row(db, f.id)
    return film_light(f, r.status if r else "none", r.rating if r else None, bool(r and r.liked),
                      r.watched_date.isoformat() if r and r.watched_date else None)


def _need_film(db: Session, film_id: int) -> Film:
    f = db.get(Film, film_id)
    if f is None:
        raise HTTPException(404, "Película no encontrada")
    return f


# ---------------------------------------------------------------------------
# Búsqueda y alta
# ---------------------------------------------------------------------------

@router.get("/search")
def search(q: str = Query(min_length=2, max_length=120), db: Session = Depends(get_db)):
    n = norm_title(q)
    like = f"%{n}%"
    local = (db.query(Film).filter(or_(Film.norm_title.like(like), Film.norm_alt.like(like)))
             .order_by(Film.vote_count.desc()).limit(14).all())
    out = [{"kind": "local", **_light(db, f)} for f in local]
    seen_tmdb = {f.tmdb_id for f in local if f.tmdb_id}
    tmdb_error = None
    tmdb = catalog.tmdb_client()
    if tmdb is not None:
        try:
            for p in tmdb.search(q)[:10]:
                if p["tmdb_id"] in seen_tmdb:
                    continue
                out.append({"kind": "tmdb", "id": None, "tmdb_id": p["tmdb_id"], "title": p["title"],
                            "original_title": p["original_title"], "year": p["year"], "runtime": None,
                            "genres": p["genres"][:3], "poster": f"/api/img/w342{p['poster_path']}" if p["poster_path"] else None,
                            "vote_average": p["vote_average"], "status": "none"})
        except ServiceError as e:
            tmdb_error = e.message
    return {"results": out, "tmdb": tmdb is not None, "tmdb_error": tmdb_error}


class FromTmdbIn(BaseModel):
    tmdb_id: int


@router.post("/films/from-tmdb")
def add_from_tmdb(body: FromTmdbIn, db: Session = Depends(get_db)):
    tmdb = catalog.tmdb_client()
    if tmdb is None:
        raise NotConfigured("Configura TMDB en Ajustes para añadir películas nuevas")
    f = catalog.upsert(db, tmdb.details(body.tmdb_id), "tmdb")
    db.commit()
    return _light(db, f)


@router.get("/films/{film_id}")
def get_film(film_id: int, db: Session = Depends(get_db)):
    f = _need_film(db, film_id)
    taste = build_taste(db, PROFILE)
    card = film_card(db, f, None, None, taste)  # type: ignore[arg-type]
    a = attrs_of(f)
    card["aged_info"] = {"risk": float(a.get("dated", .2)), "label": aged_label(float(a.get("dated", .2)))}
    card["pitch"] = (a.get("notes") or (f.overview or "").split(". ")[0])[:240]
    return card


class StateIn(BaseModel):
    status: Literal["watched", "watchlist", "parked", "watching", "never", "none"] | None = None
    rating: float | None = Field(default=None, ge=0.5, le=5)
    clear_rating: bool = False
    liked: bool | None = None
    watched_date: date | None = None
    rewatch: bool | None = None


@router.post("/films/{film_id}/state")
def set_state(film_id: int, body: StateIn, db: Session = Depends(get_db)):
    f = _need_film(db, film_id)
    row = _row(db, film_id)
    if row is None:
        row = UserFilm(profile_id=PROFILE, film_id=film_id, status="none", source="app")
        db.add(row)
    if body.status is not None:
        row.status = body.status
        if body.status == "watched" and row.watched_date is None and body.watched_date is None:
            row.watched_date = date.today()
        if body.status != "watching":
            row.started_at = None
        if body.status == "none":
            row.snoozed_until = None
    if body.rating is not None:
        row.rating = round(body.rating * 2) / 2
        if row.status in ("none", "watchlist", "parked", "watching"):
            row.status = "watched"
            row.watched_date = row.watched_date or date.today()
    if body.clear_rating:
        row.rating = None
    if body.liked is not None:
        row.liked = body.liked
    if body.watched_date is not None:
        row.watched_date = body.watched_date
    if body.rewatch is not None:
        row.rewatch = body.rewatch
    row.updated_at = utcnow()
    db.flush()
    taste_mod.invalidate(PROFILE)
    db.commit()
    return _light(db, f)


# ---------------------------------------------------------------------------
# Biblioteca
# ---------------------------------------------------------------------------

TABS = {
    "parked": ("parked",), "watchlist": ("watchlist",), "watched": ("watched",), "watching": ("watching",),
    "never": ("never",),
}


@router.get("/library")
def library(tab: str = "parked", q: str = "", sort: str = "recent", limit: int = Query(60, le=300),
            offset: int = 0, db: Session = Depends(get_db)):
    query = db.query(Film, UserFilm).outerjoin(
        UserFilm, (UserFilm.film_id == Film.id) & (UserFilm.profile_id == PROFILE))
    if tab == "jellyfin":
        query = query.filter(Film.jellyfin_id.isnot(None))
    elif tab == "requested":
        query = query.filter(Film.seerr_status.in_((2, 3, 4)))
    elif tab == "snoozed":
        query = query.filter(UserFilm.snoozed_until > utcnow())
    elif tab in TABS:
        query = query.filter(UserFilm.status.in_(TABS[tab]))
    else:
        raise HTTPException(400, "Pestaña desconocida")
    if q.strip():
        like = f"%{norm_title(q)}%"
        query = query.filter(or_(Film.norm_title.like(like), Film.norm_alt.like(like)))
    total = query.count()
    if sort == "rating":
        query = query.order_by(UserFilm.rating.desc().nullslast(), Film.vote_count.desc())
    elif sort == "title":
        query = query.order_by(Film.norm_title)
    elif sort == "year":
        query = query.order_by(Film.year.desc().nullslast())
    elif sort == "runtime":
        query = query.order_by(Film.runtime.asc().nullslast())
    else:
        query = query.order_by(func.coalesce(UserFilm.watched_date, func.date(UserFilm.updated_at)).desc().nullslast(),
                               Film.vote_count.desc())
    rows = query.offset(offset).limit(limit).all()
    items = [film_light(f, u.status if u else "none", u.rating if u else None, bool(u and u.liked),
                        u.watched_date.isoformat() if u and u.watched_date else None) for f, u in rows]
    counts = {
        "parked": db.query(UserFilm).filter_by(profile_id=PROFILE, status="parked").count(),
        "watchlist": db.query(UserFilm).filter_by(profile_id=PROFILE, status="watchlist").count(),
        "watched": db.query(UserFilm).filter_by(profile_id=PROFILE, status="watched").count(),
        "watching": db.query(UserFilm).filter_by(profile_id=PROFILE, status="watching").count(),
        "never": db.query(UserFilm).filter_by(profile_id=PROFILE, status="never").count(),
        "jellyfin": db.query(Film).filter(Film.jellyfin_id.isnot(None)).count(),
        "requested": db.query(Film).filter(Film.seerr_status.in_((2, 3, 4))).count(),
    }
    return {"items": items, "total": total, "counts": counts}


# ---------------------------------------------------------------------------
# Onboarding: calibrar el gusto sin Letterboxd
# ---------------------------------------------------------------------------

@router.get("/onboarding")
def onboarding(n: int = Query(30, ge=6, le=60), db: Session = Depends(get_db)):
    """Películas reconocibles y variadas (por época y género) aún sin valorar."""
    rated = {fid for (fid,) in db.query(UserFilm.film_id).filter(
        UserFilm.profile_id == PROFILE, UserFilm.status.in_(("watched", "never")))}
    films = (db.query(Film).filter(Film.poster_path.isnot(None) | (Film.source == "seed"),
                                   Film.vote_count > 2000).order_by(Film.vote_count.desc()).limit(220).all())
    pool = [f for f in films if f.id not in rated]
    picked: list[Film] = []
    seen_dec: dict[int, int] = {}
    seen_gen: dict[str, int] = {}
    for f in pool:  # reparte por década y género para no preguntar solo por blockbusters recientes
        dec = (f.year or 2000) // 10
        g = f.genres[0] if f.genres else "?"
        if seen_dec.get(dec, 0) >= max(3, n // 6) or seen_gen.get(g, 0) >= max(4, n // 5):
            continue
        picked.append(f)
        seen_dec[dec] = seen_dec.get(dec, 0) + 1
        seen_gen[g] = seen_gen.get(g, 0) + 1
        if len(picked) >= n:
            break
    return {"items": [film_light(f) for f in picked]}


class OnboardItem(BaseModel):
    film_id: int
    rating: float | None = Field(default=None, ge=0.5, le=5)  # None = no la he visto


class OnboardIn(BaseModel):
    items: list[OnboardItem]


@router.post("/onboarding")
def save_onboarding(body: OnboardIn, db: Session = Depends(get_db)):
    n = 0
    for it in body.items:
        if it.rating is None:
            continue
        f = db.get(Film, it.film_id)
        if f is None:
            continue
        row = _row(db, f.id)
        if row is None:
            row = UserFilm(profile_id=PROFILE, film_id=f.id, status="none", source="onboarding")
            db.add(row)
        row.status, row.rating, row.liked = "watched", it.rating, it.rating >= 4.5
        n += 1
    db.flush()
    taste_mod.invalidate(PROFILE)
    db.commit()
    return {"saved": n}


# ---------------------------------------------------------------------------
# Rutas de cine
# ---------------------------------------------------------------------------

@router.get("/paths")
def paths(db: Session = Depends(get_db)):
    taste = build_taste(db, PROFILE)
    out = []
    for p in PATHS:
        films: list[dict[str, Any]] = []
        seen = 0
        nxt: int | None = None
        for title, year in p["films"]:
            f = catalog.find_local(db, [title], year)
            if f is None:
                continue
            st = taste.status.get(f.id, "none")
            item = {**_light(db, f), "path_title": title}
            films.append(item)
            if st == "watched":
                seen += 1
            elif nxt is None and st not in ("never", "watching"):
                nxt = f.id
        out.append({"slug": p["slug"], "title": p["title"], "emoji": p["emoji"], "blurb": p["blurb"],
                    "films": films, "seen": seen, "total": len(films), "next_id": nxt})
    return {"paths": out}


# ---------------------------------------------------------------------------
# Jellyseerr / Radarr
# ---------------------------------------------------------------------------

@router.post("/films/{film_id}/request")
def request_film(film_id: int, db: Session = Depends(get_db)):
    f = _need_film(db, film_id)
    seerr = catalog.seerr_client()
    if seerr is None:
        raise NotConfigured("Jellyseerr no está configurado")
    if f.jellyfin_id:
        raise HTTPException(409, "Ya está en tu biblioteca de Jellyfin")
    if not f.tmdb_id:
        tmdb = catalog.tmdb_client()
        if tmdb is None:
            raise NotConfigured("Esta película no tiene id de TMDB y TMDB no está configurado")
        if catalog.resolve(db, tmdb, f) is None:
            raise HTTPException(404, "No he encontrado esta película en TMDB")
        db.flush()
    res = seerr.request_movie(f.tmdb_id)
    f.seerr_status = res.get("status") or 2
    f.seerr_checked_at = utcnow()
    db.commit()
    return _light(db, f)


@router.get("/downloads")
def downloads(db: Session = Depends(get_db)):
    """Películas pedidas y su progreso de descarga (Radarr, si está configurado)."""
    rows = db.query(Film).filter(Film.seerr_status.in_((2, 3, 4))).order_by(Film.seerr_checked_at.desc()).all()
    progress: dict[int, dict] = {}
    error = None
    radarr = catalog.radarr_client()
    if radarr is not None:
        try:
            progress = radarr.progress()
        except ServiceError as e:
            error = e.message
    items = []
    for f in rows:
        item = _light(db, f)
        item["download"] = progress.get(f.tmdb_id) if f.tmdb_id else None
        items.append(item)
    return {"items": items, "radarr": radarr is not None, "error": error}
