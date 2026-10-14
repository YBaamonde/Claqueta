"""Atributos «de sensación» de cada película (0‒1) y su estimación heurística.

Estos atributos son la base del motor: permiten emparejar mood, concentración, compañía
y riesgo de «tostón» sin depender del título. Tienen tres orígenes, de menor a mayor
fiabilidad: heurística (géneros, duración, año, votos) → LLM (enriquecimiento en segundo
plano) → curados a mano (semilla de demostración).
"""
from __future__ import annotations

from typing import Any, Mapping

from ..util import clamp

ATTR_KEYS = [
    "pace",        # 0 contemplativa · 1 trepidante
    "intensity",   # impacto emocional / físico
    "tension",     # suspense
    "humor",
    "warmth",      # calidez, «feel-good»
    "darkness",    # crudeza, temas oscuros
    "emotional",   # carga dramática, potencial de lágrima
    "complexity",  # exigencia cognitiva (trama, temas)
    "weirdness",   # surrealismo, rareza, formalismo
    "spectacle",   # escala visual, evasión
    "romance",
    "dated",       # riesgo de que hoy se sienta anticuada / tostón
    "access",      # facilidad para un público no cinéfilo
    "family",      # apta para ver en familia
    "rewatch",     # ganas de volver a verla
]

# Los que se usan para medir parecido entre películas (diversidad, mood reciente).
SIM_KEYS = ["pace", "intensity", "tension", "humor", "warmth", "darkness", "emotional",
            "complexity", "weirdness", "spectacle", "romance"]

_G = {  # priors por género (parciales)
    "Comedia": dict(humor=.8, warmth=.6, darkness=.15, tension=.2, intensity=.3, complexity=.25, pace=.6, access=.8, rewatch=.7),
    "Drama": dict(emotional=.7, humor=.2, pace=.4, intensity=.55, complexity=.5, spectacle=.25, rewatch=.35),
    "Romance": dict(romance=.85, warmth=.65, emotional=.6, tension=.2, humor=.4, darkness=.15, spectacle=.3),
    "Terror": dict(tension=.85, darkness=.8, intensity=.7, humor=.1, warmth=.1, pace=.55, family=.0, rewatch=.4),
    "Suspense": dict(tension=.8, pace=.6, complexity=.55, darkness=.55, intensity=.65, humor=.1),
    "Misterio": dict(tension=.65, complexity=.7, darkness=.5, pace=.45, humor=.15),
    "Crimen": dict(tension=.6, darkness=.65, intensity=.65, complexity=.55, humor=.2, warmth=.2),
    "Acción": dict(pace=.85, intensity=.75, spectacle=.8, tension=.6, complexity=.3, humor=.35, access=.85, rewatch=.6),
    "Aventura": dict(pace=.7, spectacle=.8, warmth=.55, humor=.4, complexity=.3, darkness=.25, access=.85, rewatch=.65),
    "Ciencia ficción": dict(spectacle=.75, complexity=.65, weirdness=.45, pace=.55, tension=.5, humor=.2),
    "Fantasía": dict(spectacle=.8, warmth=.55, weirdness=.45, pace=.55, complexity=.4, darkness=.3),
    "Animación": dict(family=.8, warmth=.7, spectacle=.65, humor=.55, darkness=.15, access=.85, rewatch=.75),
    "Familia": dict(family=.9, warmth=.8, humor=.55, darkness=.05, access=.9, complexity=.15, rewatch=.7),
    "Bélica": dict(intensity=.8, darkness=.7, emotional=.65, tension=.7, spectacle=.65, humor=.05, pace=.55),
    "Historia": dict(emotional=.55, complexity=.55, pace=.4, spectacle=.5, humor=.1),
    "Western": dict(pace=.5, tension=.55, spectacle=.6, darkness=.45, humor=.2, warmth=.25),
    "Música": dict(warmth=.65, emotional=.55, spectacle=.5, humor=.35, rewatch=.6),
    "Documental": dict(complexity=.6, pace=.4, humor=.15, spectacle=.2, access=.45, weirdness=.15),
}

_AGE_BASE = [(2005, .06), (1990, .13), (1970, .26), (1950, .45), (1930, .60), (0, .80)]


