"""Convierte la puntuación numérica en frases que un humano quiere leer."""
from __future__ import annotations

from typing import Any

from ..util import clamp
from .context import Context
from .moods import MOOD_BY_ID
from .recommend import Scored, aged_label, attrs_of, focus_demand
from .taste import Taste

LANG_NAMES = {
    "ja": "japonés", "fr": "francés", "it": "italiano", "de": "alemán", "ko": "coreano", "sv": "sueco",
    "ru": "ruso", "zh": "chino", "cn": "cantonés", "pt": "portugués", "da": "danés", "pl": "polaco", "cs": "checo",
    "hi": "hindi", "fa": "persa", "tr": "turco", "es": "español", "en": "inglés", "hu": "húngaro", "no": "noruego",
    "fi": "finés", "el": "griego", "nl": "neerlandés", "ar": "árabe", "he": "hebreo", "th": "tailandés",
    "ro": "rumano", "uk": "ucraniano", "ca": "catalán", "eu": "euskera", "gl": "gallego",
}

_ATTR_PHRASE = {
    "humor": "muy divertida", "emotional": "emotiva", "tension": "tensa", "pace": "trepidante",
    "spectacle": "espectacular", "warmth": "reconfortante", "romance": "romántica", "complexity": "para pensar",
    "weirdness": "rara y personal", "darkness": "oscura", "intensity": "intensa", "access": "fácil de ver",
}

COMPANY_PHRASE = {"pareja": "en pareja", "amigos": "con amigos", "familia": "en familia", "peques": "con peques"}


def _mood_hint(a: dict, ctx: Context) -> str:
    best: list[tuple[float, str]] = []
    for mid in ctx.moods:
        m = MOOD_BY_ID[mid]
        for k, t in m.targets.items():
            if k in _ATTR_PHRASE and t >= .6 and float(a.get(k, .5)) >= .6:  # solo lo que *esta* película tiene
                closeness = 1 - abs(float(a.get(k, .5)) - t)
                best.append((closeness * m.weights.get(k, 1.0), _ATTR_PHRASE[k]))
    best.sort(reverse=True)
    phrases = list(dict.fromkeys(p for _, p in best))[:2]
    return " y ".join(phrases)


def aged_note(risk: float, taste: Taste, year: int | None) -> str:
    if risk < .22:
        return "Se ve como si fuera de ayer." if (year or 2000) < 1990 else "No ha perdido ni un ápice de frescura."
    if risk < .45:
        return "Se nota la época, pero engancha igual."
    if risk < .68:
        extra = " Con tu historial, te compensará." if taste.old_tolerance >= .6 else ""
        return "Ritmo y estilo de su época: mejor verla con ganas." + extra
    return "Importante históricamente, pero hoy exige mucha paciencia."


