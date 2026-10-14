from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

log = logging.getLogger("claqueta.db")

engine: Engine | None = None
SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False)

# Migraciones aditivas: (versión, [sentencias SQL]). create_all() crea lo nuevo;
# aquí van los ALTER TABLE de columnas añadidas a tablas ya existentes.
MIGRATIONS: list[tuple[int, list[str]]] = []


def configure(data_dir: Path) -> Engine:
    """Crea (o recrea) el engine apuntando a ``data_dir/claqueta.db``."""
    global engine
    data_dir.mkdir(parents=True, exist_ok=True)
    if engine is not None:
        engine.dispose()
    url = f"sqlite:///{(data_dir / 'claqueta.db').as_posix()}"
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30}, pool_pre_ping=True)

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _):  # pragma: no cover - trivial
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    SessionLocal.configure(bind=engine)
    return engine


def init_db() -> None:
    from . import models  # noqa: F401 (registra las tablas)

    assert engine is not None, "db.configure() no se ha llamado"
    models.Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"))
        current = conn.execute(text("SELECT MAX(version) FROM schema_version")).scalar() or 0
        for version, statements in MIGRATIONS:
            if version > current:
                for stmt in statements:
                    try:
                        conn.execute(text(stmt))
                    except Exception as exc:  # columna ya existente, etc.
                        log.warning("migración %s: %s", version, exc)
                conn.execute(text("INSERT INTO schema_version (version) VALUES (:v)"), {"v": version})
    with session_scope() as db:
        if not db.get(models.Profile, 1):
            db.add(models.Profile(id=1, name="Yo", color="#f5a524"))


def get_db() -> Iterator[Session]:
    """Sesión por petición. Las rutas que escriben llaman a ``db.commit()`` explícitamente."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
