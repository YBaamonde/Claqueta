"""Perfil de gusto: se calcula a partir de lo que has visto/valorado y de tus descartes.

Todo son afinidades en [-1, 1] con *shrinkage* (pocas muestras → cerca de 0), de modo que
un único 5★ no convierte a un director en tu favorito, y el sistema arranca razonable aun
sin historial (cold start).
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Film, FilmEdge, Profile, UserFilm
from ..util import clamp, utcnow
from .attrs import ATTR_KEYS


def decade_of(year: int | None) -> int | None:
    return (year // 10) * 10 if year else None


@dataclass
class Taste:
    n_rated: int = 0
    n_watched: int = 0
    mean_rating: float = 3.4
    genre: dict[str, float] = field(default_factory=dict)
    director: dict[str, float] = field(default_factory=dict)
    cast: dict[str, float] = field(default_factory=dict)
    decade: dict[int, float] = field(default_factory=dict)
    country: dict[str, float] = field(default_factory=dict)
    attr_tilt: dict[str, float] = field(default_factory=dict)
    old_tolerance: float = 0.4
    old_seen: int = 0
    fam_genre: dict[str, float] = field(default_factory=dict)
    fam_decade: dict[int, float] = field(default_factory=dict)
    fam_country: dict[str, float] = field(default_factory=dict)
    status: dict[int, str] = field(default_factory=dict)
    rating: dict[int, float] = field(default_factory=dict)
    snoozed: set[int] = field(default_factory=set)
    recent: list[tuple[dict, list[str], float]] = field(default_factory=list)  # (attrs, géneros, peso)
    liked_seeds: dict[int, float] = field(default_factory=dict)                  # film_id → rating ≥ 4
    genre_stats: dict[str, tuple[int, float]] = field(default_factory=dict)
    director_stats: dict[str, tuple[int, float]] = field(default_factory=dict)
    adjust: dict[str, Any] = field(default_factory=dict)
    runtime_median: int | None = None
    version: str = ""


_cache: dict[int, tuple[str, Taste]] = {}


def invalidate(profile_id: int | None = None) -> None:
    if profile_id is None:
        _cache.clear()
    else:
        _cache.pop(profile_id, None)


def _signal(uf: UserFilm, mean: float) -> tuple[float, float]:
    """(señal, peso) de una fila de usuario. Señal en ~[-1.7, 1.5]."""
    if uf.status == "never":
        return -.8, .5
    if uf.status in ("watchlist", "parked"):
        return .18, .5
    if uf.status in ("watched", "watching"):
        if uf.rating is not None:
            s = (uf.rating - mean) / 1.5
            if uf.liked:
                s += .3
            if uf.rewatch:
                s += .2
            return s, 1.0
        return (.35 if uf.liked else .1), .45
    return 0.0, 0.0


def build_taste(db: Session, profile_id: int = 1) -> Taste:
    profile = db.get(Profile, profile_id)
    adjust = (profile.taste_adjust if profile else {}) or {}
    cnt, last = db.query(func.count(UserFilm.id), func.max(UserFilm.updated_at)).filter(
        UserFilm.profile_id == profile_id).one()
    version = f"{cnt}:{last}:{hash(str(sorted(adjust.items(), key=str)))}"
    hit = _cache.get(profile_id)
    if hit and hit[0] == version:
        return hit[1]

    rows = (db.query(UserFilm, Film).join(Film, Film.id == UserFilm.film_id)
            .filter(UserFilm.profile_id == profile_id).all())
    t = Taste(adjust=adjust, version=version)
    rated = [uf.rating for uf, _ in rows if uf.rating is not None and uf.status in ("watched", "watching")]
    t.n_rated = len(rated)
    t.mean_rating = sum(rated) / len(rated) if rated else 3.4

    now = utcnow()
    today = now.date()
    dims = ("genre", "director", "cast", "decade", "country")
    num: dict[str, dict] = {k: defaultdict(float) for k in dims}
    den: dict[str, dict] = {k: defaultdict(float) for k in dims}
    gstat: dict[str, list[float]] = defaultdict(list)
    dstat: dict[str, list[float]] = defaultdict(list)
    fam_g: dict[str, int] = defaultdict(int)
    fam_d: dict[int, int] = defaultdict(int)
    fam_c: dict[str, int] = defaultdict(int)
    tilt_pos: dict[str, float] = defaultdict(float)
    tilt_all: dict[str, float] = defaultdict(float)
    wpos = wall = 0.0
    old_r: list[float] = []
    new_r: list[float] = []
    runtimes: list[int] = []

    for uf, f in rows:
        t.status[f.id] = uf.status
        if uf.rating is not None:
            t.rating[f.id] = uf.rating
        if uf.snoozed_until and uf.snoozed_until > now:
            t.snoozed.add(f.id)
        sig, w = _signal(uf, t.mean_rating)
        if w <= 0:
            continue
        ref = uf.watched_date or uf.created_at.date()
        age = max(0, (today - ref).days) if isinstance(ref, date) else 0
        w *= .55 + .45 * math.exp(-age / 900)

        if uf.status in ("watched", "watching"):
            t.n_watched += 1
            if f.runtime:
                runtimes.append(f.runtime)
            for g in f.genres[:3]:
                fam_g[g] += 1
            dec = decade_of(f.year)
            if dec:
                fam_d[dec] += 1
            if f.countries:
                fam_c[f.countries[0]] += 1
            if uf.rating is not None:
                for g in f.genres[:3]:
                    gstat[g].append(uf.rating)
                for d in f.directors[:2]:
                    dstat[d].append(uf.rating)
                if f.year and f.year < 1975:
                    old_r.append(uf.rating)
                elif f.year and f.year >= 1990:
                    new_r.append(uf.rating)
                if uf.rating >= 4:
                    t.liked_seeds[f.id] = uf.rating
            if uf.watched_date and age <= 24 and f.attrs:
                t.recent.append((f.attrs, list(f.genres), math.exp(-age / 9)))
            if f.year and f.year < 1975:
                t.old_seen += 1

        # acumula afinidades
        for i, g in enumerate(f.genres[:4]):
            ww = w * (1.0 if i < 2 else .6)
            num["genre"][g] += sig * ww
            den["genre"][g] += ww
        for d in f.directors[:2]:
            num["director"][d] += sig * w
            den["director"][d] += w
        for i, a in enumerate(f.cast[:3]):
            ww = w * (1.0 if i == 0 else .7)
            num["cast"][a] += sig * ww
            den["cast"][a] += ww
        dec = decade_of(f.year)
        if dec:
            num["decade"][dec] += sig * w
            den["decade"][dec] += w
        if f.countries:
            num["country"][f.countries[0]] += sig * w
            den["country"][f.countries[0]] += w

        if f.attrs and uf.rating is not None and uf.status in ("watched", "watching"):
            wall += w
            for k in ATTR_KEYS:
                v = f.attrs.get(k)
                if isinstance(v, (int, float)):
                    tilt_all[k] += w * v
            if uf.rating >= 4 or uf.liked:
                wpos += w
                for k in ATTR_KEYS:
                    v = f.attrs.get(k)
                    if isinstance(v, (int, float)):
                        tilt_pos[k] += w * v

    shrink = {"genre": 3.0, "director": 2.0, "cast": 3.0, "decade": 5.0, "country": 6.0}
    for dim, target in (("genre", t.genre), ("director", t.director), ("cast", t.cast),
                        ("decade", t.decade), ("country", t.country)):
        for key, n in num[dim].items():
            target[key] = clamp(n / (den[dim][key] + shrink[dim]), -1.0, 1.0)

    # ajustes derivados del feedback (descartes, aceptaciones)
    for g, dv in (adjust.get("genre") or {}).items():
        t.genre[g] = clamp(t.genre.get(g, 0.0) + float(dv), -1.0, 1.0)
    for p, dv in (adjust.get("people") or {}).items():
        t.director[p] = clamp(t.director.get(p, 0.0) + float(dv), -1.0, 1.0)
        t.cast[p] = clamp(t.cast.get(p, 0.0) + float(dv), -1.0, 1.0)

    if wpos > 0 and wall > 0:
        shrink_t = t.n_rated / (t.n_rated + 8.0)
        for k in ATTR_KEYS:
            diff = tilt_pos[k] / wpos - tilt_all[k] / wall
            t.attr_tilt[k] = clamp(diff * 2.5 * shrink_t, -1.0, 1.0)

    # tolerancia a clásicos (¿te gustan las viejas tanto como las nuevas?)
    prior = .4
    if len(old_r) >= 3 and new_r:
        gap = sum(old_r) / len(old_r) - sum(new_r) / len(new_r)
        observed = clamp(.5 + gap / 2.0, .1, .95)
        wgt = len(old_r) / (len(old_r) + 4.0)
        t.old_tolerance = prior * (1 - wgt) + observed * wgt
    else:
        t.old_tolerance = prior
    t.old_tolerance = clamp(t.old_tolerance + float(adjust.get("old_tol", 0.0)), .05, .98)

    def _norm(d: dict) -> dict:
        m = max(d.values()) if d else 1
        return {k: v / m for k, v in d.items()}

    t.fam_genre, t.fam_decade, t.fam_country = _norm(fam_g), _norm(fam_d), _norm(fam_c)
    t.genre_stats = {g: (len(v), sum(v) / len(v)) for g, v in gstat.items()}
    t.director_stats = {d: (len(v), sum(v) / len(v)) for d, v in dstat.items()}
    if runtimes:
        runtimes.sort()
        t.runtime_median = runtimes[len(runtimes) // 2]
    _cache[profile_id] = (version, t)
    return t


def rec_seeds_for(db: Session, taste: Taste) -> dict[int, list[tuple[int, float]]]:
    """Para cada película candidata, qué títulos que valoraste ≥4★ llevan a ella (TMDB recs)."""
    if not taste.liked_seeds:
        return {}
    out: dict[int, list[tuple[int, float]]] = defaultdict(list)
    seeds = list(taste.liked_seeds)
    for i in range(0, len(seeds), 400):
        chunk = seeds[i:i + 400]
        for e in db.query(FilmEdge).filter(FilmEdge.src_id.in_(chunk)).all():
            out[e.dst_id].append((e.src_id, taste.liked_seeds[e.src_id]))
    return out


def taste_score(t: Taste, f: Film, rec: list[tuple[int, float]] | None = None) -> tuple[float, dict]:
    """Devuelve (0‒1, hechos para explicar). 0.5 = neutro."""
    facts: dict[str, Any] = {}
    if t.n_watched < 3:
        return .5, facts
    gs = [(t.genre.get(g, 0.0), g) for g in f.genres[:4]]
    g_val = 0.0
    if gs:
        wsum = sum(1.0 if i < 2 else .6 for i in range(len(gs)))
        g_val = sum((1.0 if i < 2 else .6) * v for i, (v, _) in enumerate(gs)) / wsum
        best = max(gs, key=lambda x: x[0])
        if best[0] > .12:
            n, avg = t.genre_stats.get(best[1], (0, 0.0))
            facts["best_genre"] = (best[1], best[0], n, avg)
    d_vals = [(t.director.get(d, 0.0), d) for d in f.directors[:2]]
    d_val = max(d_vals, key=lambda x: abs(x[0]))[0] if d_vals else 0.0
    if d_vals:
        dv, dn = max(d_vals, key=lambda x: x[0])
        if dv > .12 and dn in t.director_stats:
            facts["director"] = (dn, *t.director_stats[dn])
    c_vals = [t.cast.get(a, 0.0) for a in f.cast[:3]]
    c_val = sum(c_vals) / len(c_vals) if c_vals else 0.0
    dec_val = t.decade.get(decade_of(f.year) or 0, 0.0)
    ctry_val = t.country.get(f.countries[0], 0.0) if f.countries else 0.0
    tilt = 0.0
    if t.attr_tilt and f.attrs:
        tw = sum(abs(v) for v in t.attr_tilt.values()) or 1.0
        tilt = sum(v * (float(f.attrs.get(k, .5)) - .5) * 2 for k, v in t.attr_tilt.items()) / tw
    raw = .34 * g_val + .20 * d_val + .08 * c_val + .10 * dec_val + .04 * ctry_val + .24 * tilt
    if rec:
        boost = min(.25, sum((r - 3.5) / 1.5 for _, r in rec) * .1)
        raw += boost
        facts["rec_from"] = [sid for sid, _ in sorted(rec, key=lambda x: -x[1])[:2]]
    shrink = t.n_watched / (t.n_watched + 6.0)
    raw *= shrink
    return 1 / (1 + math.exp(-2.6 * raw)), facts
