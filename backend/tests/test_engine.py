"""Motor de recomendación: reglas de negocio que más importan (anti-tostón, mood, tiempo, aprendizaje)."""
from __future__ import annotations

from app.engine import feedback as fb
from app.engine import recommend as rec
from app.engine.context import Context
from app.engine.taste import build_taste
from app.models import Film, RecoSession, UserFilm
from app.services import demo
from app.util import norm_title


def top(db, ctx=None, events=None, limit=8):
    return rec.rank(db, 1, ctx or Context(), events or [], limit=limit)


def by_title(db, title):
    return db.query(Film).filter(Film.title == title).one()


def test_norm_title_is_unicode_aware():
    assert norm_title("Amélie") == norm_title("Amelie") == "amelie"
    assert norm_title("The Godfather") == norm_title("godfather")
    assert norm_title("七人の侍") == "七人の侍"                    # no se queda en blanco con CJK
    assert norm_title("2001: A Space Odyssey") == "2001 a space odyssey"


def test_context_validation():
    c = Context(moods=["reir", "reir", "nope", "miedo", "llorar", "comfort"], focus=99, adventure=7, max_minutes=5,
                eras=["edad_oro", "x"])
    assert c.moods == ["reir", "miedo", "llorar"] and c.focus == 5 and c.adventure == 1.0
    assert c.max_minutes == 40 and c.eras == ["edad_oro"]
    assert Context(moods=["reir"]).signature() == Context(moods=["reir"]).signature()


def test_hard_time_gate(demo_client, db):
    res = top(db, Context(max_minutes=95))
    assert res.items and all((s.film.runtime or 0) <= 95 + 10 for s in res.items)


def test_mood_drives_genre(demo_client, db):
    scary = top(db, Context(moods=["miedo"]), limit=5)
    assert sum(1 for s in scary.items if {"Terror", "Suspense"} & set(s.film.genres)) >= 4
    funny = top(db, Context(moods=["reir"]), limit=5)
    assert sum(1 for s in funny.items if "Comedia" in s.film.genres) >= 4
    cry = top(db, Context(moods=["llorar"]), limit=5)
    assert sum(1 for s in cry.items if "Drama" in s.film.genres) >= 4


def test_peques_only_family_content(demo_client, db):
    res = top(db, Context(company="peques", moods=["comfort"]))
    assert res.items and all({"Animación", "Familia"} & set(s.film.genres) for s in res.items)
    assert all((s.film.min_age or 0) <= 12 for s in res.items)


def test_anti_toston_penalises_dated_classics_for_newcomers(demo_client, db):
    """Perfil «recién llegado»: puntúa mal los clásicos lentos → Metropolis/Kane no deben liderar."""
    taste = build_taste(db, 1)
    assert taste.old_tolerance < .35
    met = by_title(db, "Metrópolis")
    on = rec.evaluate(db, 1, met, Context(allow_seen=True, anti_toston=True))
    off = rec.evaluate(db, 1, met, Context(allow_seen=True, anti_toston=False))
    assert on.aged_risk >= .5
    assert on.score < off.score - .03, (on.score, off.score)
    res = top(db, Context(), limit=12)
    assert not any((s.film.year or 2000) < 1940 for s in res.items), [s.film.title for s in res.items]


def test_good_classics_survive_anti_toston(demo_client, db):
    """Que se proteja de tostones no significa esconder los clásicos que sí envejecen bien."""
    ctx = Context(eras=["edad_oro"], moods=["intriga"])
    res = top(db, ctx, limit=6)
    titles = [s.film.title for s in res.items]
    assert len(titles) >= 4
    assert any(t in titles for t in ("La ventana indiscreta", "Con faldas y a lo loco", "Psicosis", "Chinatown",
                                    "Vértigo", "El tercer hombre", "Casablanca", "Ciudadano Kane")), titles
    risks = {s.film.title: s.aged_risk for s in res.items}
    assert min(risks.values()) < .35, risks


