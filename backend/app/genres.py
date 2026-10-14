"""Géneros canónicos (nombres de TMDB en español) y normalización desde otras fuentes."""
from __future__ import annotations

TMDB_GENRE_IDS: dict[int, str] = {
    28: "Acción", 12: "Aventura", 16: "Animación", 35: "Comedia", 80: "Crimen",
    99: "Documental", 18: "Drama", 10751: "Familia", 14: "Fantasía", 36: "Historia",
    27: "Terror", 10402: "Música", 9648: "Misterio", 10749: "Romance",
    878: "Ciencia ficción", 10770: "Película de TV", 53: "Suspense", 10752: "Bélica",
    37: "Western",
}

CANONICAL = sorted(set(TMDB_GENRE_IDS.values()))

_EN_ES = {
    "action": "Acción", "adventure": "Aventura", "animation": "Animación", "comedy": "Comedia",
    "crime": "Crimen", "documentary": "Documental", "drama": "Drama", "family": "Familia",
    "fantasy": "Fantasía", "history": "Historia", "horror": "Terror", "music": "Música",
    "musical": "Música", "mystery": "Misterio", "romance": "Romance", "science fiction": "Ciencia ficción",
    "sci-fi": "Ciencia ficción", "tv movie": "Película de TV", "thriller": "Suspense",
    "war": "Bélica", "western": "Western", "film-noir": "Crimen", "film noir": "Crimen",
    # Jellyfin en español / variantes
    "acción": "Acción", "aventura": "Aventura", "animación": "Animación", "comedia": "Comedia",
    "terror": "Terror", "misterio": "Misterio", "suspense": "Suspense", "bélica": "Bélica",
    "ciencia ficción": "Ciencia ficción", "fantasía": "Fantasía", "historia": "Historia",
    "música": "Música", "familia": "Familia", "crimen": "Crimen", "documental": "Documental",
}


def canon_genre(name: str | None) -> str | None:
    if not name:
        return None
    key = name.strip().lower()
    if key in _EN_ES:
        return _EN_ES[key]
    for c in CANONICAL:
        if c.lower() == key:
            return c
    return None


def canon_genres(names) -> list[str]:
    out: list[str] = []
    for n in names or []:
        g = canon_genre(n)
        if g and g not in out:
            out.append(g)
    return out


def genres_from_ids(ids) -> list[str]:
    return [TMDB_GENRE_IDS[i] for i in ids or [] if i in TMDB_GENRE_IDS]
