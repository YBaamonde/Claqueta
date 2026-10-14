"""Descartes con motivo → aprendizaje.

Dos escalas de tiempo:
* **Sesión**: cada motivo ajusta al instante lo que se te sugiere a continuación (p. ej. «muy
  larga» baja el tope de duración por debajo de esa película). Se deriva siempre de la lista
  de eventos de la sesión, así que *deshacer* es simplemente quitar el último evento.
* **Largo plazo**: el log de ``FeedbackEvent`` se reduce periódicamente a pequeños ajustes de
  gusto (``Profile.taste_adjust``) con decaimiento exponencial; nunca pisa tus valoraciones.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from ..models import FeedbackEvent, Film, Profile, RecoSession, UserFilm
from ..util import clamp, utcnow
from . import taste as taste_mod

# code → (etiqueta, emoji, ayuda). El orden es el orden «por defecto» en la interfaz.
REASONS: list[dict[str, str]] = [
    dict(code="too_long", label="Muy larga", emoji="⏱️", hint="Bajo el tope de duración"),
    dict(code="too_slow", label="Muy lenta", emoji="🐌", hint="Busco más ritmo"),
    dict(code="too_dated", label="Pinta a tostón", emoji="🕰️", hint="Parece que ha envejecido mal"),
    dict(code="not_mood", label="No es lo que me apetece", emoji="🎭", hint="Cambio de aires"),
    dict(code="too_heavy", label="Demasiado dura", emoji="🌑", hint="Menos oscuridad"),
    dict(code="too_light", label="Demasiado ligera", emoji="🎈", hint="Algo con más fondo"),
    dict(code="too_weird", label="Demasiado rara", emoji="🌀", hint="Algo más convencional"),
    dict(code="too_known", label="Demasiado típica", emoji="🔁", hint="Sorpréndeme más"),
    dict(code="genre_no", label="No me va ese género", emoji="🚫", hint="Menos de este género"),
    dict(code="people_no", label="Director/reparto no", emoji="👤", hint="Evita a esta gente"),
    dict(code="subtitles", label="Hoy sin subtítulos", emoji="💬", hint="Solo en mi idioma"),
    dict(code="similar_recent", label="Como lo último que vi", emoji="🪞", hint="Más variedad"),
    dict(code="seen", label="Ya la vi", emoji="✅", hint="La marco como vista"),
    dict(code="later", label="Otro día", emoji="💤", hint="Aparcarla una semana"),
    dict(code="never", label="Nunca", emoji="⛔", hint="No volver a sugerirla"),
]
REASON_CODES = {r["code"] for r in REASONS}
SERIOUS_KEYS = ("emotional", "complexity")


@dataclass
class Adj:
    """Ajustes efectivos de una sesión, derivados de sus eventos."""

    max_minutes: int | None = None
    pace_floor: float = 0.0
    darkness_max: float = 1.0
    intensity_max: float = 1.0
    weirdness_max: float = 1.0
    serious_min: float = 0.0
    aged_boost: float = 0.0
    variety_boost: float = 0.0
    adventure_delta: float = 0.0
    subtitles_off: bool = False
    genre_pen: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    decade_pen: dict[int, float] = field(default_factory=lambda: defaultdict(float))
    people_out: set[str] = field(default_factory=set)
    avoid_vectors: list[tuple[dict, float]] = field(default_factory=list)
    excluded_ids: set[int] = field(default_factory=set)
    summary: list[str] = field(default_factory=list)

    def hard_active(self) -> bool:
        return (self.pace_floor > 0 or self.darkness_max < 1 or self.intensity_max < 1 or self.weirdness_max < 1
                or self.serious_min > 0 or bool(self.people_out))


def derive_adjustments(events: list[dict], films: dict[int, Film], base_max_minutes: int | None) -> Adj:
    adj = Adj(max_minutes=base_max_minutes)
    for ev in events:
        fid = ev.get("film_id")
        f = films.get(fid)
        adj.excluded_ids.add(fid)
        if ev.get("action") != "dismiss" or not f:
            continue
        a = f.attrs or {}
        r = ev.get("reason")
        if r == "too_long":
            cap = max(60, (f.runtime or 120) - 8)
            adj.max_minutes = min(adj.max_minutes or 999, cap)
            adj.summary.append(f"Tope de duración: {adj.max_minutes} min")
        elif r == "too_slow":
            adj.pace_floor = max(adj.pace_floor, min(.85, float(a.get("pace", .4)) + .08))
            adj.summary.append("Más ritmo")
        elif r == "too_dated":
            adj.aged_boost = min(.3, adj.aged_boost + .12)
            if f.year:
                adj.decade_pen[(f.year // 10) * 10] += .12
            adj.summary.append("Menos riesgo de tostón")
        elif r == "not_mood":
            adj.avoid_vectors.append(({k: float(a.get(k, .5)) for k in a if isinstance(a.get(k), (int, float))}, .30))
            adj.summary.append("Otro tipo de película")
        elif r == "too_heavy":
            adj.darkness_max = min(adj.darkness_max, max(.15, float(a.get("darkness", .6)) - .08))
            adj.intensity_max = min(adj.intensity_max, max(.3, float(a.get("intensity", .7)) - .05))
            adj.summary.append("Menos oscuridad")
        elif r == "too_light":
            adj.serious_min = max(adj.serious_min, min(.8, max(float(a.get(k, .4)) for k in SERIOUS_KEYS) + .08))
            adj.summary.append("Algo con más fondo")
        elif r == "too_weird":
            adj.weirdness_max = min(adj.weirdness_max, max(.15, float(a.get("weirdness", .5)) - .1))
            adj.summary.append("Más convencional")
        elif r == "too_known":
            adj.adventure_delta = min(.4, adj.adventure_delta + .15)
            adj.summary.append("Más sorpresa")
        elif r == "genre_no":
            for g in f.genres[:2]:
                adj.genre_pen[g] = min(.6, adj.genre_pen[g] + .28)
            adj.summary.append("Menos " + ", ".join(f.genres[:2]).lower())
        elif r == "people_no":
            for p in (f.directors[:1] + f.cast[:1]):
                adj.people_out.add(p)
            adj.summary.append("Sin " + ", ".join((f.directors[:1] + f.cast[:1])))
        elif r == "subtitles":
            adj.subtitles_off = True
            adj.summary.append("Sin subtítulos")
        elif r == "similar_recent":
            adj.variety_boost = min(.3, adj.variety_boost + .12)
            for g in f.genres[:1]:
                adj.genre_pen[g] = min(.6, adj.genre_pen[g] + .12)
            adj.summary.append("Más variedad")
    adj.summary = list(dict.fromkeys(adj.summary))  # sin repetidos, conservando el orden
    return adj


# ---------------------------------------------------------------------------
# Persistencia de eventos
# ---------------------------------------------------------------------------

def _user_row(db: Session, profile_id: int, film_id: int) -> UserFilm:
    row = db.query(UserFilm).filter_by(profile_id=profile_id, film_id=film_id).one_or_none()
    if row is None:
        row = UserFilm(profile_id=profile_id, film_id=film_id, status="none", source="app")
        db.add(row)
        db.flush()
    return row


def record_event(db: Session, session: RecoSession, film: Film, action: str, reason: str | None) -> str:
    """Aplica un evento del usuario. Devuelve el texto del «toast»."""
    if action == "dismiss" and reason not in REASON_CODES:
        reason = None
    ev = {"film_id": film.id, "action": action, "reason": reason, "ts": utcnow().isoformat()}
    session.events = [*session.events, ev]
    db.add(FeedbackEvent(profile_id=session.profile_id, session_id=session.id, film_id=film.id,
                         action=action, reason=reason, context=session.context))
    row = _user_row(db, session.profile_id, film.id)
    toast = ""
    if action == "save":
        if row.status not in ("watched",):
            row.status = "parked"
        toast = f"«{film.title}» guardada en Pendientes"
    elif action == "accept":
        row.status = "watching"
        row.started_at = utcnow()
        toast = f"¡Buena sesión! «{film.title}» marcada como «viéndola»"
    elif action == "dismiss":
        label = next((r["label"] for r in REASONS if r["code"] == reason), "Descartada")
        if reason == "seen":
            row.status = "watched"
            toast = f"«{film.title}» marcada como vista"
        elif reason == "never":
            row.status = "never"
            toast = f"No volverá a salir «{film.title}»"
        elif reason == "later":
            row.snoozed_until = utcnow() + timedelta(days=7)
            toast = f"«{film.title}» vuelve en una semana"
        else:
            toast = f"Descartada · {label}"
    db.flush()
    taste_mod.invalidate(session.profile_id)
    return toast


def undo_last(db: Session, session: RecoSession) -> Film | None:
    if not session.events:
        return None
    ev = session.events[-1]
    session.events = session.events[:-1]
    film = db.get(Film, ev["film_id"])
    last = (db.query(FeedbackEvent)
            .filter_by(session_id=session.id, film_id=ev["film_id"], undone=False)
            .order_by(FeedbackEvent.id.desc()).first())
    if last:
        last.undone = True
    row = db.query(UserFilm).filter_by(profile_id=session.profile_id, film_id=ev["film_id"]).one_or_none()
    if row:
        if ev["action"] == "save" and row.status == "parked":
            row.status = "none"
        elif ev["action"] == "accept" and row.status == "watching":
            row.status, row.started_at = "none", None
        elif ev["action"] == "dismiss":
            if ev.get("reason") == "seen" and row.status == "watched" and row.rating is None:
                row.status = "none"
            elif ev.get("reason") == "never" and row.status == "never":
                row.status = "none"
            elif ev.get("reason") == "later":
                row.snoozed_until = None
    db.flush()
    taste_mod.invalidate(session.profile_id)
    return film


# ---------------------------------------------------------------------------
# Aprendizaje a largo plazo
# ---------------------------------------------------------------------------

def recompute_adjust(db: Session, profile_id: int = 1) -> dict[str, Any]:
    now = utcnow()
    genre: dict[str, float] = defaultdict(float)
    people: dict[str, float] = defaultdict(float)
    old_tol = 0.0
    adventure = 0.0
    counts: dict[str, int] = defaultdict(int)
    q = (db.query(FeedbackEvent, Film).join(Film, Film.id == FeedbackEvent.film_id)
         .filter(FeedbackEvent.profile_id == profile_id, FeedbackEvent.undone.is_(False)))
    for ev, f in q.all():
        w = math.exp(-max(0, (now - ev.created_at).days) / 120.0)
        key = ev.reason if ev.action == "dismiss" else ev.action
        counts[key or "dismiss"] += 1
        g2 = f.genres[:2]
        if ev.action == "accept":
            for g in g2:
                genre[g] += .04 * w
            if f.year and f.year < 1975:
                old_tol += .03 * w
        elif ev.action == "save":
            for g in g2:
                genre[g] += .025 * w
        elif ev.action == "dismiss":
            if ev.reason == "genre_no":
                for g in g2:
                    genre[g] -= .08 * w
            elif ev.reason == "people_no":
                for p in f.directors[:1]:
                    people[p] -= .20 * w
                for p in f.cast[:1]:
                    people[p] -= .08 * w
            elif ev.reason in ("too_dated", "too_slow") and f.year and f.year < 1980:
                old_tol -= .04 * w
            elif ev.reason == "too_known":
                adventure += .02 * w
            elif ev.reason == "never":
                for g in g2:
                    genre[g] -= .03 * w
    adjust = {
        "genre": {g: round(clamp(v, -.5, .5), 4) for g, v in genre.items() if abs(v) > .004},
        "people": {p: round(clamp(v, -.5, .5), 4) for p, v in people.items() if abs(v) > .004},
        "old_tol": round(clamp(old_tol, -.3, .12), 4),
        "adventure": round(clamp(adventure, 0, .15), 4),
        "counts": dict(counts),
    }
    p = db.get(Profile, profile_id)
    if p:
        p.taste_adjust = adjust
    db.flush()
    taste_mod.invalidate(profile_id)
    return adjust
