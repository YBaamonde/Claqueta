"""Arranque del frontend, ajustes, importaciones, tareas en segundo plano, perfil de gusto, inicio y exportaciones."""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import settings_store as S
from ..config import VERSION
from ..db import get_db
from ..engine import feedback as fb
from ..engine import taste as taste_mod
from ..engine.attrs import ATTR_KEYS
from ..engine.context import COMPANIES, ERAS
from ..engine.moods import MOODS
from ..engine.taste import build_taste
from ..engine.weights import DEFAULT_WEIGHTS, WEIGHT_META, get_weights
from ..genres import CANONICAL
from ..models import FeedbackEvent, Film, Profile, UserFilm
from ..services import catalog, demo, enrich, tasks
from ..services.errors import NotConfigured, ServiceError
from ..services.jobs import manager
from ..services.letterboxd import export_diary_csv, export_watchlist_csv, parse_files
from ..services.llm import PRESETS, LLM, daily_used
from .serializers import film_light

log = logging.getLogger("claqueta.api.system")
router = APIRouter(prefix="/api")
PROFILE = 1
MAX_UPLOAD = 60 * 1024 * 1024

COMPANY_LABELS = {
    "solo": ("Solo", "🧍"), "pareja": ("En pareja", "💑"), "amigos": ("Con amigos", "🍻"),
    "familia": ("En familia", "👨‍👩‍👧"), "peques": ("Con peques", "🧸"),
}

ATTR_LABELS = {
    "pace": "Ritmo rápido", "intensity": "Intensidad", "tension": "Tensión", "humor": "Humor", "warmth": "Calidez",
    "darkness": "Oscuridad", "emotional": "Carga emocional", "complexity": "Complejidad", "weirdness": "Rareza",
    "spectacle": "Espectáculo", "romance": "Romance", "dated": "Aire de época", "access": "Accesibilidad",
    "family": "Apta para familia", "rewatch": "Rever",
}


# ---------------------------------------------------------------------------
# Estado general
# ---------------------------------------------------------------------------

@router.get("/health")
def health():
    return {"ok": True, "version": VERSION}


def _stats(db: Session) -> dict[str, Any]:
    def uf(status: str) -> int:
        return db.query(UserFilm).filter_by(profile_id=PROFILE, status=status).count()

    return {
        "films": db.query(Film).count(),
        "complete": db.query(Film).filter(Film.details_at.isnot(None)).count(),
        "jellyfin": db.query(Film).filter(Film.jellyfin_id.isnot(None)).count(),
        "watched": uf("watched"), "watchlist": uf("watchlist"), "parked": uf("parked"),
        "watching": uf("watching"),
        "demo": db.query(UserFilm).filter_by(profile_id=PROFILE, source="demo").count(),
        "enrich": enrich.counts(db),
    }


def _last_runs() -> dict[str, Any]:
    keys = ["jellyfin_sync", "letterboxd_import", "letterboxd_rss", "resolve", "expand", "enrich", "seerr"]
    return {k: S.get_raw(f"x_last_{k}") for k in keys}


@router.get("/bootstrap")
def bootstrap(db: Session = Depends(get_db)):
    prof = db.get(Profile, PROFILE)
    stats = _stats(db)
    return {
        "version": VERSION,
        "moods": [{"id": m.id, "label": m.label, "emoji": m.emoji, "blurb": m.blurb, "colors": list(m.colors)}
                  for m in MOODS],
        "companies": [{"id": c, "label": COMPANY_LABELS[c][0], "emoji": COMPANY_LABELS[c][1]} for c in COMPANIES],
        "eras": [{"id": e[0], "label": e[1]} for e in ERAS],
        "genres": CANONICAL,
        "reasons": fb.REASONS,
        "configured": S.configured(),
        "stats": stats,
        "last_context": (prof.last_context if prof else None) or {},
        "defaults": {"anti_toston": bool(S.get("anti_toston_default", True))},
        "needs_onboarding": stats["watched"] == 0,
        "llm": {"presets": PRESETS, "used_today": daily_used(),
                "daily_cap": int(S.get("llm_daily_tokens", 120000) or 0)},
        "last_runs": _last_runs(),
    }


# ---------------------------------------------------------------------------
# Ajustes
# ---------------------------------------------------------------------------

