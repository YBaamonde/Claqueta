from __future__ import annotations

import math
import re
import unicodedata
from datetime import datetime, timezone
from typing import Iterable, Mapping, Sequence


def utcnow() -> datetime:
    """UTC ingenuo (sin tzinfo): SQLite no guarda zona horaria."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


_ARTICLES = ("the ", "a ", "an ", "el ", "la ", "los ", "las ", "un ", "una ", "l'", "le ", "les ")


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm_title(s: str | None) -> str:
    """Normaliza un título para emparejar entre fuentes (Letterboxd, Jellyfin, TMDB)."""
    if not s:
        return ""
    s = strip_accents(s).lower().replace("&", " and ")
    s = re.sub(r"[^\w ]+|_", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for art in _ARTICLES:
        if s.startswith(art):
            s = s[len(art):]
            break
    return s


def jaccard(a: Iterable, b: Iterable) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def cosine(a: Mapping[str, float], b: Mapping[str, float], keys: Sequence[str] | None = None) -> float:
    keys = keys or list(a.keys())
    dot = na = nb = 0.0
    for k in keys:
        x, y = float(a.get(k, 0.5)) - 0.5, float(b.get(k, 0.5)) - 0.5  # centrado en 0.5
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 1e-9 or nb <= 1e-9:
        return 0.0
    return dot / math.sqrt(na * nb)


def sigmoid(x: float) -> float:
    if x >= 0:
        return 1 / (1 + math.exp(-x))
    e = math.exp(x)
    return e / (1 + e)


def mask_secret(v: str) -> str:
    if not v:
        return ""
    if len(v) <= 8:
        return "•" * len(v)
    return v[:3] + "•" * 6 + v[-3:]
