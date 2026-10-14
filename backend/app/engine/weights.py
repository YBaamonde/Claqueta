from __future__ import annotations

from .. import settings_store

DEFAULT_WEIGHTS: dict[str, float] = {
    "taste": 0.30,        # encaje con tu historial
    "mood": 0.27,         # encaje con el estado de ánimo elegido
    "quality": 0.13,      # valoración global (bayesiana)
    "focus": 0.08,        # exigencia vs. concentración disponible
    "company": 0.08,      # adecuación a la compañía
    "variety": 0.06,      # contraste con lo visto recientemente
    "availability": 0.05, # disponible ya (Jellyfin) > streaming > pedir
    "intent": 0.03,       # estaba en tu watchlist / en pendientes
    "anti_toston": 0.80,  # fuerza de la protección anti-tostón (0‒1)
    "toston_off": 0.20,   # fuerza residual si la desactivas
    "diversity": 0.12,    # penalización MMR entre sugerencias parecidas
}

# Metadatos para pintar los controles de «afinado» en Ajustes.
WEIGHT_META: list[dict] = [
    dict(key="taste", label="Mi gusto", help="Cuánto pesa lo que has valorado antes.", min=0, max=0.6),
    dict(key="mood", label="Estado de ánimo", help="Cuánto pesa el mood que elijas.", min=0, max=0.6),
    dict(key="quality", label="Calidad general", help="Valoración global de la película.", min=0, max=0.4),
    dict(key="focus", label="Concentración", help="Evita películas más exigentes que tu energía.", min=0, max=0.3),
    dict(key="company", label="Compañía", help="Ajuste a con quién la ves.", min=0, max=0.3),
    dict(key="variety", label="Variedad", help="Contraste con lo último que has visto.", min=0, max=0.3),
    dict(key="availability", label="Disponibilidad", help="Favorece lo que ya tienes en Jellyfin.", min=0, max=0.3),
    dict(key="anti_toston", label="Protección anti-tostón", help="Cuánto castiga a los clásicos que envejecen mal.", min=0, max=0.97),
    dict(key="diversity", label="Diversidad del carrusel", help="Evita sugerencias casi idénticas seguidas.", min=0, max=0.4),
]


def get_weights() -> dict[str, float]:
    w = dict(DEFAULT_WEIGHTS)
    override = settings_store.get("engine_weights", {}) or {}
    if isinstance(override, dict):
        for k, v in override.items():
            if k in w and isinstance(v, (int, float)):
                w[k] = float(v)
    return w
