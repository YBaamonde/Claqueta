"""Proxy de pósters con caché en disco: el navegador nunca habla con TMDB y los pósters se descargan una vez."""
from __future__ import annotations

import logging
import re
import threading
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..config import get_env
from ..services.http import make_client

log = logging.getLogger("claqueta.media")
router = APIRouter(prefix="/api")

SIZES = {"w92", "w154", "w185", "w342", "w500", "w780", "w1280", "original"}
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}\.(jpg|jpeg|png|webp)$")
CACHE_HEADERS = {"Cache-Control": "public, max-age=2592000, immutable"}

_client: httpx.Client | None = None
_lock = threading.Lock()
_failed: dict[str, float] = {}  # caché negativa breve para no martillear TMDB si no hay red


def _http() -> httpx.Client:
    global _client
    with _lock:
        if _client is None:
            _client = make_client(timeout=12)
        return _client


def cache_dir() -> Path:
    d = get_env().data_dir / "img"
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.get("/img/{size}/{name}")
def image(size: str, name: str):
    if size not in SIZES or not NAME_RE.match(name):
        raise HTTPException(404)
    path = cache_dir() / size / name
    if path.exists() and path.stat().st_size > 0:
        return FileResponse(path, headers=CACHE_HEADERS)
    import time

    key = f"{size}/{name}"
    if time.monotonic() - _failed.get(key, -999) < 120:
        raise HTTPException(404)
    try:
        r = _http().get(f"https://image.tmdb.org/t/p/{size}/{name}")
    except httpx.HTTPError as e:
        _failed[key] = time.monotonic()
        log.info("no se pudo descargar %s: %s", key, e.__class__.__name__)
        raise HTTPException(404) from e
    ctype = r.headers.get("content-type", "")
    if r.status_code != 200 or not ctype.startswith("image/"):
        _failed[key] = time.monotonic()
        raise HTTPException(404)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(r.content)
    tmp.replace(path)
    return FileResponse(path, headers=CACHE_HEADERS)