@router.get("/settings")
def get_settings():
    out = S.masked_view()
    w = get_weights()
    out["weights"] = {m["key"]: {**m, "value": round(w[m["key"]], 3), "default": DEFAULT_WEIGHTS[m["key"]]}
                      for m in WEIGHT_META}
    out["presets"] = PRESETS
    return out


class SettingsIn(BaseModel):
    values: dict[str, Any] = {}
    weights: dict[str, float] | None = None


@router.put("/settings")
def put_settings(body: SettingsIn):
    values = dict(body.values)
    extra = values.get("llm_extra_body")
    if isinstance(extra, str) and extra.strip():
        try:
            if not isinstance(json.loads(extra), dict):
                raise ValueError
        except ValueError:
            raise HTTPException(400, 'Los parámetros extra del LLM deben ser un objeto JSON, p. ej. {"reasoning_effort":"low"}')
    for k in ("llm_tpm", "llm_daily_tokens"):
        if k in values:
            try:
                values[k] = max(0, int(float(values[k])))
            except (TypeError, ValueError):
                raise HTTPException(400, f"«{k}» debe ser un número")
    if body.weights is not None:
        clean = {}
        for k, v in body.weights.items():
            if k in DEFAULT_WEIGHTS:
                clean[k] = round(max(0.0, min(1.0, float(v))), 3)
        # solo se guardan las diferencias respecto a los valores por defecto
        values["engine_weights"] = {k: v for k, v in clean.items() if abs(v - DEFAULT_WEIGHTS[k]) > 1e-6}
    changed = S.set_many(values)
    return {"changed": changed, **get_settings(), "configured": S.configured()}


@router.post("/settings/test/{service}")
def test_service(service: str):
    """Comprueba una conexión con los valores *guardados*."""
    try:
        if service == "tmdb":
            t = catalog.tmdb_client()
            if t is None:
                raise NotConfigured("Falta la clave de TMDB")
            t.check()
            return {"ok": True, "message": "Conectado con TMDB"}
        if service == "jellyfin":
            jf = catalog.jellyfin_client()
            if jf is None:
                raise NotConfigured("Faltan la URL y la clave de Jellyfin")
            info = jf.check()
            return {"ok": True, "message": f"Conectado: {info.get('name')} {info.get('version')}"}
        if service == "jellyseerr":
            js = catalog.seerr_client()
            if js is None:
                raise NotConfigured("Faltan la URL y la clave de Jellyseerr")
            info = js.check()
            return {"ok": True, "message": f"Conectado a Jellyseerr {info.get('version')} como {info.get('user')}"}
        if service == "radarr":
            rd = catalog.radarr_client()
            if rd is None:
                raise NotConfigured("Faltan la URL y la clave de Radarr")
            info = rd.check()
            return {"ok": True, "message": f"Conectado a Radarr {info.get('version')}"}
        if service == "llm":
            llm = LLM.from_settings()
            out = llm.chat_json("Responde SOLO con JSON.", 'Devuelve {"ok": true}', max_tokens=40)
            return {"ok": bool(out), "message": f"El modelo {llm.model} responde correctamente"}
        if service == "letterboxd":
            user = S.get("letterboxd_username")
            if not user:
                raise NotConfigured("Falta tu usuario de Letterboxd")
            import httpx

            r = httpx.get(f"https://letterboxd.com/{user}/rss/", timeout=15, follow_redirects=True,
                          headers={"User-Agent": "Claqueta/1.0 (+self-hosted)"})
            if r.status_code != 200:
                raise ServiceError(f"Letterboxd respondió {r.status_code}: ¿usuario correcto y perfil público?")
            return {"ok": True, "message": f"Perfil de {user} accesible"}
    except ServiceError as e:
        return {"ok": False, "message": e.message}
    except Exception as e:  # noqa: BLE001
        log.info("test %s falló: %s", service, e)
        return {"ok": False, "message": f"{e.__class__.__name__}: {e}"}
    raise HTTPException(404, "Servicio desconocido")


# ---------------------------------------------------------------------------
# Tareas en segundo plano e importaciones
# ---------------------------------------------------------------------------

@router.get("/jobs")
def jobs():
    return {"jobs": manager.recent(12)}


@router.get("/jobs/{job_id}")
def job(job_id: str):
    j = manager.get(job_id)
    if j is None:
        raise HTTPException(404, "Tarea no encontrada")
    return j.as_dict()


