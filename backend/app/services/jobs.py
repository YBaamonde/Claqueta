from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from ..util import utcnow
from .errors import ServiceError

log = logging.getLogger("claqueta.jobs")


@dataclass
class Job:
    id: str
    kind: str
    title: str
    state: str = "queued"  # queued | running | done | error
    progress: int = 0
    total: int = 0
    message: str = ""
    error: str | None = None
    result: dict[str, Any] = field(default_factory=dict)
    started_at: str = ""
    finished_at: str | None = None

    def update(self, progress: int | None = None, total: int | None = None, message: str | None = None) -> None:
        if progress is not None:
            self.progress = progress
        if total is not None:
            self.total = total
        if message is not None:
            self.message = message

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class JobManager:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def running(self, kind: str) -> Job | None:
        with self._lock:
            return next((j for j in self.jobs.values() if j.kind == kind and j.state in ("queued", "running")), None)

    def _new(self, kind: str, title: str) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, title=title, started_at=utcnow().isoformat())
        with self._lock:
            self.jobs[job.id] = job
            if len(self.jobs) > 40:  # conserva solo los últimos
                for jid in list(self.jobs)[: len(self.jobs) - 40]:
                    if self.jobs[jid].state in ("done", "error"):
                        self.jobs.pop(jid, None)
        return job

    def _run(self, job: Job, fn: Callable[..., Any], args: tuple) -> None:
        job.state = "running"
        try:
            res = fn(job, *args)
            job.result = res if isinstance(res, dict) else {}
            job.state = "done"
        except ServiceError as e:
            job.state, job.error = "error", e.message
            log.warning("job %s falló: %s", job.kind, e.message)
        except Exception as e:  # noqa: BLE001
            job.state, job.error = "error", f"Error interno: {e.__class__.__name__}: {e}"
            log.exception("job %s falló", job.kind)
        finally:
            job.finished_at = utcnow().isoformat()

    def start(self, kind: str, title: str, fn: Callable[..., Any], *args: Any, unique: bool = True) -> Job:
        if unique:
            existing = self.running(kind)
            if existing:
                return existing
        job = self._new(kind, title)
        threading.Thread(target=self._run, args=(job, fn, args), daemon=True, name=f"job-{kind}").start()
        return job

    def run_sync(self, kind: str, title: str, fn: Callable[..., Any], *args: Any) -> Job:
        job = self._new(kind, title)
        self._run(job, fn, args)
        return job

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def recent(self, n: int = 12) -> list[dict[str, Any]]:
        with self._lock:
            return [j.as_dict() for j in list(self.jobs.values())[-n:]][::-1]


manager = JobManager()
