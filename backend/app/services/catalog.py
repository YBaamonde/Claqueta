"""Catálogo local: altas/fusiones de películas desde TMDB, Jellyfin y Letterboxd."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import settings_store as S
from ..engine.attrs import heuristic_attrs
from ..models import FeedbackEvent, Film, FilmEdge, UserFilm
from ..util import norm_title, utcnow
from .errors import NotConfigured, ServiceError
from .jellyfin import Jellyfin
from .jellyseerr import Jellyseerr
from .radarr import Radarr
from .tmdb import TMDB, best_match

log = logging.getLogger("claqueta.catalog")

COPY_FIELDS = ["imdb_id", "title", "original_title", "year", "release_date", "runtime", "overview", "tagline",
               "genres", "directors", "cast", "countries", "original_language", "keywords", "min_age", "adult",
               "poster_path", "backdrop_path", "trailer_key", "vote_average", "vote_count", "popularity"]
PARTIAL_FILL_ONLY = {"imdb_id", "runtime", "tagline", "directors", "cast", "countries", "keywords", "min_age",
                     "trailer_key"}


# --- clientes ---------------------------------------------------------------

def tmdb_client() -> TMDB | None:
    key = S.get("tmdb_api_key")
    if not key:
        return None
    return TMDB(key, S.get("tmdb_language", "es-ES"), S.get("region", "ES"))


def jellyfin_client() -> Jellyfin | None:
    if not (S.get("jellyfin_url") and S.get("jellyfin_api_key")):
        return None
    return Jellyfin(S.get("jellyfin_url"), S.get("jellyfin_api_key"), S.get("jellyfin_user_id", "") or "",
                    S.get("jellyfin_public_url", "") or "")


def seerr_client() -> Jellyseerr | None:
    if not (S.get("jellyseerr_url") and S.get("jellyseerr_api_key")):
        return None
    return Jellyseerr(S.get("jellyseerr_url"), S.get("jellyseerr_api_key"), S.get("jellyseerr_public_url", "") or "")


def radarr_client() -> Radarr | None:
    if not (S.get("radarr_url") and S.get("radarr_api_key")):
        return None
    return Radarr(S.get("radarr_url"), S.get("radarr_api_key"))


# --- altas / fusiones ---------------------------------------------------------

def find_local(db: Session, titles: Iterable[str | None], year: int | None, *, unresolved_only: bool = False,
               tmdb_id: int | None = None) -> Film | None:
    if tmdb_id:
        f = db.query(Film).filter(Film.tmdb_id == tmdb_id).first()
        if f:
            return f
    norms = {norm_title(t) for t in titles if t}
    norms.discard("")
    if not norms:
        return None
    q = db.query(Film).filter(or_(Film.norm_title.in_(norms), Film.norm_alt.in_(norms)))
    if unresolved_only:
        q = q.filter(Film.tmdb_id.is_(None))
    cands = q.all()
    if not cands:
        return None
    if year:
        exact = [c for c in cands if c.year == year]
        if exact:
            return exact[0]
        near = [c for c in cands if c.year and abs(c.year - year) == 1]
        return near[0] if near else None
    return cands[0] if len(cands) == 1 else None


def apply_parsed(f: Film, p: dict[str, Any], source: str | None = None) -> Film:
    partial = bool(p.get("partial"))
    has_details = f.details_at is not None
    for k in COPY_FIELDS:
        v = p.get(k)
        if v in (None, "", []):
            continue
        if has_details and partial and k not in ("vote_average", "vote_count", "popularity", "poster_path",
                                                 "backdrop_path"):
            continue  # una ficha parcial nunca pisa una completa
        if k in PARTIAL_FILL_ONLY and getattr(f, k) and partial:
            continue
        setattr(f, k, v)
    if p.get("tmdb_id") and not f.tmdb_id:
        f.tmdb_id = p["tmdb_id"]
    if p.get("providers"):
        f.providers = p["providers"]
        f.providers_at = utcnow()
    if not partial:
        f.details_at = utcnow()
    if source and not f.source:
        f.source = source
    f.norm_title = norm_title(f.title)
    f.norm_alt = norm_title(f.original_title) if f.original_title else ""
    if f.attrs_source in ("none", "heuristic") and (not partial or not f.attrs):
        notes = (f.attrs or {}).get("notes")
        f.attrs = heuristic_attrs(f)
        if notes:
            f.attrs["notes"] = notes
        f.attrs_source, f.attrs_at = "heuristic", utcnow()
    return f


def upsert(db: Session, p: dict[str, Any], source: str = "tmdb") -> Film:
    f = None
    if p.get("tmdb_id"):
        f = db.query(Film).filter(Film.tmdb_id == p["tmdb_id"]).one_or_none()
    if f is None:
        f = find_local(db, [p.get("title"), p.get("original_title")], p.get("year"), unresolved_only=True)
    if f is None:
        f = Film(title=p.get("title") or "?", source=source, genres=[], directors=[], cast=[], countries=[],
                 keywords=[], providers={}, attrs={})
        db.add(f)
    apply_parsed(f, p, source)
    db.flush()
    return f


def merge_films(db: Session, keep: Film, drop: Film) -> Film:
    """Fusiona ``drop`` dentro de ``keep`` conservando el estado del usuario y las relaciones."""
    if keep.id == drop.id:
        return keep
    for uf in db.query(UserFilm).filter(UserFilm.film_id == drop.id).all():
        other = db.query(UserFilm).filter_by(profile_id=uf.profile_id, film_id=keep.id).one_or_none()
        if other is None:
            uf.film_id = keep.id
        else:
            for attr in ("rating", "watched_date", "notes", "started_at", "snoozed_until"):
                if getattr(other, attr) is None and getattr(uf, attr) is not None:
                    setattr(other, attr, getattr(uf, attr))
            other.liked = other.liked or uf.liked
            if other.status in ("none", "watchlist") and uf.status not in ("none",):
                other.status = uf.status
            db.delete(uf)
    db.query(FeedbackEvent).filter(FeedbackEvent.film_id == drop.id).update({"film_id": keep.id})
    for e in db.query(FilmEdge).filter((FilmEdge.src_id == drop.id) | (FilmEdge.dst_id == drop.id)).all():
        db.delete(e)
    for attr in ("jellyfin_id", "letterboxd_uri", "seerr_status"):
        if getattr(keep, attr) is None and getattr(drop, attr) is not None:
            setattr(keep, attr, getattr(drop, attr))
    if drop.attrs_source in ("seed", "llm") and keep.attrs_source in ("none", "heuristic"):
        keep.attrs, keep.attrs_source, keep.attrs_at = drop.attrs, drop.attrs_source, drop.attrs_at
    db.flush()
    db.delete(drop)
    db.flush()
    return keep


def hydrate(db: Session, tmdb: TMDB, f: Film) -> Film:
    """Completa la ficha con /movie/{id}. Si el id ya pertenece a otra fila, las fusiona."""
    if not f.tmdb_id:
        return f
    p = tmdb.details(f.tmdb_id)
    clash = db.query(Film).filter(Film.tmdb_id == f.tmdb_id, Film.id != f.id).one_or_none()
    if clash:
        f = merge_films(db, clash, f) if clash.details_at else merge_films(db, f, clash)
    apply_parsed(f, p)
    db.flush()
    return f


def resolve(db: Session, tmdb: TMDB, f: Film) -> Film | None:
    """Busca en TMDB una película sin id (semilla, stub de Letterboxd/Jellyfin) y la completa."""
    if f.tmdb_id:
        return f
    titles = [t for t in (f.original_title, f.title) if t]
    match = None
    for t in dict.fromkeys(titles):
        results = tmdb.search(t, f.year)
        if not results and f.year:
            results = tmdb.search(t)
        match = best_match(results, titles, f.year)
        if match:
            break
    if not match:
        return None
    clash = db.query(Film).filter(Film.tmdb_id == match["tmdb_id"], Film.id != f.id).one_or_none()
    if clash:
        f = merge_films(db, clash, f)
    else:
        f.tmdb_id = match["tmdb_id"]
    return hydrate(db, tmdb, f)


def match_or_create(db: Session, tmdb: TMDB | None, *, title: str, year: int | None, tmdb_id: int | None = None,
                    source: str = "letterboxd", hydrate_now: bool = True) -> Film:
    f = find_local(db, [title], year, tmdb_id=tmdb_id)
    if f is None and tmdb is not None:
        try:
            if tmdb_id:
                f = upsert(db, tmdb.details(tmdb_id), source)
            else:
                res = tmdb.search(title, year) or (tmdb.search(title) if year else [])
                m = best_match(res, [title], year)
                if m:
                    f = upsert(db, m, source)
        except ServiceError as e:
            if e.status == 429:
                raise
            log.info("sin coincidencia en TMDB para %s (%s): %s", title, year, e.message)
    if f is None:
        f = Film(title=title, year=year, source=source, genres=[], directors=[], cast=[], countries=[],
                 keywords=[], providers={}, attrs={})
        db.add(f)
        apply_parsed(f, {"title": title, "year": year, "partial": True})
        db.flush()
    elif tmdb is not None and hydrate_now and f.details_at is None and f.tmdb_id:
        try:
            hydrate(db, tmdb, f)
        except NotConfigured:
            pass
        except ServiceError as e:
            if e.status == 429:
                raise
    return f


# --- Jellyfin ---------------------------------------------------------------

def link_jellyfin(db: Session, tmdb: TMDB | None, items: list[dict]) -> dict[str, Any]:
    """Enlaza un lote de elementos de Jellyfin con el catálogo. Devuelve estadísticas y los ids vistos."""
    seen: set[str] = set()
    created = matched = 0
    for it in items:
        f = find_local(db, [it["title"], it.get("original_title")], it.get("year"), tmdb_id=it.get("tmdb_id"))
        if f is None:
            if tmdb is not None and it.get("tmdb_id"):
                try:
                    f = upsert(db, tmdb.details(it["tmdb_id"]), "jellyfin")
                except ServiceError:
                    f = None
            if f is None:
                f = Film(title=it["title"], original_title=it.get("original_title"), year=it.get("year"),
                         runtime=it.get("runtime"), overview=it.get("overview"), genres=it.get("genres") or [],
                         tmdb_id=it.get("tmdb_id"), imdb_id=it.get("imdb_id"), source="jellyfin", directors=[],
                         cast=[], countries=[], keywords=[], providers={}, attrs={})
                db.add(f)
                apply_parsed(f, {"title": it["title"], "year": it.get("year"), "partial": True})
                db.flush()
            created += 1
        else:
            matched += 1
        if not f.runtime and it.get("runtime"):
            f.runtime = it["runtime"]
        if not f.genres and it.get("genres"):
            f.genres = it["genres"]
            if f.attrs_source in ("none", "heuristic"):
                f.attrs = heuristic_attrs(f)
        f.jellyfin_id = it["jf_id"]
        seen.add(it["jf_id"])
    db.flush()
    return {"created": created, "matched": matched, "seen": seen}


def prune_jellyfin(db: Session, seen: set[str]) -> int:
    """Lo que ya no está en la biblioteca deja de figurar como disponible."""
    if not seen:
        return 0
    gone = db.query(Film).filter(Film.jellyfin_id.isnot(None), Film.jellyfin_id.notin_(seen)).all()
    for f in gone:
        f.jellyfin_id = None
    db.flush()
    return len(gone)


def import_jellyfin_history(db: Session, profile_id: int, items: list[dict]) -> int:
    n = 0
    for it in items:
        f = db.query(Film).filter(Film.jellyfin_id == it["jf_id"]).one_or_none()
        if f is None:
            continue
        row = db.query(UserFilm).filter_by(profile_id=profile_id, film_id=f.id).one_or_none()
        if row is None:
            row = UserFilm(profile_id=profile_id, film_id=f.id, status="none", source="jellyfin")
            db.add(row)
        if row.status in ("none", "watchlist", "parked", "watching"):
            row.status = "watched"
            lp = it.get("last_played")
            if lp and not row.watched_date:
                try:
                    row.watched_date = datetime.fromisoformat(lp.replace("Z", "+00:00")[:19]).date()
                except ValueError:
                    pass
            n += 1
    db.flush()
    return n
