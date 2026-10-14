"""Configuración por entorno.

Solo lo imprescindible vive aquí. Todo lo que el usuario pueda querer cambiar
desde la interfaz (claves de API, URLs, pesos del motor...) se gestiona en
``settings_store`` y se guarda en la base de datos; las variables de entorno
actúan como valores por defecto.
"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

VERSION = "1.0.0"


class Env(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    data_dir: Path = Path("./data")
    static_dir: Path | None = None
    access_password: str = ""
    secret_key: str = ""
    disable_scheduler: bool = False
    log_level: str = "INFO"

    # Valores por defecto de integraciones (se pueden sobrescribir desde Ajustes).
    tmdb_api_key: str = ""
    tmdb_language: str = "es-ES"
    region: str = "ES"
    jellyfin_url: str = ""
    jellyfin_public_url: str = ""
    jellyfin_api_key: str = ""
    jellyfin_user_id: str = ""
    jellyseerr_url: str = ""
    jellyseerr_public_url: str = ""
    jellyseerr_api_key: str = ""
    radarr_url: str = ""
    radarr_api_key: str = ""
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    letterboxd_username: str = ""


_env: Env | None = None


def get_env() -> Env:
    global _env
    if _env is None:
        _env = Env()
    return _env


def reset_env() -> None:
    global _env
    _env = None
