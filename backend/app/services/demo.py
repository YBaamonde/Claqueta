"""Carga del catálogo semilla y de un historial de ejemplo para probar la app sin datos propios."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from ..data.seed import EN_ALIASES, SEED_ROWS
from ..engine.attrs import heuristic_attrs
from ..models import Film, UserFilm
from ..util import clamp, norm_title, utcnow
from . import catalog

_KEYS = ["pace", "intensity", "tension", "humor", "warmth", "darkness", "emotional", "complexity", "weirdness",
         "spectacle", "romance", "dated", "access"]


def _attrs(vals: tuple, min_age: int, notes: str) -> dict[str, Any]:
    a: dict[str, Any] = {k: round(v / 100, 3) for k, v in zip(_KEYS, vals)}
    fam = .95 if min_age <= 0 else .85 if min_age <= 7 else .42 if min_age <= 12 else .12 if min_age <= 16 else .02
    a["family"] = round(fam * (1 - .35 * a["darkness"]), 3)
    a["rewatch"] = round(clamp(.3 + .35 * a["humor"] + .25 * a["warmth"] + .2 * a["spectacle"] - .25 * a["darkness"]), 3)
    if notes:
        a["notes"] = notes
    return a


def load_seed(db: Session) -> int:
    """Inserta (de forma idempotente) las películas de la semilla. Devuelve cuántas añadió."""
    added = 0
    now = utcnow()
    for (title, orig, year, rt, genres, director, cast, countries, lang, va, votes_k, age, vals, overview,
         notes) in SEED_ROWS:
        if catalog.find_local(db, [title, orig], year) is not None:
            continue
        f = Film(title=title, original_title=orig, year=year, runtime=rt, genres=genres, directors=[director],
                 cast=cast, countries=countries, original_language=lang, vote_average=va,
                 vote_count=int(votes_k * 1000), popularity=votes_k / 10, min_age=age, overview=overview,
                 keywords=[], providers={}, source="seed", details_at=now, release_date=f"{year}-01-01")
        f.norm_title, f.norm_alt = norm_title(title), norm_title(EN_ALIASES.get(title, orig))
        f.attrs = _attrs(vals, age, notes)
        f.attrs_source, f.attrs_at = "seed", now
        db.add(f)
        added += 1
    db.flush()
    return added


# título original, año, valoración, ¿favorita?, hace cuántos días la vio (None = sin fecha)
SAMPLE_HISTORY: list[tuple[str, int, float, bool, int | None]] = [
    ("The Matrix", 1999, 4.5, True, None), ("Inception", 2010, 4.5, True, None),
    ("Interstellar", 2014, 5.0, True, None), ("The Dark Knight", 2008, 4.5, True, None),
    ("Parasite", 2019, 5.0, True, None), ("Pulp Fiction", 1994, 4.0, False, None),
    ("The Shawshank Redemption", 1994, 5.0, True, None), ("Forrest Gump", 1994, 4.0, False, None),
    ("GoodFellas", 1990, 4.0, False, None), ("Fight Club", 1999, 4.0, False, None),
    ("Se7en", 1995, 4.5, True, None), ("Alien", 1979, 4.0, False, None), ("Jaws", 1975, 4.0, False, None),
    ("Back to the Future", 1985, 4.5, True, None), ("Star Wars", 1977, 4.0, False, None),
    ("Raiders of the Lost Ark", 1981, 4.0, False, None), ("Casablanca", 1942, 4.0, False, 70),
    ("Psycho", 1960, 4.0, False, 55), ("Rear Window", 1954, 4.5, True, 40),
    ("Some Like It Hot", 1959, 4.0, False, 33), ("Metropolis", 1927, 2.5, False, 120),
    ("Citizen Kane", 1941, 2.5, False, 100), ("2001: A Space Odyssey", 1968, 2.0, False, 90),
    ("Whiplash", 2014, 4.5, True, 4), ("Get Out", 2017, 4.0, False, 9), ("Seven Samurai", 1954, 3.5, False, 15),
    ("Mad Max: Fury Road", 2015, 3.5, False, 22), ("Arrival", 2016, 4.0, False, 28), ("Coco", 2017, 4.0, False, None),
    ("La La Land", 2016, 3.5, False, None),
]


def load_sample_history(db: Session, profile_id: int = 1) -> int:
    """Marca un historial de ejemplo (perfil «recién llegado a los clásicos»)."""
    n = 0
    today = utcnow().date()
    for orig, year, rating, liked, days in SAMPLE_HISTORY:
        f = catalog.find_local(db, [orig], year)
        if f is None:
            continue
        row = db.query(UserFilm).filter_by(profile_id=profile_id, film_id=f.id).one_or_none()
        if row is None:
            row = UserFilm(profile_id=profile_id, film_id=f.id, status="none", source="demo")
            db.add(row)
        row.status, row.rating, row.liked = "watched", rating, liked
        row.watched_date = today - timedelta(days=days) if days is not None else None
        n += 1
    db.flush()
    return n


def clear_demo(db: Session, profile_id: int = 1) -> int:
    """Borra el historial de ejemplo (los datos reales de otras fuentes no se tocan)."""
    rows = db.query(UserFilm).filter_by(profile_id=profile_id, source="demo").all()
    for r in rows:
        db.delete(r)
    db.flush()
    return len(rows)


def ensure_attrs_all(db: Session) -> int:
    """Rellena heurísticamente los atributos que falten (migraciones, altas externas)."""
    n = 0
    for f in db.query(Film).filter(Film.attrs_source == "none").all():
        f.attrs = heuristic_attrs(f)
        f.attrs_source = "heuristic"
        n += 1
    db.flush()
    return n
