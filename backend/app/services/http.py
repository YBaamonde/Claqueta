from __future__ import annotations

import threading
import time
from typing import Any

import httpx

from .errors import ServiceError

_UA = "Claqueta/1.0 (+self-hosted)"


class Limiter:
    """Intervalo mínimo entre peticiones, compartido entre hilos."""

    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self.min_interval
        if delay > 0:
            time.sleep(delay)


def request_json(client: httpx.Client, method: str, url: str, *, retries: int = 2, name: str = "servicio",
                 **kw: Any) -> Any:
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            r = client.request(method, url, **kw)
        except httpx.TimeoutException as e:
            last = e
            time.sleep(.6 * (attempt + 1))
            continue
        except httpx.HTTPError as e:
            raise ServiceError(f"No se pudo conectar con {name}: {e.__class__.__name__}") from e
        if r.status_code == 429:
            wait = min(8.0, float(r.headers.get("retry-after", "1") or 1))
            time.sleep(wait)
            last = ServiceError(f"{name} limita las peticiones (429)", 429)
            continue
        if r.status_code in (401, 403):
            raise ServiceError(f"{name} rechazó las credenciales ({r.status_code})", r.status_code)
        if r.status_code == 404:
            raise ServiceError(f"{name}: no encontrado", 404)
        if r.status_code >= 400:
            detail = ""
            try:
                detail = r.text[:200]
            except Exception:  # noqa: BLE001
                pass
            raise ServiceError(f"{name} respondió {r.status_code}. {detail}".strip(), r.status_code)
        if not r.content:
            return None
        try:
            return r.json()
        except ValueError as e:
            raise ServiceError(f"{name} devolvió una respuesta no válida") from e
    if isinstance(last, ServiceError):
        raise last
    raise ServiceError(f"{name} no responde (tiempo de espera agotado)")


def make_client(timeout: float = 15.0, **kw: Any) -> httpx.Client:
    return httpx.Client(timeout=timeout, headers={"User-Agent": _UA}, follow_redirects=True, **kw)
