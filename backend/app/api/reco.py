"""Sesiones de recomendación: mazo de sugerencias, descartes con motivo, deshacer, veredicto y pitch."""
from __future__ import annotations

import logging
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..engine import feedback as fb
from ..engine import recommend as rec
from ..engine.context import Context
from ..engine.taste import build_taste
from ..models import Film, Profile, RecoSession
from ..services import enrich
from ..services.errors import ServiceError
from .serializers import film_card

log = logging.getLogger("claqueta.api.reco")
router = APIRouter(prefix="/api")

PROFILE = 1
DECK_SIZE = 8


def _seed_titles(db: Session, ranked: list[rec.Scored]) -> dict[int, str]:
    ids = {i for s in ranked for i in s.facts.get("rec_from", [])}
    if not ids:
        return {}
    return {f.id: f.title for f in db.query(Film).filter(Film.id.in_(ids))}


def _get_session(db: Session, sid: str) -> RecoSession:
    s = db.get(RecoSession, sid)
    if s is None:
        raise HTTPException(404, "Sesión no encontrada: empieza una nueva")
    return s


def deck_response(db: Session, sess: RecoSession, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    ctx = Context.model_validate(sess.context or {})
    res = rec.rank(db, PROFILE, ctx, sess.events, limit=DECK_SIZE)
    taste = build_taste(db, PROFILE)
    titles = _seed_titles(db, res.items)
    cards = []
    for i, s in enumerate(res.items):
        c = film_card(db, s.film, s, res.ctx, taste, titles)
        c["rank"] = i
        cards.append(c)
    out = {
        "session_id": sess.id,
        "context": ctx.model_dump(),
        "effective": {"max_minutes": res.ctx.max_minutes, "subtitles_ok": res.ctx.subtitles_ok},
        "deck": cards,
        "pool": {"films": res.pool_size, "candidates": res.candidates},
        "adjustments": res.adj.summary,
        "relaxed": res.relaxed,
        "empty_reason": res.empty_reason,
        "dismissed": len([e for e in sess.events if e.get("action") == "dismiss"]),
        "can_undo": bool(sess.events),
    }
    if extra:
        out.update(extra)
    return out


class SessionIn(BaseModel):
    context: Context = Field(default_factory=Context)


@router.post("/sessions")
def create_session(body: SessionIn, db: Session = Depends(get_db)):
    sess = RecoSession(id=uuid.uuid4().hex[:16], profile_id=PROFILE, context=body.context.model_dump(), events=[])
    db.add(sess)
    prof = db.get(Profile, PROFILE)
    if prof:
        prof.last_context = body.context.model_dump()
    db.commit()
    return deck_response(db, sess)


@router.get("/sessions/{sid}")
def get_session(sid: str, db: Session = Depends(get_db)):
    return deck_response(db, _get_session(db, sid))


@router.put("/sessions/{sid}/context")
def update_context(sid: str, body: Context, db: Session = Depends(get_db)):
    sess = _get_session(db, sid)
    sess.context = body.model_dump()
    prof = db.get(Profile, PROFILE)
    if prof:
        prof.last_context = body.model_dump()
    db.commit()
    return deck_response(db, sess)


class FeedbackIn(BaseModel):
    film_id: int
    action: Literal["dismiss", "save", "accept"]
    reason: str | None = None


@router.post("/sessions/{sid}/feedback")
def feedback(sid: str, body: FeedbackIn, db: Session = Depends(get_db)):
    sess = _get_session(db, sid)
    film = db.get(Film, body.film_id)
    if film is None:
        raise HTTPException(404, "Película no encontrada")
    toast = fb.record_event(db, sess, film, body.action, body.reason)
    fb.recompute_adjust(db, PROFILE)
    db.commit()
    return deck_response(db, sess, {"toast": toast})


@router.post("/sessions/{sid}/undo")
def undo(sid: str, db: Session = Depends(get_db)):
    sess = _get_session(db, sid)
    film = fb.undo_last(db, sess)
    if film is None:
        raise HTTPException(409, "No hay nada que deshacer")
    fb.recompute_adjust(db, PROFILE)
    db.commit()
    return deck_response(db, sess, {"restored_film_id": film.id, "toast": f"Recuperada «{film.title}»"})


class PitchIn(BaseModel):
    film_id: int


@router.post("/sessions/{sid}/pitch")
def pitch(sid: str, body: PitchIn, db: Session = Depends(get_db)):
    """Texto personalizado por LLM para la película (opcional; cacheado por película+contexto)."""
    sess = _get_session(db, sid)
    film = db.get(Film, body.film_id)
    if film is None:
        raise HTTPException(404, "Película no encontrada")
    ctx = Context.model_validate(sess.context or {})
    cached = enrich.cached_pitch(db, film, ctx)
    if cached:
        return {"pitch": cached, "source": "cache"}
    if enrich.llm_or_none() is None:
        return {"pitch": None, "source": "none"}
    scored = rec.evaluate(db, PROFILE, film, ctx)
    from ..engine.explain import build_texts
    taste = build_taste(db, PROFILE)
    texts = build_texts(scored, ctx, taste, {})
    try:
        res = enrich.get_pitch(db, film, ctx, [r["text"] for r in texts["reasons"]], texts["aged"]["label"])
    except ServiceError as e:
        log.info("pitch no disponible: %s", e.message)
        return {"pitch": None, "source": "error", "error": e.message}
    db.commit()
    return res or {"pitch": None, "source": "none"}


class ParseIn(BaseModel):
    text: str = Field(min_length=2, max_length=500)


@router.post("/context/parse")
def parse_context(body: ParseIn):
    """«Estoy cansado, quiero reír y tengo 90 minutos» → filtros del compositor."""
    source = "rules"
    parsed = None
    try:
        parsed = enrich.parse_context_llm(body.text)
        if parsed:
            source = "llm"
    except ServiceError as e:
        log.info("LLM no disponible para interpretar el texto: %s", e.message)
    if parsed:
        raw, expl = parsed
    else:
        raw, expl = enrich.parse_context_rules(body.text)
    return {"context": enrich.sanitize_context(raw), "explanation": expl, "source": source}


class EvaluateIn(BaseModel):
    context: Context = Field(default_factory=Context)


@router.post("/films/{film_id}/evaluate")
def evaluate(film_id: int, body: EvaluateIn, db: Session = Depends(get_db)):
    """«¿Me conviene esta película ahora?»: veredicto para una película concreta."""
    film = db.get(Film, film_id)
    if film is None:
        raise HTTPException(404, "Película no encontrada")
    scored = rec.evaluate(db, PROFILE, film, body.context)
    taste = build_taste(db, PROFILE)
    titles = _seed_titles(db, [scored])
    card = film_card(db, film, scored, body.context, taste, titles)
    soft = {rec.GATE_TEXT[k] for k in ("subtitles", "quality", "adj_pace", "adj_dark", "adj_weird", "adj_serious")}
    hard = [f for f in scored.flags if f not in soft]
    if hard:
        verdict = "skip"
    else:
        verdict = "go" if scored.score >= .62 and not scored.flags else "maybe" if scored.score >= .5 else "skip"
    card["verdict"] = verdict
    return card