def build_texts(s: Scored, ctx: Context, taste: Taste, seed_titles: dict[int, str]) -> dict[str, Any]:
    f = s.film
    a = attrs_of(f)
    reasons: list[tuple[float, str, str, str]] = []  # (fuerza, tipo, icono, texto)
    warns: list[tuple[str, str]] = []

    fx = s.facts
    if "director" in fx:
        d, n, avg = fx["director"]
        reasons.append((.95, "taste", "🎬", f"Dirigida por {d}, de quien has visto {n} (media {avg:.1f}★)"
                        if n > 1 else f"Dirigida por {d}, que te encantó ({avg:.1f}★)"))
    if fx.get("rec_from"):
        titles = [seed_titles[i] for i in fx["rec_from"] if i in seed_titles]
        if titles:
            reasons.append((.9, "taste", "💞", f"Porque te encantó «{titles[0]}»"))
    if "best_genre" in fx:
        g, aff, n, avg = fx["best_genre"]
        txt = (f"Se te da bien el género «{g.lower()}»: {n} vistas con {avg:.1f}★ de media" if n >= 2
               else f"Encaja con tu gusto por el género «{g.lower()}»")
        reasons.append((.55 + .3 * aff, "taste", "❤️", txt))
    if ctx.moods and s.contrib.get("mood", 0) > .035:
        hint = _mood_hint(a, ctx)
        labels = " + ".join(MOOD_BY_ID[m].label.lower() for m in ctx.moods[:2])
        reasons.append((min(.8, .55 + 2.5 * s.contrib["mood"]), "mood", MOOD_BY_ID[ctx.moods[0]].emoji,
                        f"Va con tu ánimo ({labels})" + (f": {hint}" if hint else "")))
    rt = f.runtime or 0
    if ctx.max_minutes and rt and rt <= ctx.max_minutes:
        left = ctx.max_minutes - rt
        reasons.append((.62, "time", "⏱️", f"Dura {rt} min" + (f" y te sobran {left}" if left >= 10 else ", justo a tu medida")))
    elif rt and rt <= 98:
        reasons.append((.4, "time", "⏱️", f"Cortita: {rt} min"))
    demand = focus_demand(f, a, ctx.subtitles_ok)
    if ctx.focus <= 2 and demand < .35:
        reasons.append((.6, "focus", "🔋", "Fácil de seguir aunque vengas con la cabeza apagada"))
    elif ctx.focus >= 4 and float(a.get("complexity", .4)) >= .62:
        reasons.append((.55, "focus", "🧠", "Merece tu concentración: tiene miga"))
    if ctx.company != "solo" and s.parts.get("company", 0) > .72:
        reasons.append((.5, "company", "👥", f"Muy buena para ver {COMPANY_PHRASE[ctx.company]}"))
    if s.aged_risk < .22 and (f.year or 2000) < 1985:
        reasons.append((.78, "aged", "🕰️", "Un clásico que ha envejecido de maravilla"))
    if s.parts.get("variety", 0) > .8 and taste.recent:
        reasons.append((.4, "variety", "🔀", "Un cambio de aires respecto a lo último que has visto"))
    if f.jellyfin_id:
        reasons.append((.5, "availability", "▶️", "Ya la tienes en Jellyfin"))
    elif (f.providers or {}).get("flatrate"):
        reasons.append((.35, "availability", "📺", "Disponible en streaming por suscripción"))
    if fx.get("intent") == "watchlist":
        reasons.append((.7, "intent", "🔖", "Estaba en tu watchlist de Letterboxd"))
    elif fx.get("intent") == "parked":
        reasons.append((.7, "intent", "📌", "La tenías guardada en Pendientes"))
    if (f.vote_average or 0) >= 7.8 and (f.vote_count or 0) >= 2000:
        reasons.append((.45, "quality", "⭐", f"Muy bien valorada ({f.vote_average:.1f}/10 con {f.vote_count // 1000}k votos)"))

    # --- avisos honestos ---
    if ctx.max_minutes and rt > ctx.max_minutes:
        warns.append(("time", f"Dura {rt} min, {rt - ctx.max_minutes} más de lo que querías"))
    lang = f.original_language
    if lang in ("xx", "zxx") or (f.year and f.year < 1930 and not lang):
        warns.append(("subs", "Cine mudo: con intertítulos"))
    elif lang and lang not in ("es", "en"):
        warns.append(("subs", f"VO en {LANG_NAMES.get(lang, lang)}, con subtítulos"))
    if float(a.get("pace", .5)) < .3:
        warns.append(("pace", "Ritmo contemplativo: dale tiempo"))
    if s.aged_risk >= .68:
        warns.append(("aged", "Más valiosa históricamente que entretenida hoy"))
    elif s.aged_risk >= .45:
        warns.append(("aged", "Se nota el paso del tiempo"))
    if float(a.get("darkness", .3)) > .78:
        warns.append(("dark", "Tema duro"))
    cap = (ctx.focus - 1) / 4 + .18
    if demand > cap + .05:
        warns.append(("focus", "Pide más concentración de la que traes"))

    reasons.sort(key=lambda r: -r[0])
    top = reasons[:4]

    # orden contextual de los motivos de descarte: primero lo que más probablemente moleste
    pains: list[tuple[float, str]] = []
    if (ctx.max_minutes and rt > ctx.max_minutes - 10) or rt > 150:
        pains.append((1.0, "too_long"))
    if float(a.get("pace", .5)) < .38:
        pains.append((.95, "too_slow"))
    if s.aged_risk >= .4:
        pains.append((.9, "too_dated"))
    if float(a.get("darkness", .3)) > .65:
        pains.append((.8, "too_heavy"))
    if float(a.get("weirdness", .3)) > .55:
        pains.append((.7, "too_weird"))
    if lang and lang not in ("es", "en", "xx", "zxx"):
        pains.append((.75, "subtitles"))
    if s.parts.get("variety", 1) < .45:
        pains.append((.7, "similar_recent"))
    if float(a.get("humor", .3)) > .6 and float(a.get("emotional", .4)) < .45:
        pains.append((.4, "too_light"))
    order = [c for _, c in sorted(pains, reverse=True)]
    base = ["not_mood", "genre_no", "seen", "too_known", "too_long", "too_slow", "too_dated", "too_heavy",
            "too_light", "too_weird", "people_no", "subtitles", "similar_recent", "later", "never"]
    for c in base:
        if c not in order:
            order.append(c)

    synopsis = (a.get("notes") or (f.overview or "").split(". ")[0]).strip()
    return {
        "reasons": [{"kind": k, "icon": i, "text": t} for _, k, i, t in top],
        "warnings": [{"kind": k, "text": t} for k, t in warns[:4]],
        "aged": {"risk": round(s.aged_risk, 2), "label": aged_label(s.aged_risk),
                 "note": aged_note(s.aged_risk, taste, f.year)},
        "pitch": synopsis[:240],
        "suggested_reasons": order,
    }


def match_percent(score: float) -> int:
    return int(round(55 + 44 * clamp((score - .40) / .50)))
