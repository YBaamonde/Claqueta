"""Cliente mínimo para cualquier API compatible con OpenAI (Groq, Gemini, OpenRouter, Ollama…).

Pensado para planes *gratuitos*: limita los tokens por minuto, respeta ``Retry-After`` y lleva
la cuenta del gasto diario para no agotar la cuota.
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from datetime import date
from typing import Any

import httpx

from .. import settings_store
from .errors import NotConfigured, ServiceError
from .http import make_client

PRESETS: list[dict[str, str]] = [
    dict(id="groq", label="Groq (gratis)", base_url="https://api.groq.com/openai/v1", model="openai/gpt-oss-20b",
         extra='{"reasoning_effort":"low"}', tpm="6000",
         help="Cuenta gratuita en console.groq.com. Límite ~8k tokens/min en el plan free."),
    dict(id="gemini", label="Google Gemini (gratis)", base_url="https://generativelanguage.googleapis.com/v1beta/openai",
         model="gemini-flash-latest", extra="", tpm="20000",
         help="Clave gratuita en aistudio.google.com."),
    dict(id="openrouter", label="OpenRouter (modelos :free)", base_url="https://openrouter.ai/api/v1",
         model="openai/gpt-oss-20b:free", extra="", tpm="6000", help="Elige un modelo cuyo id acabe en :free."),
    dict(id="ollama", label="Ollama (local)", base_url="http://localhost:11434/v1", model="llama3.2", extra="",
         tpm="60000", help="Sin coste ni límites, pero necesita RAM/GPU en tu servidor."),
]


class LLMBusy(ServiceError):
    pass


class _Budget:
    """Ventana deslizante de tokens/minuto."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.window: deque[tuple[float, int]] = deque()

    def reserve(self, tokens: int, tpm: int, max_wait: float) -> None:
        deadline = time.monotonic() + max_wait
        while True:
            with self.lock:
                now = time.monotonic()
                while self.window and now - self.window[0][0] > 60:
                    self.window.popleft()
                used = sum(t for _, t in self.window)
                if used + tokens <= tpm or not self.window:
                    self.window.append((now, tokens))
                    return
                wait = 60 - (now - self.window[0][0]) + .2
            if time.monotonic() + wait > deadline:
                raise LLMBusy("El LLM está al límite de tokens por minuto; reintento enseguida")
            time.sleep(min(wait, 5))


_budget = _Budget()


def daily_used() -> int:
    d = settings_store.get_raw("x_llm_usage", {}) or {}
    return int(d.get("tokens", 0)) if d.get("day") == date.today().isoformat() else 0


def _add_usage(tokens: int) -> None:
    today = date.today().isoformat()
    d = settings_store.get_raw("x_llm_usage", {}) or {}
    if d.get("day") != today:
        d = {"day": today, "tokens": 0, "calls": 0}
    d["tokens"] = int(d.get("tokens", 0)) + tokens
    d["calls"] = int(d.get("calls", 0)) + 1
    settings_store.set_raw("x_llm_usage", d)


def extract_json(text: str) -> Any:
    """Extrae el primer objeto/array JSON de una respuesta, tolerando ```fences``` y texto alrededor."""
    if not text:
        raise ServiceError("El LLM devolvió una respuesta vacía")
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t[:4].lower() == "json":
            t = t[4:]
    dec = json.JSONDecoder()
    for i, ch in enumerate(t):
        if ch in "{[":
            try:
                obj, _ = dec.raw_decode(t[i:])
                return obj
            except ValueError:
                continue
    raise ServiceError("No pude interpretar la respuesta del LLM")


class LLM:
    def __init__(self, base_url: str, api_key: str, model: str, extra_body: dict | None = None, tpm: int = 6000,
                 client: httpx.Client | None = None):
        if not base_url or not model:
            raise NotConfigured("El LLM no está configurado")
        self.base_url, self.key, self.model = base_url.rstrip("/"), api_key, model
        self.extra = extra_body or {}
        self.tpm = tpm
        self.client = client or make_client(timeout=60)

    @classmethod
    def from_settings(cls) -> "LLM":
        raw = settings_store.get("llm_extra_body", "") or ""
        extra: dict = {}
        if isinstance(raw, dict):
            extra = raw
        elif raw.strip():
            try:
                extra = json.loads(raw)
            except ValueError:
                extra = {}
        return cls(settings_store.get("llm_base_url", ""), settings_store.get("llm_api_key", ""),
                   settings_store.get("llm_model", ""), extra, int(settings_store.get("llm_tpm", 6000) or 6000))

    def chat(self, system: str, user: str, *, json_mode: bool = True, max_tokens: int = 1400,
             temperature: float = .3, max_wait: float = 20.0) -> str:
        est = int((len(system) + len(user)) / 3.2) + max_tokens // 2
        _budget.reserve(est, self.tpm, max_wait)
        body: dict[str, Any] = {
            "model": self.model, "temperature": temperature, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            **self.extra,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
        for attempt in range(3):
            try:
                r = self.client.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
            except httpx.TimeoutException as e:
                raise ServiceError("El LLM tardó demasiado en responder") from e
            except httpx.HTTPError as e:
                raise ServiceError(f"No se pudo conectar con el LLM: {e.__class__.__name__}") from e
            if r.status_code == 400 and json_mode and "response_format" in body:
                body.pop("response_format")  # proveedor sin modo JSON: reintenta sin él
                continue
            if r.status_code == 429:
                wait = min(10.0, float(r.headers.get("retry-after", "3") or 3))
                if attempt == 2:
                    raise LLMBusy("El LLM está limitando las peticiones (429)", 429)
                time.sleep(wait)
                continue
            if r.status_code in (401, 403):
                raise ServiceError("El LLM rechazó la clave de API", r.status_code)
            if r.status_code >= 400:
                raise ServiceError(f"El LLM respondió {r.status_code}: {r.text[:160]}", r.status_code)
            data = r.json()
            usage = (data.get("usage") or {}).get("total_tokens") or est
            _add_usage(int(usage))
            msg = ((data.get("choices") or [{}])[0].get("message") or {})
            return msg.get("content") or ""
        raise ServiceError("El LLM no respondió")

    def chat_json(self, system: str, user: str, **kw: Any) -> Any:
        return extract_json(self.chat(system, user, json_mode=True, **kw))
