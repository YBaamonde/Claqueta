from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .moods import MOOD_IDS

COMPANIES = ["solo", "pareja", "amigos", "familia", "peques"]

# Épocas seleccionables en el compositor: (id, etiqueta, año_desde, año_hasta)
ERAS: list[tuple[str, str, int, int]] = [
    ("actual", "Actual (2010+)", 2010, 3000),
    ("dosmil", "Años 2000", 2000, 2009),
    ("ochenta_noventa", "80s y 90s", 1980, 1999),
    ("sesenta_setenta", "60s y 70s", 1960, 1979),
    ("edad_oro", "Edad de oro (hasta 1959)", 0, 1959),
]
ERA_RANGES = {e[0]: (e[2], e[3]) for e in ERAS}


class Context(BaseModel):
    """Lo que el usuario quiere *esta noche*. Es el contrato del compositor."""

    moods: list[str] = Field(default_factory=list)
    company: Literal["solo", "pareja", "amigos", "familia", "peques"] = "solo"
    max_minutes: int | None = None          # None = sin límite
    focus: int = 3                          # 1 zombi … 5 concentración total
    adventure: float = 0.35                 # 0 apuesta segura … 1 sorpréndeme
    eras: list[str] = Field(default_factory=list)
    genres_in: list[str] = Field(default_factory=list)
    genres_out: list[str] = Field(default_factory=list)
    scope: Literal["all", "library", "streaming"] = "all"
    subtitles_ok: bool = True
    anti_toston: bool = True
    allow_seen: bool = False

    @field_validator("moods")
    @classmethod
    def _moods(cls, v: list[str]) -> list[str]:
        return [m for m in dict.fromkeys(v) if m in MOOD_IDS][:3]

    @field_validator("eras")
    @classmethod
    def _eras(cls, v: list[str]) -> list[str]:
        return [e for e in dict.fromkeys(v) if e in ERA_RANGES]

    @field_validator("focus")
    @classmethod
    def _focus(cls, v: int) -> int:
        return max(1, min(5, int(v)))

    @field_validator("adventure")
    @classmethod
    def _adv(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))

    @field_validator("max_minutes")
    @classmethod
    def _mm(cls, v: int | None) -> int | None:
        if v is None:
            return None
        return max(40, min(400, int(v)))

    def signature(self) -> str:
        """Firma estable para cachear textos generados por LLM."""
        d = self.model_dump()
        return "|".join(f"{k}={d[k]}" for k in sorted(d))