@router.post("/import/letterboxd")
async def import_letterboxd(files: list[UploadFile] = File(...)):
    """Acepta el ZIP de exportación de Letterboxd o los CSV sueltos (watched, ratings, diary, watchlist, likes)."""
    blobs: dict[str, bytes] = {}
    total = 0
    for f in files:
        data = await f.read()
        total += len(data)
        if total > MAX_UPLOAD:
            raise HTTPException(413, "Los archivos son demasiado grandes")
        blobs[f.filename or f"file{len(blobs)}.csv"] = data
    try:
        entries = parse_files(blobs)
    except ServiceError as e:
        raise HTTPException(400, e.message) from e
    if not entries:
        raise HTTPException(400, "No encontré películas en esos archivos")
    j = manager.start("import_letterboxd", "Importando Letterboxd", tasks.import_letterboxd, entries)
    return j.as_dict()


SYNCS: dict[str, tuple[str, str, Any, str | None]] = {
    # what: (kind, título, función, servicio requerido)
    "jellyfin": ("sync_jellyfin", "Sincronizando Jellyfin", tasks.sync_jellyfin, "jellyfin"),
    "letterboxd-rss": ("sync_lb_rss", "Leyendo tu RSS de Letterboxd", tasks.sync_letterboxd_rss, "letterboxd"),
    "resolve": ("resolve", "Identificando películas en TMDB", tasks.resolve_catalog, "tmdb"),
    "expand": ("expand", "Ampliando el catálogo", tasks.expand_catalog, "tmdb"),
    "enrich": ("enrich", "Enriqueciendo fichas con el LLM", tasks.enrich_run, "llm"),
    "seerr": ("seerr", "Actualizando peticiones", tasks.refresh_seerr, "jellyseerr"),
}
NEED_MSG = {
    "jellyfin": "Configura Jellyfin (URL y clave) en Ajustes", "letterboxd": "Indica tu usuario de Letterboxd en Ajustes",
    "tmdb": "Configura la clave de TMDB en Ajustes", "llm": "Configura un LLM en Ajustes",
    "jellyseerr": "Configura Jellyseerr en Ajustes",
}


@router.post("/sync/{what}")
def sync(what: str):
    spec = SYNCS.get(what)
    if spec is None:
        raise HTTPException(404, "Tarea desconocida")
    kind, title, fn, need = spec
    if need and not S.configured().get(need):
        raise NotConfigured(NEED_MSG[need])
    return manager.start(kind, title, fn).as_dict()


# ---------------------------------------------------------------------------
# Datos de ejemplo
# ---------------------------------------------------------------------------

@router.post("/demo/load")
def demo_load(db: Session = Depends(get_db)):
    added = demo.load_seed(db)
    demo.ensure_attrs_all(db)
    n = demo.load_sample_history(db, PROFILE)
    db.commit()
    taste_mod.invalidate()
    return {"seed_added": added, "history": n}


@router.delete("/demo/history")
def demo_clear(db: Session = Depends(get_db)):
    n = demo.clear_demo(db, PROFILE)
    db.commit()
    taste_mod.invalidate()
    return {"removed": n}


# ---------------------------------------------------------------------------
# Perfil de gusto
# ---------------------------------------------------------------------------

def _rank(d: dict, stats: dict, n: int, min_count: int = 1, reverse: bool = True) -> list[dict]:
    rows = []
    for k, v in d.items():
        cnt, avg = stats.get(k, (0, None))
        if cnt >= min_count or not stats:
            rows.append({"name": str(k), "affinity": round(v, 2), "count": cnt, "avg": round(avg, 2) if avg else None})
    rows.sort(key=lambda r: r["affinity"], reverse=reverse)
    return rows[:n]


def _old_label(x: float) -> str:
    return "Alta: te lo pasas bien con clásicos" if x >= .62 else "Media: clásicos sí, pero seleccionados" if x >= .38 \
        else "Baja: prefiero cine más reciente (te protejo de tostones)"


