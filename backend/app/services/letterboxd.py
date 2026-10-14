"""Importación de Letterboxd sin API: exportación CSV (histórico completo) + RSS público (lo reciente).

La exportación oficial (Ajustes → Importar y exportar → Exportar tus datos) es un ZIP con
``watched.csv``, ``ratings.csv``, ``diary.csv``, ``watchlist.csv``, ``likes/films.csv``…
Aceptamos el ZIP entero o CSV sueltos y fusionamos todo por (título, año).
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from xml.etree import ElementTree as ET

from ..util import norm_title
from .errors import ServiceError

NS = {
    "lb": "https://letterboxd.com",
    "tmdb": "https://themoviedb.org",
    "dc": "http://purl.org/dc/elements/1.1/",
}


@dataclass
class LbEntry:
    title: str
    year: int | None
    uri: str | None = None
    watched: bool = False
    watchlist: bool = False
    liked: bool = False
    rating: float | None = None
    watched_date: date | None = None
    rewatch: bool = False
    tmdb_id: int | None = None
    sources: set[str] = field(default_factory=set)

    @property
    def key(self) -> tuple[str, int | None]:
        return (norm_title(self.title), self.year)


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _year(s: str | None) -> int | None:
    m = re.search(r"\d{4}", s or "")
    return int(m.group()) if m else None


def _rows(data: bytes) -> list[dict[str, str]]:
    text = data.decode("utf-8-sig", errors="replace")
    return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(io.StringIO(text))]


def _classify(name: str, headers: set[str]) -> str | None:
    n = name.lower().replace("\\", "/")
    base = n.rsplit("/", 1)[-1]
    if "/likes/" in n or n.startswith("likes/"):
        return "likes" if base == "films.csv" else None
    for kind in ("ratings", "diary", "watched", "watchlist"):
        if base == f"{kind}.csv":
            return kind
    # CSV suelto con otro nombre: por cabeceras
    if "Watched Date" in headers:
        return "diary"
    if "Rating" in headers:
        return "ratings"
    return None


def parse_files(files: dict[str, bytes]) -> list[LbEntry]:
    """``files``: nombre → contenido. Acepta CSVs y/o un ZIP de exportación."""
    flat: dict[str, bytes] = {}
    for name, data in files.items():
        if name.lower().endswith(".zip") or data[:2] == b"PK":
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    for zi in z.infolist():
                        if zi.filename.lower().endswith(".csv") and not zi.is_dir() and zi.file_size < 50_000_000:
                            flat[zi.filename] = z.read(zi)
            except zipfile.BadZipFile as e:
                raise ServiceError("El ZIP de Letterboxd no es válido") from e
        elif name.lower().endswith(".csv"):
            flat[name] = data
    if not flat:
        raise ServiceError("No encontré ningún CSV de Letterboxd (watched, ratings, diary, watchlist…)")

    entries: dict[tuple[str, int | None], LbEntry] = {}

    def get(row: dict[str, str]) -> LbEntry | None:
        title = row.get("Name") or row.get("Title") or ""
        if not title:
            return None
        year = _year(row.get("Year"))
        e = LbEntry(title, year, row.get("Letterboxd URI") or None)
        existing = entries.get(e.key)
        if existing:
            existing.uri = existing.uri or e.uri
            return existing
        entries[e.key] = e
        return e

    for name, data in flat.items():
        rows = _rows(data)
        kind = _classify(name, set(rows[0].keys()) if rows else set())
        if not kind:
            continue
        for row in rows:
            e = get(row)
            if not e:
                continue
            e.sources.add(kind)
            if kind == "watched":
                e.watched = True
            elif kind == "ratings":
                e.watched = True
                try:
                    e.rating = float(row.get("Rating", ""))
                except ValueError:
                    pass
            elif kind == "diary":
                e.watched = True
                d = _parse_date(row.get("Watched Date") or row.get("Date"))
                if d and (e.watched_date is None or d > e.watched_date):
                    e.watched_date = d
                if (row.get("Rewatch") or "").lower() == "yes":
                    e.rewatch = True
                try:
                    r = float(row.get("Rating", ""))
                    if e.rating is None:
                        e.rating = r
                except ValueError:
                    pass
            elif kind == "watchlist":
                e.watchlist = True
            elif kind == "likes":
                e.liked = True
    return list(entries.values())


def parse_rss(xml_text: str) -> list[LbEntry]:
    """RSS público del perfil: ``https://letterboxd.com/<usuario>/rss/`` (últimas ~50 entradas)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise ServiceError("El RSS de Letterboxd no es válido") from e
    out: list[LbEntry] = []
    for item in root.iterfind("./channel/item"):
        title = item.findtext("lb:filmTitle", namespaces=NS)
        if not title:
            continue  # listas u otras entradas
        year = _year(item.findtext("lb:filmYear", namespaces=NS))
        rating_txt = item.findtext("lb:memberRating", namespaces=NS)
        tmdb_txt = item.findtext("tmdb:movieId", namespaces=NS)
        e = LbEntry(
            title=title, year=year, uri=item.findtext("link"), watched=True,
            rating=float(rating_txt) if rating_txt else None,
            watched_date=_parse_date(item.findtext("lb:watchedDate", namespaces=NS)),
            rewatch=(item.findtext("lb:rewatch", namespaces=NS) or "").lower() == "yes",
            liked=(item.findtext("lb:memberLike", namespaces=NS) or "").lower() == "yes",
            tmdb_id=int(tmdb_txt) if tmdb_txt and tmdb_txt.isdigit() else None,
        )
        e.sources.add("rss")
        out.append(e)
    return out


def export_diary_csv(rows: list[dict[str, Any]]) -> str:
    """CSV en el formato de importación de Letterboxd (https://letterboxd.com/import/)."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Title", "Year", "WatchedDate", "Rating10", "Rewatch", "Liked"])
    for r in rows:
        rating10 = round(r["rating"] * 2) if r.get("rating") else ""
        w.writerow([r["title"], r.get("year") or "", r.get("watched_date") or "", rating10,
                    "true" if r.get("rewatch") else "", "true" if r.get("liked") else ""])
    return buf.getvalue()


def export_watchlist_csv(rows: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Title", "Year"])
    for r in rows:
        w.writerow([r["title"], r.get("year") or ""])
    return buf.getvalue()
