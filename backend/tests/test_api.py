from __future__ import annotations


def ctx(**kw):
    return {"context": kw}


def titles(deck):
    return [c["title"] for c in deck]


def test_health_and_bootstrap(client):
    assert client.get("/api/health").json()["ok"] is True
    b = client.get("/api/bootstrap").json()
    assert len(b["moods"]) == 12 and {m["id"] for m in b["moods"]} >= {"reir", "miedo", "comfort"}
    assert b["stats"]["films"] >= 100          # catálogo semilla cargado al arrancar
    assert b["needs_onboarding"] is True        # sin historial todavía
    assert len(b["reasons"]) == 15
    assert b["configured"] == {"tmdb": False, "jellyfin": False, "jellyseerr": False, "radarr": False,
                               "llm": False, "letterboxd": False}


def test_cold_start_session_works(client):
    d = client.post("/api/sessions", json=ctx(moods=["comfort"])).json()
    assert len(d["deck"]) == 8
    assert all(0 < c["match"] <= 99 for c in d["deck"])
    assert d["deck"][0]["reasons"], "cada sugerencia debe explicarse"


def test_session_respects_duration_and_company(demo_client):
    d = demo_client.post("/api/sessions", json=ctx(moods=["reir"], max_minutes=100, company="peques")).json()
    assert d["deck"], "debería haber opciones"
    for c in d["deck"]:
        assert c["runtime"] <= 100 + 15 or d["relaxed"], c["title"]
        assert set(c["genres"]) & {"Animación", "Familia"}, f"{c['title']} no es para peques"


def test_dismiss_with_reason_then_next_best_and_undo(demo_client):
    d = demo_client.post("/api/sessions", json=ctx(moods=["adrenalina"])).json()
    sid, first = d["session_id"], d["deck"][0]
    r = demo_client.post(f"/api/sessions/{sid}/feedback",
                         json={"film_id": first["id"], "action": "dismiss", "reason": "too_long"}).json()
    assert first["title"] not in titles(r["deck"])
    assert r["can_undo"] and r["dismissed"] == 1 and r["toast"]
    u = demo_client.post(f"/api/sessions/{sid}/undo").json()
    assert titles(u["deck"])[0] == first["title"]
    assert demo_client.post(f"/api/sessions/{sid}/undo").status_code == 409


def test_too_long_lowers_duration_cap(demo_client):
    d = demo_client.post("/api/sessions", json=ctx(moods=["pensar"])).json()
    long_film = max(d["deck"], key=lambda c: c["runtime"])
    r = demo_client.post(f"/api/sessions/{d['session_id']}/feedback",
                         json={"film_id": long_film["id"], "action": "dismiss", "reason": "too_long"}).json()
    assert r["effective"]["max_minutes"] and r["effective"]["max_minutes"] < long_film["runtime"]
    assert r["adjustments"], "el motivo debe ajustar las siguientes sugerencias"
    assert all(c["runtime"] < long_film["runtime"] for c in r["deck"])


def test_never_hides_film_for_good(demo_client):
    d = demo_client.post("/api/sessions", json=ctx(moods=["comfort"])).json()
    victim = d["deck"][0]
    demo_client.post(f"/api/sessions/{d['session_id']}/feedback",
                     json={"film_id": victim["id"], "action": "dismiss", "reason": "never"})
    d2 = demo_client.post("/api/sessions", json=ctx(moods=["comfort"])).json()
    assert victim["title"] not in titles(d2["deck"])


def test_save_to_parked_and_library(demo_client):
    d = demo_client.post("/api/sessions", json=ctx(moods=["romantico"])).json()
    pick = d["deck"][1]
    demo_client.post(f"/api/sessions/{d['session_id']}/feedback", json={"film_id": pick["id"], "action": "save"})
    lib = demo_client.get("/api/library", params={"tab": "parked"}).json()
    assert pick["title"] in titles(lib["items"]) and lib["counts"]["parked"] == 1


def test_accept_marks_watching(demo_client):
    d = demo_client.post("/api/sessions", json=ctx(moods=["pensar"])).json()
    pick = d["deck"][0]
    demo_client.post(f"/api/sessions/{d['session_id']}/feedback", json={"film_id": pick["id"], "action": "accept"})
    lib = demo_client.get("/api/library", params={"tab": "watching"}).json()
    assert pick["title"] in titles(lib["items"])


