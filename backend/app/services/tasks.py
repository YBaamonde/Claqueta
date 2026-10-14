"""Tareas largas (se ejecutan en hilos mediante ``jobs.manager``).

Todas escriben en lotes pequeños con su propia sesión: una transacción larga bloquearía las
escrituras de la API (SQLite admite un único escritor a la vez).
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Iterable, Sequence

import httpx

from .. import settings_store as S
from ..db import session_scope
from ..engine import feedback as fb
from ..engine import taste as taste_mod
from ..models import Film, FilmEdge, UserFilm
from ..util import utcnow
from . import catalog, enrich
from .errors import NotConfigured, ServiceError
from .jobs import Job
from .letterboxd import LbEntry, parse_rss
from .tmdb import TMDB

log = logging.getLogger("claqueta.tasks")
PROFILE = 1


def _chunks(seq: Sequence, n: int) -> Iterable[Sequence]:
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _need_tmdb() -> TMDB:
    t = catalog.tmdb_client()
    if t is None:
        raise NotConfigured("Configura la clave de TMDB en Ajustes para esta acción")
    return t


# ---------------------------------------------------------------------------
# Jellyfin
# ---------------------------------------------------------------------------

def sync_jellyfin(job: Job) -> dict[str, Any]:
    jf = catalog.jellyfin_client()
    if jf is None:
        raise NotConfigured("Jellyfin no está configurado")
    job.update(message="Leyendo la biblioteca de Jellyfin…")
    items = jf.library()
    job.update(total=len(items), progress=0, message="Enlazando películas…")
    tmdb = catalog.tmdb_client()
    seen: set[str] = set()
    created = matched = 0
    for chunk in _chunks(items, 40):
        with session_scope() as db:
            st = catalog.link_jellyfin(db, tmdb, list(chunk))
        seen |= st["seen"]
        created += st["created"]
        matched += st["matched"]
        job.update(progress=job.progress + len(chunk))
    with session_scope() as db:
        removed = catalog.prune_jellyfin(db, seen)
    job.update(message="Importando tu historial de reproducciones…")
    try:
        played = jf.played()
        with session_scope() as db:
            new_hist = catalog.import_jellyfin_history(db, PROFILE, played)
    except ServiceError as e:
        log.info("historial de Jellyfin no disponible: %s", e.message)
        new_hist = 0
    taste_mod.invalidate()
    sid = jf.server_id()
    if sid:
        S.set_raw("x_jf_server_id", sid)
    S.set_raw("x_last_jellyfin_sync", utcnow().isoformat())
    return {"items": len(items), "created": created, "matched": matched, "removed": removed, "history": new_hist}


# ---------------------------------------------------------------------------
# Letterboxd
# ---------------------------------------------------------------------------

def _apply_entry(db, tmdb: TMDB | None, e: LbEntry) -> bool:
    f = catalog.match_or_create(db, tmdb, title=e.title, year=e.year, tmdb_id=e.tmdb_id, source="letterboxd")
    if e.uri and not f.letterboxd_uri:
        f.letterboxd_uri = e.uri[:120]
    row = db.query(UserFilm).filter_by(profile_id=PROFILE, film_id=f.id).one_or_none()
    if row is None:
        row = UserFilm(profile_id=PROFILE, film_id=f.id, status="none", source="letterboxd")
        db.add(row)
    if e.watched or e.liked:
        row.status = "watched" if row.status != "never" else row.status
        if e.rating is not None:
            row.rating = e.rating
        if e.watched_date and (row.watched_date is None or e.watched_date > row.watched_date):
            row.watched_date = e.watched_date
        row.liked = row.liked or e.liked
        row.rewatch = row.rewatch or e.rewatch
        if row.source == "app":
            row.source = "letterboxd"
    elif e.watchlist and row.status in ("none", "watchlist"):
        row.status = "watchlist"
    db.flush()
    return True


def import_letterboxd(job: Job, entries: list[LbEntry]) -> dict[str, Any]:
    tmdb = catalog.tmdb_client()
    job.update(total=len(entries), progress=0, message="Emparejando con TMDB…" if tmdb else "Importando (sin TMDB)…")
    ok = failed = 0
    # primero lo visto (alimenta el gusto), luego la watchlist
    ordered = sorted(entries, key=lambda e: (not e.watched, e.watchlist))
    for chunk in _chunks(ordered, 12):
        with session_scope() as db:
            for e in chunk:
                try:
                    _apply_entry(db, tmdb, e)
                    ok += 1
                except ServiceError as err:
                    failed += 1
                    log.info("no se pudo importar %s: %s", e.title, err.message)
                except Exception:  # noqa: BLE001
                    failed += 1
                    log.exception("fallo importando %s", e.title)
        job.update(progress=job.progress + len(chunk))
    taste_mod.invalidate()
    S.set_raw("x_last_letterboxd_import", utcnow().isoformat())
    return {"entries": len(entries), "imported": ok, "failed": failed,
            "watched": sum(1 for e in entries if e.watched), "watchlist": sum(1 for e in entries if e.watchlist),
            "tmdb": bool(tmdb)}


def sync_letterboxd_rss(job: Job) -> dict[str, Any]:
    user = S.get("letterboxd_username")
    if not user:
        raise NotConfigured("Indica tu usuario de Letterboxd en Ajustes")
    try:
        r = httpx.get(f"https://letterboxd.com/{user}/rss/", timeout=20, follow_redirects=True,
                      headers={"User-Agent": "Claqueta/1.0 (+self-hosted)"})
    except httpx.HTTPError as e:
        raise ServiceError(f"No se pudo leer el RSS de Letterboxd: {e.__class__.__name__}") from e
    if r.status_code == 404:
        raise ServiceError("No existe ese usuario de Letterboxd (o su perfil es privado)")
    if r.status_code != 200:
        raise ServiceError(f"Letterboxd respondió {r.status_code}")
    entries = parse_rss(r.text)
    res = import_letterboxd(job, entries)
    S.set_raw("x_last_letterboxd_rss", utcnow().isoformat())
    return res


# ---------------------------------------------------------------------------
# Resolución y ampliación del catálogo
# ---------------------------------------------------------------------------

def _fetch_details(tmdb: TMDB, ids: list[int], workers: int = 6) -> dict[int, dict | None]:
    def one(i: int) -> tuple[int, dict | None]:
        try:
            return i, tmdb.details(i)
        except ServiceError as e:
            log.info("TMDB details %s: %s", i, e.message)
            return i, None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        return dict(ex.map(one, ids))


def hydrate_partials(job: Job | None, limit: int, only_user: bool = False) -> int:
    """Completa fichas parciales con prioridad: tu historial → biblioteca → más votadas."""
    tmdb = catalog.tmdb_client()
    if tmdb is None:
        return 0
    with session_scope() as db:
        q = db.query(Film.id, Film.tmdb_id).filter(Film.tmdb_id.isnot(None), Film.details_at.is_(None))
        if only_user:
            q = q.join(UserFilm, UserFilm.film_id == Film.id)
        rows = q.order_by(Film.jellyfin_id.is_(None), Film.vote_count.desc()).limit(limit).all()
    if job:
        job.update(total=len(rows), progress=0, message=f"Completando {len(rows)} fichas…")
    done = 0
    for chunk in _chunks(rows, 30):
        details = _fetch_details(tmdb, [t for _, t in chunk])
        with session_scope() as db:
            for fid, tid in chunk:
                p = details.get(tid)
                f = db.get(Film, fid)
                if p and f:
                    try:
                        catalog.apply_parsed(f, p)
                        done += 1
                    except Exception:  # noqa: BLE001
                        log.exception("no se pudo aplicar la ficha %s", tid)
        if job:
            job.update(progress=job.progress + len(chunk))
    return done


def resolve_catalog(job: Job) -> dict[str, Any]:
    """Asigna id de TMDB a la semilla y a los stubs, y completa lo que importa (historial)."""
    tmdb = _need_tmdb()
    with session_scope() as db:
        ids = [i for (i,) in db.query(Film.id).filter(Film.tmdb_id.is_(None))
               .order_by(Film.source == "seed", Film.id).all()]
    job.update(total=len(ids), progress=0, message=f"Buscando {len(ids)} películas en TMDB…")
    resolved = missed = 0
    for fid in ids:
        with session_scope() as db:
            f = db.get(Film, fid)
            if f is not None:
                try:
                    if catalog.resolve(db, tmdb, f):
                        resolved += 1
                    else:
                        missed += 1
                except ServiceError as e:
                    missed += 1
                    log.info("sin resolver %s: %s", f.title, e.message)
        job.update(progress=job.progress + 1)
    hydrated = hydrate_partials(job, 400, only_user=True)
    taste_mod.invalidate()
    S.set_raw("x_last_resolve", utcnow().isoformat())
    return {"resolved": resolved, "missed": missed, "hydrated": hydrated}


DECADES = [(1920, 1929), (1930, 1939), (1940, 1949), (1950, 1959), (1960, 1969), (1970, 1979), (1980, 1989),
           (1990, 1999), (2000, 2009), (2010, 2019), (2020, 2029)]


def expand_catalog(job: Job, hydrate_limit: int = 700) -> dict[str, Any]:
    """Amplía el universo de candidatas: afines a lo que te gusta, mejor valoradas y clásicos por década."""
    tmdb = _need_tmdb()
    added = 0
    job.update(total=4 + len(DECADES), progress=0, message="Buscando películas afines a tus favoritas…")

    def add(items: list[dict]) -> None:
        nonlocal added
        with session_scope() as db:
            for p in items:
                had = db.query(Film.id).filter(Film.tmdb_id == p["tmdb_id"]).first() is not None
                catalog.upsert(db, p, "tmdb")
                added += 0 if had else 1

    # 1) afines (TMDB recommendations) a tus 4★+; se guardan las relaciones para explicar «porque te gustó X»
    with session_scope() as db:
        seeds = [(f.id, f.tmdb_id) for uf, f in
                 db.query(UserFilm, Film).join(Film, Film.id == UserFilm.film_id)
                 .filter(UserFilm.profile_id == PROFILE, UserFilm.rating >= 4, Film.tmdb_id.isnot(None))
                 .order_by(UserFilm.rating.desc(), UserFilm.updated_at.desc()).limit(80).all()]
        done_src = {s for (s,) in db.query(FilmEdge.src_id).distinct().all()}
    for fid, tid in seeds:
        if fid in done_src:
            continue
        try:
            recs = tmdb.recommendations(tid)
        except ServiceError:
            continue
        with session_scope() as db:
            for p in recs:
                had = db.query(Film.id).filter(Film.tmdb_id == p["tmdb_id"]).first() is not None
                f = catalog.upsert(db, p, "tmdb")
                added += 0 if had else 1
                if not db.query(FilmEdge).filter_by(src_id=fid, dst_id=f.id, kind="rec").first():
                    db.add(FilmEdge(src_id=fid, dst_id=f.id, kind="rec"))
    job.update(progress=1, message="Añadiendo las mejor valoradas de todos los tiempos…")

    # 2) top rated + populares
    for page in range(1, 11):
        try:
            add(tmdb.top_rated(page))
        except ServiceError:
            break
    job.update(progress=2)
    for page in range(1, 4):
        try:
            add(tmdb.popular(page))
        except ServiceError:
            break
    job.update(progress=3, message="Rescatando clásicos por década…")

    # 3) lo mejor de cada década (para que los clásicos tengan representación)
    for lo, hi in DECADES:
        for page in (1, 2):
            try:
                add(tmdb.discover(sort_by="vote_average.desc", **{"vote_count.gte": 1200 if lo >= 1960 else 500},
                                  **{"primary_release_date.gte": f"{lo}-01-01",
                                     "primary_release_date.lte": f"{hi}-12-31"}, page=page))
            except ServiceError:
                break
        job.update(progress=job.progress + 1)

    job.update(message="Completando fichas (duración, reparto, streaming)…")
    hydrated = hydrate_partials(job, hydrate_limit)
    S.set_raw("x_last_expand", utcnow().isoformat())
    return {"added": added, "hydrated": hydrated, "seeds": len(seeds)}


# ---------------------------------------------------------------------------
# Jellyseerr / enriquecimiento / mantenimiento
# ---------------------------------------------------------------------------

def refresh_seerr(job: Job) -> dict[str, Any]:
    seerr = catalog.seerr_client()
    if seerr is None:
        raise NotConfigured("Jellyseerr no está configurado")
    with session_scope() as db:
        rows = [(f.id, f.tmdb_id) for f in
                db.query(Film).filter(Film.seerr_status.in_((2, 3, 4)), Film.tmdb_id.isnot(None)).limit(60).all()]
    changed = 0
    for fid, tid in rows:
        try:
            st = seerr.status(tid)
        except ServiceError:
            continue
        with session_scope() as db:
            f = db.get(Film, fid)
            if f:
                if st != f.seerr_status:
                    f.seerr_status = st
                    changed += 1
                f.seerr_checked_at = utcnow()
    return {"checked": len(rows), "changed": changed}


def enrich_run(job: Job, max_batches: int = 20) -> dict[str, Any]:
    if enrich.llm_or_none() is None:
        raise NotConfigured("Configura un LLM en Ajustes para enriquecer las fichas")
    total = 0
    job.update(total=max_batches, progress=0, message="Pidiendo al LLM que valore las películas…")
    for i in range(max_batches):
        with session_scope() as db:
            res = enrich.enrich_tick(db)
        if "enriched" not in res:
            job.update(message=f"Parado: {res.get('skipped')}")
            break
        total += res["enriched"]
        job.update(progress=i + 1)
    return {"enriched": total}


def learn(job: Job | None = None) -> dict[str, Any]:
    with session_scope() as db:
        return fb.recompute_adjust(db, PROFILE)


def maintenance(job: Job) -> dict[str, Any]:
    """Pequeño goteo diario: completa fichas pendientes."""
    n = hydrate_partials(job, 120)
    return {"hydrated": n}