def test_old_tolerance_grows_with_old_film_love(client, db):
    """Quien disfruta de los clásicos recibe más clásicos: la tolerancia se aprende, no se impone."""
    demo.load_seed(db)
    demo.ensure_attrs_all(db)
    for title, r in (("Casablanca", 5), ("Ciudadano Kane", 4.5), ("Psicosis", 5), ("Metrópolis", 4.5),
                     ("Los siete samurais", 5), ("Matrix", 3.5), ("Origen", 3.5), ("Interstellar", 3.5)):
        f = db.query(Film).filter(Film.title == title).first()
        if f:
            db.add(UserFilm(profile_id=1, film_id=f.id, status="watched", rating=r, source="app"))
    db.commit()
    from app.engine import taste

    taste.invalidate()
    t = build_taste(db, 1)
    assert t.old_tolerance > .55, t.old_tolerance


def test_single_rating_does_not_create_favorite_director(client, db):
    demo.load_seed(db)
    demo.ensure_attrs_all(db)
    f = db.query(Film).filter(Film.directors.isnot(None)).first()
    db.add(UserFilm(profile_id=1, film_id=f.id, status="watched", rating=5, source="app"))
    db.commit()
    t = build_taste(db, 1)
    assert all(abs(v) < .5 for v in t.director.values())


def test_diversity_in_deck(demo_client, db):
    res = top(db, Context(moods=["pensar"]), limit=8)
    directors = [d for s in res.items for d in s.film.directors[:1]]
    assert max(directors.count(d) for d in set(directors)) <= 2
    assert len({s.film.id for s in res.items}) == len(res.items)


def test_session_events_adjust_and_undo(demo_client, db):
    s = RecoSession(id="t1", profile_id=1, context={}, events=[])
    db.add(s)
    first = top(db).items[0].film
    msg = fb.record_event(db, s, first, "dismiss", "too_slow")
    assert msg and s.events and s.events[-1]["reason"] == "too_slow"
    nxt = top(db, events=s.events)
    assert first.id not in [x.film.id for x in nxt.items]
    assert nxt.adj.summary, "debe describir el ajuste aplicado"
    restored = fb.undo_last(db, s)
    assert restored.id == first.id and not s.events
    db.commit()


def test_seen_reason_marks_watched_and_later_snoozes(demo_client, db):
    s = RecoSession(id="t2", profile_id=1, context={}, events=[])
    db.add(s)
    a, b = [x.film for x in top(db).items[:2]]
    fb.record_event(db, s, a, "dismiss", "seen")
    fb.record_event(db, s, b, "dismiss", "later")
    db.commit()
    ua = db.query(UserFilm).filter_by(film_id=a.id).one()
    ub = db.query(UserFilm).filter_by(film_id=b.id).one()
    assert ua.status == "watched" and ub.snoozed_until is not None
    fb.undo_last(db, s)
    db.commit()
    db.refresh(ub)
    assert ub.snoozed_until is None


def test_long_term_learning_from_dismissals(demo_client, db):
    horror = [f for f in db.query(Film).all() if "Terror" in f.genres[:2]][:4]
    s = RecoSession(id="t3", profile_id=1, context={}, events=[])
    db.add(s)
    for f in horror:
        fb.record_event(db, s, f, "dismiss", "genre_no")
    adj = fb.recompute_adjust(db, 1)
    db.commit()
    assert adj["genre"].get("Terror", 0) < 0
    assert build_taste(db, 1).genre["Terror"] < 0


def test_relaxation_never_returns_empty_when_possible(demo_client, db):
    res = top(db, Context(max_minutes=40, genres_in=["Western"], eras=["actual"]))
    assert res.relaxed or res.items or res.empty_reason == "no_match"
    wide = top(db, Context(max_minutes=75, moods=["comfort"]))
    assert wide.items


def test_evaluate_ignores_gates_but_reports_them(demo_client, db):
    kane = by_title(db, "Ciudadano Kane")
    s = rec.evaluate(db, 1, kane, Context(company="peques", max_minutes=60))
    assert s.flags and any("compañía" in f for f in s.flags)
