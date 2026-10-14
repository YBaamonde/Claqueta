"""Tareas periódicas en segundo plano (un único hilo ligero que lanza trabajos en ``jobs.manager``)."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Callable

from . import settings_store as S
from .db import session_scope
from .services import enrich, tasks
from .services.jobs import manager
from .util import utcnow

log = logging.getLogger("claqueta.scheduler")


class Scheduler:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._next: dict[str, float] = {}

    # (nombre, cada_n_segundos, retraso_inicial, condición, acción)
    def _plan(self) -> list[tuple[str, int, int, Callable[[], bool], Callable[[], None]]]:
        cfg = S.configured
        return [
            ("enrich", 75, 45, lambda: cfg()["llm"] and bool(S.get("llm_enrich", True)), self._enrich),
            ("learn", 3600, 120, lambda: True, lambda: manager.start("learn", "Aprendiendo de tus descartes",
                                                                       lambda job: tasks.learn(job))),
            ("jellyfin", 6 * 3600, 90, lambda: cfg()["jellyfin"], lambda: manager.start(
                "sync_jellyfin", "Sincronizando Jellyfin", tasks.sync_jellyfin)),
            ("letterboxd", 6 * 3600, 150, lambda: cfg()["letterboxd"], lambda: manager.start(
                "sync_lb_rss", "Leyendo tu RSS de Letterboxd", tasks.sync_letterboxd_rss)),
            ("seerr", 600, 180, lambda: cfg()["jellyseerr"], lambda: manager.start(
                "seerr", "Actualizando peticiones", tasks.refresh_seerr)),
            ("maintenance", 24 * 3600, 240, lambda: cfg()["tmdb"], lambda: manager.start(
                "maintenance", "Completando fichas pendientes", tasks.maintenance)),
        ]

    @staticmethod
    def _enrich() -> None:
        try:
            with session_scope() as db:
                res = enrich.enrich_tick(db)
            if "enriched" in res:
                log.info("enriquecidas %s fichas", res["enriched"])
        except Exception as e:  # noqa: BLE001
            log.info("enriquecimiento en segundo plano: %s", e)

    def _loop(self) -> None:
        now = time.monotonic()
        plan = self._plan()
        for name, _every, delay, _cond, _act in plan:
            self._next[name] = now + delay
        while not self._stop.wait(5):
            now = time.monotonic()
            for name, every, _delay, cond, act in plan:
                if now < self._next.get(name, 0):
                    continue
                self._next[name] = now + every
                try:
                    if cond():
                        act()
                except Exception:  # noqa: BLE001
                    log.exception("tarea periódica %s falló", name)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()


scheduler = Scheduler()