@router.get("/taste")
def taste(db: Session = Depends(get_db)):
    t = build_taste(db, PROFILE)
    tilt = sorted(({"key": k, "label": ATTR_LABELS.get(k, k), "value": round(v, 2)}
                   for k, v in t.attr_tilt.items() if abs(v) > .06 and k in ATTR_KEYS),
                  key=lambda r: -abs(r["value"]))[:8]
    liked = sorted(t.liked_seeds.items(), key=lambda kv: -kv[1])[:8]
    titles = {f.id: f for f in db.query(Film).filter(Film.id.in_([i for i, _ in liked]))} if liked else {}
    fav = [film_light(titles[i], "watched", r) for i, r in liked if i in titles]
    decades = [{"name": f"{d}s", "affinity": round(v, 2), "count": None} for d, v in sorted(t.decade.items())]
    adj = t.adjust or {}
    return {
        "n_rated": t.n_rated, "n_watched": t.n_watched, "mean_rating": round(t.mean_rating, 2),
        "old_tolerance": round(t.old_tolerance, 2), "old_label": _old_label(t.old_tolerance), "old_seen": t.old_seen,
        "genres_up": [g for g in _rank(t.genre, t.genre_stats, 8) if g["affinity"] > .03],
        "genres_down": [g for g in _rank(t.genre, t.genre_stats, 5, reverse=False) if g["affinity"] < -.03],
        "directors": [d for d in _rank(t.director, t.director_stats, 8, min_count=1) if d["affinity"] > .05],
        "decades": decades,
        "countries": [c for c in _rank(t.country, {}, 6) if c["affinity"] > .05],
        "attr_tilt": tilt,
        "favorites": fav,
        "learned": {"counts": adj.get("counts", {}), "genre": adj.get("genre", {}), "people": adj.get("people", {}),
                    "old_tol": adj.get("old_tol", 0), "adventure": adj.get("adventure", 0)},
        "feedback_total": db.query(FeedbackEvent).filter_by(profile_id=PROFILE, undone=False).count(),
        "cold_start": t.n_rated < 8,
    }


@router.post("/taste/reset-learning")
def reset_learning(db: Session = Depends(get_db)):
    """Olvida lo aprendido por tus descartes (no toca tus valoraciones)."""
    db.query(FeedbackEvent).filter_by(profile_id=PROFILE).delete()
    prof = db.get(Profile, PROFILE)
    if prof:
        prof.taste_adjust = {}
    db.commit()
    taste_mod.invalidate()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Inicio
# ---------------------------------------------------------------------------

@router.get("/home")
def home(db: Session = Depends(get_db)):
    def light_for(status: str, order, limit: int) -> list[dict]:
        rows = (db.query(Film, UserFilm).join(UserFilm, UserFilm.film_id == Film.id)
                .filter(UserFilm.profile_id == PROFILE, UserFilm.status == status).order_by(order).limit(limit).all())
        return [film_light(f, u.status, u.rating, u.liked, u.watched_date.isoformat() if u.watched_date else None)
                for f, u in rows]

    stats = _stats(db)
    return {
        "watching": light_for("watching", UserFilm.updated_at.desc(), 6),
        "parked": light_for("parked", UserFilm.updated_at.desc(), 8),
        "recent": light_for("watched", func.coalesce(UserFilm.watched_date, func.date(UserFilm.updated_at)).desc(), 8),
        "requested": db.query(Film).filter(Film.seerr_status.in_((2, 3, 4))).count(),
        "stats": stats,
        "configured": S.configured(),
        "needs_onboarding": stats["watched"] == 0,
    }


# ---------------------------------------------------------------------------
# Exportar a Letterboxd (sin API de escritura: se importa a mano con su asistente)
# ---------------------------------------------------------------------------

@router.get("/export/letterboxd/{kind}")
def export_letterboxd(kind: str, db: Session = Depends(get_db)):
    if kind == "diary":
        rows = (db.query(Film, UserFilm).join(UserFilm, UserFilm.film_id == Film.id)
                .filter(UserFilm.profile_id == PROFILE, UserFilm.status == "watched",
                        UserFilm.source.in_(("app", "jellyfin"))).order_by(UserFilm.watched_date).all())
        data = export_diary_csv([{"title": f.original_title or f.title, "year": f.year, "rating": u.rating,
                                  "watched_date": u.watched_date.isoformat() if u.watched_date else None,
                                  "rewatch": u.rewatch, "liked": u.liked} for f, u in rows])
        name = "claqueta-diario.csv"
    elif kind == "watchlist":
        rows = (db.query(Film, UserFilm).join(UserFilm, UserFilm.film_id == Film.id)
                .filter(UserFilm.profile_id == PROFILE, UserFilm.status.in_(("watchlist", "parked")),
                        UserFilm.source == "app").order_by(Film.title).all())
        data = export_watchlist_csv([{"title": f.original_title or f.title, "year": f.year} for f, _ in rows])
        name = "claqueta-pendientes.csv"
    else:
        raise HTTPException(404, "Exportación desconocida")
    return Response(content="﻿" + data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
