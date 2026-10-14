"""Ajustes editables desde la interfaz.

Orden de resolución: valor guardado en la base de datos → variable de entorno → valor por defecto.
Los secretos nunca salen sin enmascarar de la API (``masked_view``) y se ignoran al guardar si
llegan con el marcador de enmascarado.
"""
from __future__ import annotations

import threading
from typing import Any

from . import db
from .config import get_env
from .models import Setting
from .util import mask_secret

MASK = "•"

DEFS: list[dict[str, Any]] = [
    # --- Catálogo ---
    dict(key="tmdb_api_key", group="tmdb", label="Clave de API de TMDB", kind="text", secret=True,
         help="Gratuita en themoviedb.org → Ajustes → API. Vale la clave v3 o el token de lectura v4."),
    dict(key="tmdb_language", group="tmdb", label="Idioma de los metadatos", kind="text", default="es-ES"),
    dict(key="region", group="tmdb", label="País (disponibilidad en streaming)", kind="text", default="ES"),
    # --- Jellyfin ---
    dict(key="jellyfin_url", group="jellyfin", label="URL de Jellyfin (desde el servidor)", kind="text",
         help="Ej.: http://192.168.68.53:8096 o http://jellyfin:8096 si comparten red Docker."),
    dict(key="jellyfin_public_url", group="jellyfin", label="URL pública de Jellyfin (para el botón ▶)", kind="text",
         help="La que abres tú en el navegador. Si lo dejas vacío se usa la anterior."),
    dict(key="jellyfin_api_key", group="jellyfin", label="Clave de API de Jellyfin", kind="text", secret=True,
         help="Panel de control → Claves de API."),
    dict(key="jellyfin_user_id", group="jellyfin", label="ID de usuario de Jellyfin (historial)", kind="text",
         help="Opcional. Si lo dejas vacío se usa el primer administrador."),
    # --- Jellyseerr / Radarr ---
    dict(key="jellyseerr_url", group="jellyseerr", label="URL de Jellyseerr", kind="text"),
    dict(key="jellyseerr_public_url", group="jellyseerr", label="URL pública de Jellyseerr", kind="text"),
    dict(key="jellyseerr_api_key", group="jellyseerr", label="Clave de API de Jellyseerr", kind="text", secret=True,
         help="Ajustes → General → Clave de API."),
    dict(key="radarr_url", group="radarr", label="URL de Radarr (opcional)", kind="text",
         help="Solo para mostrar el progreso de descarga de lo que pidas."),
    dict(key="radarr_api_key", group="radarr", label="Clave de API de Radarr", kind="text", secret=True),
    # --- Letterboxd ---
    dict(key="letterboxd_username", group="letterboxd", label="Usuario de Letterboxd", kind="text",
         help="Para sincronizar tu diario reciente por RSS (público). El histórico se importa con los CSV."),
    # --- LLM ---
    dict(key="llm_base_url", group="llm", label="Endpoint compatible con OpenAI", kind="text"),
    dict(key="llm_api_key", group="llm", label="Clave de API del LLM", kind="text", secret=True),
    dict(key="llm_model", group="llm", label="Modelo", kind="text"),
    dict(key="llm_extra_body", group="llm", label="Parámetros extra (JSON)", kind="text", default="",
         help='Opcional. Ej.: {"reasoning_effort":"low"} para modelos de razonamiento.'),
    dict(key="llm_tpm", group="llm", label="Tokens por minuto permitidos", kind="number", default=6000,
         help="Ajusta al límite de tu plan gratuito para no recibir errores 429."),
    dict(key="llm_daily_tokens", group="llm", label="Tope diario de tokens para enriquecer", kind="number",
         default=120000),
    dict(key="llm_enrich", group="llm", label="Enriquecer fichas en segundo plano", kind="bool", default=True),
    # --- Motor ---
    dict(key="engine_weights", group="engine", label="Pesos del motor", kind="json", default={}),
    dict(key="anti_toston_default", group="engine", label="Protección anti-tostón por defecto", kind="bool",
         default=True),
]

_BY_KEY = {d["key"]: d for d in DEFS}
_cache: dict[str, Any] = {}
_loaded = False
_lock = threading.RLock()


def _load() -> None:
    global _loaded
    with _lock:
        _cache.clear()
        with db.session_scope() as s:
            for row in s.query(Setting).all():
                _cache[row.key] = row.value
        _loaded = True


def invalidate() -> None:
    global _loaded
    with _lock:
        _loaded = False


def get(key: str, default: Any = None) -> Any:
    with _lock:
        if not _loaded:
            _load()
        if key in _cache and _cache[key] not in (None, ""):
            return _cache[key]
    env_val = getattr(get_env(), key, None)
    if env_val not in (None, ""):
        return env_val
    d = _BY_KEY.get(key, {})
    if "default" in d:
        return d["default"]
    return default


def set_many(values: dict[str, Any]) -> list[str]:
    changed: list[str] = []
    with db.session_scope() as s:
        for key, val in values.items():
            if key not in _BY_KEY and not key.startswith("x_"):
                continue
            d = _BY_KEY.get(key, {})
            if d.get("secret") and isinstance(val, str) and MASK in val:
                continue  # el cliente reenvió el valor enmascarado: no tocar
            if isinstance(val, str):
                val = val.strip()
                if d.get("kind") == "text" and key.endswith("_url"):
                    val = val.rstrip("/")
            row = s.get(Setting, key)
            if row is None:
                s.add(Setting(key=key, value=val))
            else:
                row.value = val
            changed.append(key)
    invalidate()
    return changed


def set_raw(key: str, value: Any) -> None:
    """Para estado interno (contadores, marcas de última sincronización)."""
    with db.session_scope() as s:
        row = s.get(Setting, key)
        if row is None:
            s.add(Setting(key=key, value=value))
        else:
            row.value = value
    invalidate()


def get_raw(key: str, default: Any = None) -> Any:
    with _lock:
        if not _loaded:
            _load()
        return _cache.get(key, default)


def masked_view() -> dict[str, Any]:
    out = []
    for d in DEFS:
        v = get(d["key"], d.get("default", ""))
        item = {k: d.get(k) for k in ("key", "group", "label", "kind", "help")}
        item["secret"] = bool(d.get("secret"))
        if d.get("secret"):
            item["value"] = mask_secret(v if isinstance(v, str) else "")
            item["is_set"] = bool(v)
        else:
            item["value"] = v
            item["is_set"] = v not in (None, "", {}, [])
        out.append(item)
    return {"settings": out}


def configured() -> dict[str, bool]:
    return {
        "tmdb": bool(get("tmdb_api_key")),
        "jellyfin": bool(get("jellyfin_url") and get("jellyfin_api_key")),
        "jellyseerr": bool(get("jellyseerr_url") and get("jellyseerr_api_key")),
        "radarr": bool(get("radarr_url") and get("radarr_api_key")),
        "llm": bool(get("llm_base_url") and get("llm_model")),
        "letterboxd": bool(get("letterboxd_username")),
    }
