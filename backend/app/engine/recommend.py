"""Motor de recomendación.

Flujo: candidatas (SQL) → puertas duras → puntuación por componentes → penalizaciones
multiplicativas (tiempo, anti-tostón, ajustes de sesión) → re-ranking MMR para diversidad.

Cada componente es un número en [0, 1) y se pesa con ``weights``; así se puede explicar *por qué*
una película está arriba y afinar el comportamiento sin tocar el código.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from .. import settings_store
from ..models import Film
from ..util import clamp, cosine, jaccard
from .attrs import SIM_KEYS, heuristic_attrs
from .context import ERA_RANGES, Context
from .feedback import Adj, derive_adjustments
from .moods import MOOD_BY_ID, mix_moods, mood_score
from .taste import Taste, build_taste, rec_seeds_for, taste_score
from .weights import get_weights

log = logging.getLogger("claqueta.engine")

SUBS_FREE_LANGS = {"es", "en", "xx", "zxx", "", None}


@dataclass
class Scored:
    film: Film
    score: float
    parts: dict[str, float]
    contrib: dict[str, float]
    aged_risk: float
    aged_eff: float
    aged_mult: float
    facts: dict[str, Any]
    user_status: str
    flags: list[str] = field(default_factory=list)


@dataclass
class RankResult:
    items: list[Scored]
    pool_size: int
    candidates: int
    adj: Adj
    ctx: Context
    relaxed: list[str]
    empty_reason: str | None = None


@dataclass
class Env:
    ctx: Context
    taste: Taste
    W: dict[str, float]
    adj: Adj
    now: datetime
    seerr_on: bool
    rec: dict[int, list[tuple[int, float]]]
    recent_centroid: dict[str, float] | None
    recent_genres: list[str]
    relax: int = 0


# ---------------------------------------------------------------------------
# Utilidades de película
# ---------------------------------------------------------------------------

def attrs_of(f: Film) -> dict[str, Any]:
    a = f.attrs or {}
    if "pace" not in a:
        return {**heuristic_attrs(f), **{k: v for k, v in a.items() if not isinstance(v, (int, float))}}
    return a


def quality(f: Film) -> float:
    v, r = f.vote_count or 0, f.vote_average or 0.0
    if v < 20:
        return .25
    m, c = 400.0, 6.3
    q = (v / (v + m)) * r + (m / (v + m)) * c
    return clamp((q - 5.6) / (8.2 - 5.6))


def streaming_ok(f: Film) -> bool:
    return bool((f.providers or {}).get("flatrate"))


def needs_subs(f: Film, subtitles_ok: bool) -> float:
    """Coste de atención por subtítulos / intertítulos (0‒0.5)."""
    lang = f.original_language
    if lang == "es":
        return 0.0
    if lang in ("xx", "zxx") or (f.year and f.year < 1930 and not lang):
        return .15  # cine mudo: intertítulos
    if lang == "en":
        return .06
    return .22 if subtitles_ok else .5


def era_ok(f: Film, eras: list[str]) -> bool:
    if not eras:
        return True
    if not f.year:
        return False
    return any(ERA_RANGES[e][0] <= f.year <= ERA_RANGES[e][1] for e in eras)


def film_sim(a: Film, b: Film) -> float:
    aa, bb = attrs_of(a), attrs_of(b)
    return .5 * jaccard(a.genres, b.genres) + .5 * max(0.0, cosine(aa, bb, SIM_KEYS))


def aged_label(risk: float) -> str:
    if risk < .22:
        return "Intemporal"
    if risk < .45:
        return "Aguanta bien"
    if risk < .68:
        return "Pide paciencia"
    return "Solo para completistas"


def focus_demand(f: Film, a: dict, subtitles_ok: bool) -> float:
    d = .55 * float(a.get("complexity", .5)) + .25 * float(a.get("weirdness", .3))
    slow = max(0.0, .42 - float(a.get("pace", .5)))
    d += .5 * slow
    d += needs_subs(f, subtitles_ok)
    if (f.runtime or 100) > 150:
        d += .08
    return clamp(d)


# ---------------------------------------------------------------------------
# Puertas duras
# ---------------------------------------------------------------------------

def gate_failures(f: Film, env: Env) -> list[str]:
    ctx, adj, taste = env.ctx, env.adj, env.taste
    out: list[str] = []
    a = attrs_of(f)
    st = taste.status.get(f.id, "none")
    if st == "never":
        out.append("never")
    if st == "watching":
        out.append("watching")
    if st == "watched" and not ctx.allow_seen:
        out.append("seen")
    if f.id in taste.snoozed:
        out.append("snoozed")
    if f.id in adj.excluded_ids:
        out.append("session")
    if not f.runtime:
        out.append("no_runtime")
    slack = 20 if env.relax >= 2 else 5
    if ctx.max_minutes and f.runtime and f.runtime > ctx.max_minutes + slack:
        out.append("too_long")
    if ctx.scope == "library" and not f.jellyfin_id:
        out.append("not_in_library")
    if ctx.scope == "streaming" and not (streaming_ok(f) or f.jellyfin_id):
        out.append("not_streaming")
    if not era_ok(f, ctx.eras):
        out.append("era")
    if ctx.genres_out and any(g in ctx.genres_out for g in f.genres):
        out.append("genre_out")
    if ctx.genres_in and not any(g in ctx.genres_in for g in f.genres):
        out.append("genre_in")
    # compañía
    if ctx.company == "peques":
        kid_genre = any(g in ("Animación", "Familia") for g in f.genres)
        ok = kid_genre and ((f.min_age is not None and f.min_age <= 7) or (
            f.min_age is None and float(a.get("family", 0)) >= .7))
        if not ok or any(g in ("Terror", "Crimen", "Bélica") for g in f.genres):
            out.append("company")
    elif ctx.company == "familia":
        ok = (f.min_age is not None and f.min_age <= 12) or (f.min_age is None and float(a.get("family", 0)) >= .4)
        if not ok:
            out.append("company")
    # ajustes duros de la sesión (se relajan si no quedan opciones)
    if env.relax == 0:
        if adj.pace_floor and float(a.get("pace", .5)) < adj.pace_floor:
            out.append("adj_pace")
        if float(a.get("darkness", .3)) > adj.darkness_max + .05 or float(a.get("intensity", .5)) > adj.intensity_max + .05:
            out.append("adj_dark")
        if float(a.get("weirdness", .3)) > adj.weirdness_max + .05:
            out.append("adj_weird")
        if adj.serious_min and max(float(a.get("emotional", .4)), float(a.get("complexity", .4))) < adj.serious_min - .05:
            out.append("adj_serious")
        if adj.people_out and (set(f.directors) | set(f.cast[:3])) & adj.people_out:
            out.append("adj_people")
    if not ctx.subtitles_ok and f.original_language not in SUBS_FREE_LANGS and env.relax < 1:
        out.append("subtitles")
    # suelo de calidad
    if env.relax < 2 and ctx.adventure < .8 and quality(f) < .12 and not (f.jellyfin_id or st in ("watchlist", "parked")):
        out.append("quality")
    return out


GATE_TEXT = {
    "never": "Descartada para siempre", "watching": "La estás viendo", "seen": "Ya la has visto",
    "snoozed": "Aparcada unos días", "session": "Ya la has descartado hoy", "no_runtime": "Sin duración conocida",
    "too_long": "Se pasa de tu tiempo", "not_in_library": "No está en tu biblioteca",
    "not_streaming": "No está en streaming ni en tu biblioteca", "era": "Fuera de las épocas elegidas",
    "genre_out": "Tiene un género que excluiste", "genre_in": "No es de los géneros elegidos",
    "company": "No apta para esta compañía", "adj_pace": "Más lenta de lo que querías",
    "adj_dark": "Más dura de lo que querías", "adj_weird": "Más rara de lo que querías",
    "adj_serious": "Más ligera de lo que querías", "adj_people": "Sale gente que has descartado",
    "subtitles": "Pide subtítulos", "quality": "Valoración baja",
}


# ---------------------------------------------------------------------------
# Puntuación
# ---------------------------------------------------------------------------

def company_fit(f: Film, a: dict, company: str) -> float:
    if company == "solo":
        return .6 + .15 * (float(a.get("complexity", .5)) + float(a.get("weirdness", .3)) - .8)
    tg = {
        "pareja": ({"romance": .6, "warmth": .6, "humor": .5, "darkness": .25, "intensity": .4},
                   {"romance": 1.0, "warmth": 1.0, "humor": .8, "darkness": 1.6, "intensity": 1.0}),
        "amigos": ({"pace": .7, "humor": .6, "spectacle": .65, "rewatch": .7, "complexity": .3, "access": .8},
                   {"pace": 1.0, "humor": 1.2, "spectacle": 1.0, "rewatch": .8, "complexity": 1.0, "access": 1.2}),
        "familia": ({"family": .85, "access": .85, "darkness": .15, "humor": .5, "warmth": .6},
                    {"family": 2.0, "access": 1.2, "darkness": 1.4, "humor": .8, "warmth": .8}),
        "peques": ({"family": .95, "pace": .6, "humor": .6, "darkness": .05, "complexity": .15},
                   {"family": 2.0, "pace": .8, "humor": .8, "darkness": 1.6, "complexity": 1.0}),
    }[company]
    targets, weights = tg
    num = den = 0.0
    for k, t in targets.items():
        w = weights.get(k, 1.0)
        num += w * abs(float(a.get(k, .5)) - t)
        den += w
    fit = 1 - num / den
    if company == "peques" and (f.runtime or 0) > 110:
        fit -= .15
    if company == "pareja" and (f.min_age or 0) >= 18:
        fit -= .1
    return clamp((fit - .4) / .5)


def score_film(f: Film, env: Env) -> Scored:
    ctx, taste, W, adj = env.ctx, env.taste, env.W, env.adj
    a = attrs_of(f)
    st = taste.status.get(f.id, "none")
    q = quality(f)
    ts, facts = taste_score(taste, f, env.rec.get(f.id))

    fam = []
    if f.genres:
        fam.append(max(taste.fam_genre.get(g, 0.0) for g in f.genres[:2]))
    fam.append(taste.fam_decade.get((f.year // 10) * 10, 0.0) if f.year else 0.0)
    fam.append(taste.fam_country.get(f.countries[0], 0.0) if f.countries else 0.0)
    novelty = 1 - sum(fam) / len(fam)
    adv = clamp(ctx.adventure + adj.adventure_delta + float(taste.adjust.get("adventure", 0.0)))
    taste_mix = (1 - adv) * ts + adv * (.45 * q + .35 * novelty + .20 * ts)

    mood_s = None
    if ctx.moods:
        mood_s = mix_moods([mood_score(a, f.genres, f.year, MOOD_BY_ID[m]) for m in ctx.moods])

    # tiempo
    time_mult = 1.0
    if ctx.max_minutes and f.runtime:
        if f.runtime > ctx.max_minutes:
            time_mult = .82
        elif f.runtime < .45 * ctx.max_minutes:
            time_mult = .94
    elif f.runtime and f.runtime > 165 and ctx.focus < 3:
        time_mult = .9

    # concentración
    demand = focus_demand(f, a, ctx.subtitles_ok)
    cap = (ctx.focus - 1) / 4 + .18
    focus_fit = 1 - clamp((demand - cap) / .5)

    # compañía
    comp = clamp(company_fit(f, a, ctx.company))

    # variedad respecto a lo visto recientemente
    var = 1.0
    if env.recent_centroid:
        sim = max(0.0, cosine(a, env.recent_centroid, SIM_KEYS))
        var = 1 - clamp(sim * .9)
    if env.recent_genres and f.genres and f.genres[0] in env.recent_genres:
        var = max(0.0, var - .2)
    if mood_s is not None and mood_s > .75:   # si pides expresamente «miedo», no te castigo por haber visto terror hace poco
        var = max(var, .55)

    # disponibilidad
    if f.jellyfin_id:
        avail = 1.0
    elif streaming_ok(f):
        avail = .55
    elif env.seerr_on:
        avail = .25
    else:
        avail = .1

    # anti-tostón
    risk = float(a.get("dated", .2))
    eff = risk * (1 - .55 * taste.old_tolerance)
    if any(e in ("edad_oro", "sesenta_setenta") for e in ctx.eras):
        eff *= .65
    if ctx.focus >= 4:
        eff *= .85
    strength = W["anti_toston"] if ctx.anti_toston else W["toston_off"]
    strength = clamp(strength + adj.aged_boost, 0.0, .97)
    aged_mult = 1 - strength * eff

    # penalizaciones blandas por feedback de sesión
    soft = 1.0
    for g in f.genres[:3]:
        soft *= 1 - min(.5, adj.genre_pen.get(g, 0.0)) * (1.0 if g == f.genres[0] else .6)
    if f.year:
        soft *= 1 - min(.4, adj.decade_pen.get((f.year // 10) * 10, 0.0))
    for vec, w in adj.avoid_vectors:
        sim = cosine(a, vec, SIM_KEYS)
        if sim > .2:
            soft *= 1 - min(.45, w * sim)
    if env.relax >= 1 and adj.hard_active():  # los límites duros pasan a ser blandos
        soft *= .85

    parts = dict(taste=taste_mix, quality=q, focus=focus_fit, company=comp, variety=var, availability=avail)
    wts = dict(taste=W["taste"], quality=W["quality"], focus=W["focus"], company=W["company"],
               variety=W["variety"] + adj.variety_boost * .5, availability=W["availability"])
    if mood_s is not None:
        parts["mood"] = mood_s
        wts["mood"] = W["mood"]
    tot = sum(wts.values()) or 1.0
    base = sum(wts[k] * parts[k] for k in wts) / tot
    contrib = {k: wts[k] * (parts[k] - .5) / tot for k in wts}

    intent = .04 if st == "parked" else .025 if st == "watchlist" else 0.0
    if intent:
        facts["intent"] = st
    score = base * time_mult * aged_mult * soft + intent
    parts.update(time=time_mult, aged=aged_mult, novelty=novelty)
    return Scored(f, score, parts, contrib, risk, eff, aged_mult, facts, st)


def diversify(items: list[Scored], k: int, lam: float) -> list[Scored]:
    """MMR: evita que el carrusel sean cinco clones de la misma película."""
    pool = items[:80]
    chosen: list[Scored] = []
    while pool and len(chosen) < k:
        best, best_val = None, -1e9
        for it in pool:
            pen = max((film_sim(it.film, c.film) for c in chosen), default=0.0)
            val = it.score - lam * pen
            if val > best_val:
                best, best_val = it, val
        assert best is not None
        chosen.append(best)
        pool.remove(best)
    return chosen


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def _build_env(db: Session, profile_id: int, ctx: Context, events: list[dict], now: datetime) -> Env:
    taste = build_taste(db, profile_id)
    ids = {e["film_id"] for e in events}
    films_ev = {f.id: f for f in db.query(Film).filter(Film.id.in_(ids))} if ids else {}
    adj = derive_adjustments(events, films_ev, ctx.max_minutes)
    eff = ctx.model_copy(update={
        "max_minutes": adj.max_minutes,
        "subtitles_ok": ctx.subtitles_ok and not adj.subtitles_off,
    })
    rec = rec_seeds_for(db, taste)
    centroid = None
    recent_genres: list[str] = []
    if taste.recent:
        tw = sum(w for _, _, w in taste.recent)
        centroid = {k: sum(float(a.get(k, .5)) * w for a, _, w in taste.recent) / tw for k in SIM_KEYS}
        recent_genres = [gs[0] for _, gs, w in sorted(taste.recent, key=lambda x: -x[2])[:3] if gs]
    return Env(eff, taste, get_weights(), adj, now, bool(settings_store.get("jellyseerr_url")), rec, centroid,
               recent_genres)


def rank(db: Session, profile_id: int, ctx: Context, events: list[dict] | None = None, limit: int = 10,
         now: datetime | None = None) -> RankResult:
    now = now or datetime.now()
    events = events or []
    env = _build_env(db, profile_id, ctx, events, now)
    films = db.query(Film).filter(Film.runtime.isnot(None), Film.runtime > 0).all()
    relaxed: list[str] = []
    cands: list[Film] = []
    for relax in (0, 1, 2):
        env.relax = relax
        cands = [f for f in films if not gate_failures(f, env)]
        if len(cands) >= 6 or relax == 2:
            if relax == 1:
                relaxed.append("He suavizado los límites que habías ido marcando para no quedarme sin opciones")
            elif relax == 2:
                relaxed.append("Tuve que ampliar un poco el tiempo y bajar el listón de calidad")
            break
    scored = sorted((score_film(f, env) for f in cands), key=lambda s: -s.score)
    picked = diversify(scored, limit, env.W["diversity"]) if scored else []
    empty = None
    if not picked:
        empty = "no_films" if not films else "no_match"
    return RankResult(picked, len(films), len(cands), env.adj, env.ctx, relaxed, empty)


def evaluate(db: Session, profile_id: int, film: Film, ctx: Context, now: datetime | None = None) -> Scored:
    """Veredicto para una película concreta: puntúa ignorando las puertas, pero las lista como avisos."""
    env = _build_env(db, profile_id, ctx, [], now or datetime.now())
    s = score_film(film, env)
    s.flags = [GATE_TEXT[g] for g in gate_failures(film, env) if g in GATE_TEXT and g != "session"]
    return s
