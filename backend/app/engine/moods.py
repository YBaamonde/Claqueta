"""Catálogo de estados de ánimo.

Cada mood define un *vector objetivo* sobre los atributos de la película, cuánto pesa cada
atributo y qué géneros suman o restan. Añadir un mood nuevo = añadir una entrada aquí; el
frontend lo recibe por ``/api/bootstrap`` y lo pinta solo.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from ..util import clamp


@dataclass(frozen=True)
class Mood:
    id: str
    label: str
    emoji: str
    blurb: str
    colors: tuple[str, str]
    targets: Mapping[str, float]
    weights: Mapping[str, float] = field(default_factory=dict)
    genre_boost: Mapping[str, float] = field(default_factory=dict)
    year_pref: tuple[int, int] | None = None  # (desde, hasta) con bonus suave


MOODS: list[Mood] = [
    Mood("reir", "Reírme", "😄", "Que me duelan los mofletes", ("#f6b73c", "#ef6a3a"),
         dict(humor=.85, darkness=.15, warmth=.6, tension=.2), dict(humor=3.6, darkness=1.2),
         {"Comedia": .25, "Animación": .05, "Terror": -.2, "Bélica": -.12, "Suspense": -.08}),
    Mood("llorar", "Llorar a gusto", "😢", "Catarsis con pañuelos", ("#5b8def", "#7b5be0"),
         dict(emotional=.9, intensity=.65, humor=.25, warmth=.5), dict(emotional=2.2, humor=.8),
         {"Drama": .15, "Romance": .1, "Comedia": -.1, "Terror": -.15, "Acción": -.1}),
    Mood("adrenalina", "Adrenalina", "⚡", "Pulso a 120 y sin respirar", ("#ff5a4e", "#ffb02e"),
         dict(pace=.9, tension=.7, spectacle=.8, intensity=.8), dict(pace=1.6, spectacle=1.2),
         {"Acción": .25, "Aventura": .1, "Suspense": .12, "Ciencia ficción": .08, "Drama": -.12, "Romance": -.1}),
    Mood("pensar", "Pensar y darle vueltas", "🧠", "Que me dure el debate", ("#4bc0b0", "#2e7bd6"),
         dict(complexity=.85, weirdness=.5, emotional=.5, pace=.45), dict(complexity=2.2),
         {"Misterio": .1, "Ciencia ficción": .1, "Drama": .06, "Familia": -.15, "Comedia": -.05}),
    Mood("evadirme", "Evadirme del mundo", "🚀", "Otro universo, por favor", ("#9b6bff", "#2fb7ff"),
         dict(spectacle=.85, complexity=.35, darkness=.3, warmth=.55), dict(spectacle=2.0),
         {"Aventura": .15, "Fantasía": .18, "Ciencia ficción": .14, "Animación": .1, "Documental": -.2}),
    Mood("miedo", "Pasar miedo", "😱", "Luces fuera", ("#c0233a", "#3b1a4a"),
         dict(tension=.85, darkness=.8, intensity=.75, humor=.1), dict(tension=1.8, darkness=1.4),
         {"Terror": .3, "Suspense": .15, "Comedia": -.15, "Familia": -.3, "Animación": -.1}),
    Mood("comfort", "Algo reconfortante", "🛋️", "Manta, sofá y cero estrés", ("#f2a65a", "#e56b6f"),
         dict(warmth=.9, intensity=.2, darkness=.1, humor=.5, access=.85), dict(warmth=2.0, darkness=1.5, intensity=1.2),
         {"Comedia": .12, "Romance": .1, "Familia": .1, "Animación": .08, "Música": .08, "Terror": -.25, "Bélica": -.2}),
    Mood("romantico", "Romántico", "💘", "Mariposas incluidas", ("#ff7aa8", "#c23b7a"),
         dict(romance=.9, warmth=.7, emotional=.55, darkness=.15), dict(romance=2.4),
         {"Romance": .3, "Terror": -.25, "Bélica": -.2, "Acción": -.08}),
    Mood("inspirador", "Inspirador", "🌅", "Salir con ganas de comerme el mundo", ("#ffb347", "#ff6b81"),
         dict(warmth=.7, emotional=.65, intensity=.5, darkness=.2), dict(warmth=1.4, emotional=1.4, darkness=1.2),
         {"Drama": .08, "Historia": .08, "Música": .1, "Terror": -.2}),
    Mood("intriga", "Intriga y misterio", "🕵️", "Ir atando cabos", ("#3d5a80", "#98c1d9"),
         dict(tension=.65, complexity=.65, darkness=.5, pace=.5), dict(tension=1.4, complexity=1.6),
         {"Misterio": .25, "Crimen": .18, "Suspense": .2, "Comedia": -.1, "Familia": -.2}),
    Mood("raro", "Algo raro, de autor", "🌀", "Sorpréndeme con una locura", ("#7f5af0", "#2cb67d"),
         dict(weirdness=.85, complexity=.65, access=.3), dict(weirdness=2.4, complexity=1.0),
         {"Familia": -.2, "Acción": -.08}),
    Mood("nostalgia", "Nostalgia de siempre", "📼", "Como las pelis de antes", ("#d4a373", "#8d5a97"),
         dict(warmth=.65, access=.75, dated=.2), dict(warmth=1.4, access=1.2), {}, (1975, 2003)),
]

MOOD_IDS = {m.id for m in MOODS}
MOOD_BY_ID = {m.id: m for m in MOODS}


def mood_score(attrs: Mapping[str, float], genres: list[str], year: int | None, mood: Mood) -> float:
    num = den = 0.0
    for k, t in mood.targets.items():
        w = mood.weights.get(k, 1.0)
        num += w * abs(float(attrs.get(k, .5)) - t)
        den += w
    s = 1.0 - (num / den if den else 0.5)
    s += clamp(sum(mood.genre_boost.get(g, 0.0) for g in genres), -.3, .3)
    if mood.year_pref and year:
        lo, hi = mood.year_pref
        if lo <= year <= hi:
            s += .08
        else:
            s -= min(.15, .004 * min(abs(year - lo), abs(year - hi)))
    # curva convexa: un «casi» encaja bastante peor que un encaje claro (Oppenheimer no es «pasar miedo»)
    return clamp((s - .5) / .45) ** 1.9


def mix_moods(scores: list[float]) -> float:
    if not scores:
        return 0.0
    if len(scores) == 1:
        return scores[0]
    scores = sorted(scores, reverse=True)
    return .65 * scores[0] + .35 * (sum(scores[1:]) / len(scores[1:]))