def test_seen_excludes_and_state_roundtrip(demo_client):
    d = demo_client.post("/api/sessions", json=ctx(moods=["reir"])).json()
    pick = d["deck"][0]
    s = demo_client.post(f"/api/films/{pick['id']}/state",
                         json={"status": "watched", "rating": 4.5, "liked": True}).json()
    assert s["status"] == "watched" and s["my_rating"] == 4.5
    d2 = demo_client.post("/api/sessions", json=ctx(moods=["reir"])).json()
    assert pick["title"] not in titles(d2["deck"])
    d3 = demo_client.post("/api/sessions", json=ctx(moods=["reir"], allow_seen=True)).json()
    assert d3["deck"]


def test_update_context_changes_deck(demo_client):
    d = demo_client.post("/api/sessions", json=ctx(moods=["miedo"])).json()
    r = demo_client.put(f"/api/sessions/{d['session_id']}/context", json={"moods": ["comfort"], "company": "solo"})
    assert r.status_code == 200
    assert titles(r.json()["deck"]) != titles(d["deck"])


def test_genre_filters(demo_client):
    d = demo_client.post("/api/sessions", json=ctx(genres_in=["Terror"])).json()
    assert d["deck"] and all("Terror" in c["genres"] for c in d["deck"][:3])
    d2 = demo_client.post("/api/sessions", json=ctx(moods=["comfort"], genres_out=["Animación"])).json()
    assert all("Animación" not in c["genres"] for c in d2["deck"])


def test_evaluate_verdict(demo_client):
    d = demo_client.post("/api/sessions", json=ctx(moods=["comfort"])).json()
    good = d["deck"][0]
    ok = demo_client.post(f"/api/films/{good['id']}/evaluate", json=ctx(moods=["comfort"])).json()
    assert ok["verdict"] in ("go", "maybe")
    bad = demo_client.post(f"/api/films/{good['id']}/evaluate", json=ctx(moods=["comfort"], company="peques",
                                                                         max_minutes=40)).json()
    assert bad["verdict"] == "skip" and bad["warnings"]


def test_parse_context_rules(client):
    r = client.post("/api/context/parse", json={"text": "Estoy cansado, quiero reírme y tengo hora y media, en pareja"})
    j = r.json()
    assert j["source"] == "rules"
    assert j["context"]["moods"] == ["reir"] and j["context"]["max_minutes"] == 90
    assert j["context"]["company"] == "pareja" and j["context"]["focus"] == 1


def test_taste_profile_after_demo(demo_client):
    t = demo_client.get("/api/taste").json()
    assert t["n_rated"] >= 25 and t["genres_up"] and t["favorites"]
    assert 0 <= t["old_tolerance"] <= 1


def test_onboarding_calibrates(client):
    items = client.get("/api/onboarding").json()["items"]
    assert len(items) >= 8
    loved = [{"film_id": i["id"], "rating": 5.0} for i in items[:4]]
    r = client.post("/api/onboarding", json={"items": loved})
    assert r.status_code == 200, r.text
    assert client.get("/api/bootstrap").json()["needs_onboarding"] is False


def test_paths(demo_client):
    p = demo_client.get("/api/paths").json()
    assert len(p["paths"]) >= 8 and all(x["films"] and x["total"] == len(x["films"]) for x in p["paths"])


def test_search_local(demo_client):
    r = demo_client.get("/api/search", params={"q": "matrix"}).json()
    assert any(x["title"] == "Matrix" for x in r["results"])


def test_not_configured_errors_are_friendly(client):
    r = client.post("/api/sync/jellyfin")
    assert r.status_code == 409 and "Jellyfin" in r.json()["detail"]
    assert client.post("/api/sync/expand").status_code == 409
    d = client.post("/api/sessions", json=ctx()).json()
    assert client.post(f"/api/films/{d['deck'][0]['id']}/request").status_code == 409


def test_unknown_session_404(client):
    assert client.get("/api/sessions/nope").status_code == 404


def test_validation_error_is_json(client):
    r = client.post("/api/sessions/x/feedback", json={"film_id": "a"})
    assert r.status_code == 422 and "detail" in r.json()


def test_demo_clear(demo_client):
    assert demo_client.delete("/api/demo/history").json()["removed"] > 20
    assert demo_client.get("/api/bootstrap").json()["needs_onboarding"] is True