def _base_dated(year: int | None) -> float:
    if not year:
        return .25
    for y, v in _AGE_BASE:
        if year >= y:
            return v
    return .8


def heuristic_attrs(film: Any) -> dict[str, float]:
    """Estima los atributos a partir de metadatos genéricos. ``film`` es un Film o un dict."""
    g = lambda k, d=None: (film.get(k, d) if isinstance(film, Mapping) else getattr(film, k, d))  # noqa: E731
    genres: list[str] = list(g("genres") or [])
    year = g("year")
    runtime = g("runtime") or 105
    va, vc = g("vote_average") or 0, g("vote_count") or 0
    min_age = g("min_age")

    vals: dict[str, float] = {k: .5 for k in ATTR_KEYS}
    acc: dict[str, list[tuple[float, float]]] = {}
    for i, name in enumerate(genres[:4]):
        prior = _G.get(name)
        if not prior:
            continue
        w = 1.0 if i < 2 else .6
        for k, v in prior.items():
            acc.setdefault(k, []).append((w, v))
    for k, pairs in acc.items():
        tw = sum(w for w, _ in pairs)
        mean = sum(w * v for w, v in pairs) / tw
        blend = min(1.0, .45 + .3 * tw)  # más géneros coincidentes → más confianza
        vals[k] = .5 * (1 - blend) + mean * blend

    if runtime > 150:
        vals["pace"] -= .12
        vals["complexity"] += .05
    elif runtime < 92:
        vals["pace"] += .06
    if year and year < 1960:
        vals["pace"] -= .1

    # riesgo de «tostón»
    d = _base_dated(year)
    old = year is not None and year < 1980
    if "Comedia" in genres and old:
        d += .10
    if "Música" in genres and old:
        d += .06
    if old and any(x in genres for x in ("Suspense", "Terror", "Crimen", "Misterio")):
        d -= .09
    if runtime > 150:
        d += .07
    if vals["pace"] < .32:
        d += .08
    if va >= 8.0 and vc >= 3000:
        d -= .12  # las películas «supervivientes» suelen aguantar
    elif va and va < 6.6:
        d += .05
    vals["dated"] = clamp(d, .02, .95)

    # accesibilidad para público no cinéfilo
    lang = g("original_language")
    acc_v = .85 - .5 * vals["complexity"] - .35 * vals["weirdness"] + .1 * (vals["pace"] - .5) - .25 * vals["dated"]
    if lang and lang not in ("en", "es"):
        acc_v -= .08
    vals["access"] = clamp(acc_v, .05, .98)

    # familia
    if min_age is not None:
        fam = .95 if min_age <= 0 else .85 if min_age <= 7 else .6 if min_age <= 10 else .42 if min_age <= 12 else .12 if min_age <= 16 else .02
    else:
        fam = vals["family"] if "family" in acc else .35
        if any(x in genres for x in ("Terror", "Crimen", "Bélica", "Suspense")):
            fam = min(fam, .1)
    vals["family"] = clamp(fam * (1 - .6 * vals["darkness"]) if min_age is None else fam)

    vals["rewatch"] = clamp(.3 + .35 * vals["humor"] + .25 * vals["warmth"] + .2 * vals["spectacle"] - .25 * vals["darkness"])
    return {k: round(clamp(v), 3) for k, v in vals.items()}


def sanitize_attrs(raw: Mapping[str, Any], fallback: Mapping[str, float] | None = None) -> dict[str, Any]:
    """Valida/recorta atributos que vienen de un LLM o de un fichero externo."""
    out: dict[str, Any] = dict(fallback or {})
    for k in ATTR_KEYS:
        v = raw.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            v = float(v)
            if v > 1.0:  # escala 0‒100 o 0‒10
                v = v / 100 if v > 10 else v / 10
            out[k] = round(clamp(v), 3)
    notes = raw.get("notes")
    if isinstance(notes, str) and notes.strip():
        out["notes"] = notes.strip()[:220]
    tags = raw.get("tags")
    if isinstance(tags, list):
        out["tags"] = [str(t)[:24] for t in tags[:6]]
    return out
