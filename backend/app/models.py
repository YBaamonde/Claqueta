from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .util import utcnow


class Base(DeclarativeBase):
    pass


class Profile(Base):
    """Perfil de gustos. Hoy hay uno por defecto, pero todo cuelga de profile_id."""

    __tablename__ = "profile"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    color: Mapped[str] = mapped_column(String(16), default="#f5a524")
    taste_adjust: Mapped[dict] = mapped_column(JSON, default=dict)  # derivado del log de feedback
    last_context: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Film(Base):
    __tablename__ = "film"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tmdb_id: Mapped[int | None] = mapped_column(Integer, unique=True, index=True, nullable=True)
    imdb_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    jellyfin_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    letterboxd_uri: Mapped[str | None] = mapped_column(String(120), nullable=True)

    title: Mapped[str] = mapped_column(String(300))
    original_title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    norm_title: Mapped[str] = mapped_column(String(300), index=True, default="")
    norm_alt: Mapped[str] = mapped_column(String(300), index=True, default="")  # título original normalizado
    year: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    release_date: Mapped[str | None] = mapped_column(String(12), nullable=True)
    runtime: Mapped[int | None] = mapped_column(Integer, nullable=True)
    overview: Mapped[str | None] = mapped_column(Text, nullable=True)
    tagline: Mapped[str | None] = mapped_column(String(300), nullable=True)

    genres: Mapped[list] = mapped_column(JSON, default=list)
    directors: Mapped[list] = mapped_column(JSON, default=list)
    cast: Mapped[list] = mapped_column(JSON, default=list)
    countries: Mapped[list] = mapped_column(JSON, default=list)
    original_language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    min_age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    adult: Mapped[bool] = mapped_column(Boolean, default=False)

    poster_path: Mapped[str | None] = mapped_column(String(120), nullable=True)
    backdrop_path: Mapped[str | None] = mapped_column(String(120), nullable=True)
    trailer_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    vote_average: Mapped[float | None] = mapped_column(Float, nullable=True)
    vote_count: Mapped[int] = mapped_column(Integer, default=0)
    popularity: Mapped[float] = mapped_column(Float, default=0.0)

    providers: Mapped[dict] = mapped_column(JSON, default=dict)  # {"flatrate": [...], "rent": [...], "link": ...}
    providers_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    attrs: Mapped[dict] = mapped_column(JSON, default=dict)  # ver engine/attrs.py
    attrs_source: Mapped[str] = mapped_column(String(12), default="none")  # none|heuristic|llm|seed
    attrs_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    seerr_status: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 2 pend, 3 proc, 4 parcial, 5 disp
    seerr_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    source: Mapped[str] = mapped_column(String(12), default="tmdb")  # seed|tmdb|jellyfin|letterboxd
    details_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # None = ficha parcial
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (Index("ix_film_title_year", "norm_title", "year"),)


class UserFilm(Base):
    __tablename__ = "user_film"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profile.id"), index=True, default=1)
    film_id: Mapped[int] = mapped_column(ForeignKey("film.id"), index=True)
    # watched | watchlist | parked | watching | never | none
    status: Mapped[str] = mapped_column(String(12), default="none", index=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0.5 – 5
    liked: Mapped[bool] = mapped_column(Boolean, default=False)
    watched_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    rewatch: Mapped[bool] = mapped_column(Boolean, default=False)
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="app")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("profile_id", "film_id", name="uq_user_film"),)


class FilmEdge(Base):
    """Relación «A lleva a B» obtenida de TMDB (recomendaciones/similares)."""

    __tablename__ = "film_edge"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    src_id: Mapped[int] = mapped_column(ForeignKey("film.id"), index=True)
    dst_id: Mapped[int] = mapped_column(ForeignKey("film.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10), default="rec")
    __table_args__ = (UniqueConstraint("src_id", "dst_id", "kind", name="uq_edge"),)


class RecoSession(Base):
    __tablename__ = "reco_session"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profile.id"), default=1)
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    events: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class FeedbackEvent(Base):
    """Log inmutable de decisiones: alimenta estadísticas y el aprendizaje a largo plazo."""

    __tablename__ = "feedback_event"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(Integer, index=True, default=1)
    session_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    film_id: Mapped[int] = mapped_column(ForeignKey("film.id"), index=True)
    action: Mapped[str] = mapped_column(String(12))  # dismiss|save|accept|seen|never|snooze
    reason: Mapped[str | None] = mapped_column(String(24), nullable=True)
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    undone: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Setting(Base):
    __tablename__ = "setting"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=True)


class PitchCache(Base):
    __tablename__ = "pitch_cache"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
