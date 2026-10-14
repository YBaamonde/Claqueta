"""Funciones que usan el LLM: enriquecer atributos, redactar el «pitch» y entender texto libre.

Todas degradan con elegancia: sin LLM (o si falla) la app sigue funcionando con heurísticas.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from .. import settings_store as S
from ..engine.attrs import sanitize_attrs
from ..engine.context import ERAS, Context
from ..engine.moods import MOODS
from ..genres import CANONICAL
from ..models import Film, PitchCache
from ..util import utcnow
from .errors import NotConfigured, ServiceError
from .llm import LLM, daily_used

log = logging.getLogger("claqueta.enrich")

ENRICH_SYSTEM = """Eres un crítico de cine con criterio y honestidad. Para cada película recibida devuelve \
atributos numéricos de 0 a 100 que describan CÓMO SE SIENTE verla HOY para un espectador actual no especialista.
Atributos: pace (0 contemplativa, 100 trepidante), intensity, tension (suspense), humor, warmth (calidez, \
feel-good), darkness (crudeza, temas oscuros), emotional (carga dramática), complexity (exigencia mental), \
weirdness (surrealismo/rareza formal), spectacle (escala visual, evasión), romance, \
dated (probabilidad de que un espectador actual la encuentre lenta, anticuada o aburrida pese a su prestigio: \
10 = intemporal, 50 = se nota la época pero engancha, 80 = solo para completistas), \
access (facilidad para un público no cinéfilo), family (apta para ver en familia), rewatch (ganas de repetirla).
Sé crítico: un clásico puede tener dated bajo si su ritmo y narración siguen funcionando (p. ej. thrillers y noir \
bien contados) y alto si es lento, teatral o depende de humor de su época. No inventes: si dudas, usa 50.
Añade "notes": una frase en español (máx. 140 caracteres), sin spoilers, que diga QUÉ ESPERAR hoy, con honestidad \
(ritmo, tono, a quién le va). Responde SOLO con JSON: {"films":[{"id":<id>,"pace":..,...,"notes":"..."}]}"""


def llm_or_none() -> LLM | None:
    try:
        return LLM.from_settings()
    except NotConfigured:
        return None


def _film_brief(f: Film) -> dict[str, Any]:
    return {
        "id": f.id, "titulo": f.title, "año": f.year, "generos": f.genres[:4], "director": (f.directors or [None])[0],
        "duracion": f.runtime, "idioma": f.original_language, "nota_tmdb": f.vote_average,
        "votos": f.vote_count, "sinopsis": (f.overview or "")[:230],
    }


def pending(db: Session, limit: int) -> list[Film]:
    return (db.query(Film)
            .filter(Film.details_at.isnot(None), Film.attrs_source.in_(("none", "heuristic")),
                    Film.runtime.isnot(None))
            .order_by(Film.jellyfin_id.is_(None), Film.vote_count.desc())
            .limit(limit).all())


def counts(db: Session) -> dict[str, int]:
    total = db.query(Film).filter(Film.details_at.isnot(None)).count()
    done = db.query(Film).filter(Film.attrs_source.in_(("llm", "seed"))).count()
    return {"total": total, "enriched": done, "pending": max(0, total - done)}


def enrich_batch(db: Session, llm: LLM, films: list[Film]) -> int:
    payload = json.dumps([_film_brief(f) for f in films], ensure_ascii=False)
    data = llm.chat_json(ENRICH_SYSTEM, payload, max_tokens=300 * len(films) + 200)
    items = data.get("films") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ServiceError("Respuesta del LLM sin la lista de películas")
    by_id = {f.id: f for f in films}
    n = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        f = by_id.get(it.get("id"))
        if not f:
            continue
        clean = sanitize_attrs(it, fallback=f.attrs or {})
        if not all(k in clean for k in ("pace", "dated", "humor", "emotional")):
            continue
        f.attrs = {**(f.attrs or {}), **clean}
        f.attrs_source, f.attrs_at = "llm", utcnow()
        n += 1
    db.flush()
    return n


def enrich_tick(db: Session, batch: int = 6) -> dict[str, Any]:
    """Un paso del enriquecimiento en segundo plano. Respeta el tope diario de tokens."""
    if not S.get("llm_enrich", True):
        return {"skipped": "desactivado"}
    llm = llm_or_none()
    if not llm:
        return {"skipped": "sin LLM"}
    cap = int(S.get("llm_daily_tokens", 120000) or 0)
    if cap and daily_used() >= cap:
        return {"skipped": "tope diario alcanzado"}
    films = pending(db, batch)
    if not films:
        return {"skipped": "nada pendiente"}
    n = enrich_batch(db, llm, films)
    return {"enriched": n}


# ---------------------------------------------------------------------------
# Pitch personalizado
# ---------------------------------------------------------------------------

PITCH_SYSTEM = ("Eres un amigo cinéfilo que recomienda una película con honestidad, sin spoilers ni humo. "
                "Escribe 2 frases en español (máx. 230 caracteres en total): por qué encaja con lo que la persona "
                "busca ahora y qué debe esperar (ritmo, tono). Si tiene riesgo de resultar lenta o anticuada, dilo con "
                "tacto. Responde SOLO con JSON: {\"pitch\":\"...\"}")


def pitch_key(film_id: int, ctx: Context) -> str:
    return hashlib.sha1(f"{film_id}|{ctx.signature()}".encode()).hexdigest()[:40]


def cached_pitch(db: Session, film: Film, ctx: Context) -> str | None:
    row = db.get(PitchCache, pitch_key(film.id, ctx))
    return row.text if row else None


def get_pitch(db: Session, film: Film, ctx: Context, reasons: list[str], aged_label: str) -> dict[str, str] | None:
    key = pitch_key(film.id, ctx)
    cached = db.get(PitchCache, key)
    if cached:
        return {"pitch": cached.text, "source": "cache"}
    llm = llm_or_none()
    if not llm:
        return None
    cap = int(S.get("llm_daily_tokens", 120000) or 0)
    if cap and daily_used() >= cap * 1.5:  # los pitches pueden pasarse un poco del tope de enriquecimiento
        return None
    user = json.dumps({
        "pelicula": _film_brief(film), "notas": (film.attrs or {}).get("notes"), "envejecimiento": aged_label,
        "motivos": reasons[:3],
        "busca": {"estado_de_animo": ctx.moods, "compania": ctx.company, "minutos": ctx.max_minutes,
                  "concentracion_1a5": ctx.focus},
    }, ensure_ascii=False)
    data = llm.chat_json(PITCH_SYSTEM, user, max_tokens=300, temperature=.5)
    text = (data.get("pitch") if isinstance(data, dict) else None) or ""
    text = re.sub(r"\s+", " ", text).strip()[:300]
    if not text:
        return None
    db.merge(PitchCache(key=key, text=text, created_at=utcnow()))
    db.flush()
    return {"pitch": text, "source": "llm"}


# ---------------------------------------------------------------------------
# Texto libre → contexto
# ---------------------------------------------------------------------------

PARSE_SYSTEM = """Convierte lo que el usuario quiere ver esta noche en un JSON de filtros. Campos (todos opcionales):
moods: lista (máx 3) de ids entre %s; company: solo|pareja|amigos|familia|peques; max_minutes: entero \
(minutos disponibles); focus: 1 (cabeza apagada) a 5 (máxima concentración); adventure: 0 (apuesta segura) a 1 \
(sorpréndeme); eras: lista entre %s; genres_in / genres_out: listas entre %s; subtitles_ok: bool; \
scope: all|library|streaming (library = solo lo que ya tengo en casa); allow_seen: bool. \
Incluye SOLO lo que el texto indique. Añade "explanation": una frase corta en español que resuma cómo lo has entendido. \
Responde SOLO JSON.""" % (", ".join(m.id for m in MOODS), ", ".join(e[0] for e in ERAS), ", ".join(CANONICAL))


def parse_context_llm(text: str) -> tuple[dict, str] | None:
    llm = llm_or_none()
    if not llm:
        return None
    data = llm.chat_json(PARSE_SYSTEM, text[:500], max_tokens=350, temperature=0.1)
    if not isinstance(data, dict):
        return None
    expl = str(data.pop("explanation", "") or "")
    return data, expl


_MOOD_WORDS = {
    "reir": ["reír", "reir", "divertid", "comedia", "gracios"], "llorar": ["llorar", "pañuelos", "emotiv", "drama"],
    "adrenalina": ["adrenalina", "acción", "accion", "trepidante"], "pensar": ["pensar", "reflexi", "cerebr", "profunda"],
    "evadirme": ["evadir", "escapar", "fantas", "aventura épica"], "miedo": ["miedo", "terror", "asust"],
    "comfort": ["reconfort", "relaj", "tranquil", "ligera", "sin complicaciones"],
    "romantico": ["romántic", "romantic", "amor"], "inspirador": ["inspirador", "motivador"],
    "intriga": ["intriga", "misterio", "thriller"], "raro": ["rara", "raro", "extraña", "de autor", "experimental"],
    "nostalgia": ["nostalgi", "de siempre", "de antes"],
}


MOOD_LABEL = {m.id: m.label for m in MOODS}
_NUM_WORDS = {"una": 1, "un": 1, "dos": 2, "tres": 3, "cuatro": 4}


def _parse_minutes(t: str) -> int | None:
    """«hora y media», «2 horas», «90 min», «una horita»… → minutos disponibles."""
    m = re.search(r"(\d{2,3})\s*(?:min|minutos)\b", t)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(?:(\d|una|un|dos|tres|cuatro)\s*(?:horas?|horitas?|h)\b)(?:\s*y\s*(media|cuarto|pico|\d{1,2}))?", t)
    if m:
        n = m.group(1)
        hours = int(n) if n.isdigit() else _NUM_WORDS[n]
        extra = m.group(2)
        mins = 30 if extra == "media" else 15 if extra == "cuarto" else 10 if extra == "pico" \
            else int(extra) if extra and extra.isdigit() else 0
        return hours * 60 + mins + (5 if hours >= 2 and not mins else 0)
    m = re.search(r"\bhora\s*y\s*(media|cuarto|pico)", t)
    if m:
        return 60 + {"media": 30, "cuarto": 15, "pico": 10}[m.group(1)]
    if re.search(r"\bcorta\b|\bcortita\b|\bpoco tiempo\b", t):
        return 100
    return None


def parse_context_rules(text: str) -> tuple[dict, str]:
    """Plan B sin LLM: palabras clave en español."""
    t = text.lower()
    out: dict[str, Any] = {}
    moods = [m for m, words in _MOOD_WORDS.items() if any(w in t for w in words)]
    if moods:
        out["moods"] = moods[:3]
    for pat, comp in ((r"\bpareja|\bnovi[oa]|\bmarid|\bmujer\b|\bespos", "pareja"), (r"\bamigos|\bcolegas", "amigos"),
                      (r"\bfamilia|\babuel", "familia"), (r"\bhijos|\bniñ|\bpeques|\bpequeñ", "peques"),
                      (r"\b(?:estoy|voy|ver|veo|veré|esta noche)\s+(?:yo\s+)?(?:solo|sola)\b|\ba solas\b|\byo solo\b|\bsolo para mi\b", "solo")):
        if re.search(pat, t):
            out["company"] = comp
            break
    mins = _parse_minutes(t)
    if mins:
        out["max_minutes"] = max(40, min(400, mins))
    if re.search(r"cansad|agotad|cabeza apagada|sin pensar|zombi|derrotad|reventad", t):
        out["focus"] = 1
    elif re.search(r"concentrad|atent[oa]|exigente|despejad|con la cabeza", t):
        out["focus"] = 5
    if re.search(r"sin subt[ií]tulos|nada de subt|no quiero subt|en español|doblad", t):
        out["subtitles_ok"] = False
    if re.search(r"sorpr[eé]nd|algo nuevo|descubrir|arriesg", t):
        out["adventure"] = .85
    elif re.search(r"seguro|apuesta segura|que no falle|sin riesgos", t):
        out["adventure"] = .1
    if re.search(r"clásic|clasic|antigua|de antes", t):
        out["eras"] = ["edad_oro", "sesenta_setenta"]
    elif re.search(r"reciente|actual|moderna|estreno", t):
        out["eras"] = ["actual"]
    if re.search(r"ya (?:la )?tengo|en casa|jellyfin|mi biblioteca|mi servidor", t):
        out["scope"] = "library"
    parts = []
    if out.get("moods"):
        parts.append("ánimo: " + ", ".join(MOOD_LABEL.get(m, m).lower() for m in out["moods"]))
    if out.get("company"):
        parts.append("compañía: " + out["company"])
    if out.get("max_minutes"):
        parts.append(f"hasta {out['max_minutes']} min")
    if out.get("subtitles_ok") is False:
        parts.append("sin subtítulos")
    if out.get("adventure", .35) >= .8:
        parts.append("con ganas de sorpresa")
    elif out.get("adventure", .35) <= .15:
        parts.append("apuesta segura")
    if out.get("focus") == 1:
        parts.append("poca energía mental")
    elif out.get("focus") == 5:
        parts.append("concentración total")
    if out.get("eras"):
        parts.append("época: " + ", ".join(out["eras"]))
    if out.get("scope") == "library":
        parts.append("solo lo que ya tienes en casa")
    return out, ("He entendido " + "; ".join(parts) + ".") if parts else "No he sacado nada concreto; ajusta a mano."


def sanitize_context(raw: dict) -> dict:
    """Valida lo que devuelva el LLM aplicando el propio modelo Context; devuelve solo las claves dadas."""
    keys = [k for k in raw if k in Context.model_fields]
    try:
        ctx = Context.model_validate({k: raw[k] for k in keys})
    except Exception:  # noqa: BLE001
        good: dict[str, Any] = {}
        for k in keys:
            try:
                Context.model_validate({k: raw[k]})
                good[k] = raw[k]
            except Exception:  # noqa: BLE001
                continue
        ctx = Context.model_validate(good)
        keys = list(good)
    return {k: getattr(ctx, k) for k in keys}
