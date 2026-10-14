"""Integraciones con servicios externos simulados (httpx.MockTransport): nada sale a Internet."""
from __future__ import annotations

import io
import json
import time
import zipfile

import httpx
import pytest


def wait_job(client, job, timeout=15):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{job['id']}").json()
        if j["state"] in ("done", "error"):
            return j
        time.sleep(.05)
    raise AssertionError(f"la tarea no terminó: {j}")


def mock_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="")


# --------------------------------------------------------------------------- Letterboxd

WATCHED = "Date,Name,Year,Letterboxd URI\n2024-01-01,Casablanca,1942,https://boxd.it/a\n2024-01-02,Parasite,2019,https://boxd.it/b\n"
RATINGS = "Date,Name,Year,Letterboxd URI,Rating\n2024-01-01,Casablanca,1942,https://boxd.it/a,2.0\n2024-01-02,Parasite,2019,https://boxd.it/b,5.0\n"
DIARY = ("Date,Name,Year,Letterboxd URI,Rating,Rewatch,Tags,Watched Date\n"
         "2024-02-01,Whiplash,2014,https://boxd.it/c,4.5,,,2024-01-30\n")
WATCHLIST = "Date,Name,Year,Letterboxd URI\n2024-03-01,Seven Samurai,1954,https://boxd.it/d\n2024-03-01,Una peli rarísima,1999,https://boxd.it/e\n"
LIKES = "Date,Name,Year,Letterboxd URI\n2024-01-02,Parasite,2019,https://boxd.it/b\n"


def test_letterboxd_zip_import(client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("watched.csv", WATCHED)
        z.writestr("ratings.csv", RATINGS)
        z.writestr("diary.csv", DIARY)
        z.writestr("watchlist.csv", WATCHLIST)
        z.writestr("likes/films.csv", LIKES)
    r = client.post("/api/import/letterboxd", files=[("files", ("letterboxd-export.zip", buf.getvalue(), "application/zip"))])
    assert r.status_code == 200, r.text
    res = wait_job(client, r.json())
    assert res["state"] == "done", res
    assert res["result"]["watched"] == 3 and res["result"]["watchlist"] == 2

    lib = client.get("/api/library", params={"tab": "watched"}).json()
    by_title = {i["title"].lower(): i for i in lib["items"]}
    assert lib["counts"]["watched"] == 3
    assert any(i["my_rating"] == 2.0 for i in lib["items"])         # Casablanca 2★ (le pareció un tostón)
    assert any(i["my_rating"] == 5.0 and i["liked"] for i in lib["items"])
    wl = client.get("/api/library", params={"tab": "watchlist"}).json()
    assert wl["counts"]["watchlist"] == 2                           # incluida una que no existe en el catálogo
    assert client.get("/api/bootstrap").json()["needs_onboarding"] is False
    # lo importado alimenta el gusto: ya no es arranque en frío
    assert client.get("/api/taste").json()["n_rated"] >= 3


def test_letterboxd_loose_csv_and_bad_input(client):
    r = client.post("/api/import/letterboxd", files=[("files", ("ratings.csv", RATINGS.encode(), "text/csv"))])
    assert r.status_code == 200
    assert wait_job(client, r.json())["state"] == "done"
    bad = client.post("/api/import/letterboxd", files=[("files", ("notes.txt", b"hola", "text/plain"))])
    assert bad.status_code == 400 and "CSV" in bad.json()["detail"]
    broken = client.post("/api/import/letterboxd", files=[("files", ("x.zip", b"PK\x03\x04garbage", "application/zip"))])
    assert broken.status_code == 400


def test_import_is_idempotent_and_does_not_touch_letterboxd(client):
    for _ in range(2):
        r = client.post("/api/import/letterboxd", files=[("files", ("watched.csv", WATCHED.encode(), "text/csv"))])
        assert wait_job(client, r.json())["state"] == "done"
    assert client.get("/api/library", params={"tab": "watched"}).json()["counts"]["watched"] == 2
    # nada se escribe en Letterboxd: lo que exporta la app es solo lo registrado *aquí*
    csv = client.get("/api/export/letterboxd/diary").text
    assert "Casablanca" not in csv


def test_rss_parse():
    from app.services.letterboxd import parse_rss

    xml = """<?xml version="1.0"?><rss xmlns:letterboxd="https://letterboxd.com" xmlns:tmdb="https://themoviedb.org" version="2.0">
    <channel><item><title>Parasite, 2019 - ★★★★★</title><link>https://letterboxd.com/u/film/parasite/</link>
    <letterboxd:watchedDate>2026-09-30</letterboxd:watchedDate><letterboxd:rewatch>No</letterboxd:rewatch>
    <letterboxd:filmTitle>Parasite</letterboxd:filmTitle><letterboxd:filmYear>2019</letterboxd:filmYear>
    <letterboxd:memberRating>5.0</letterboxd:memberRating><letterboxd:memberLike>Yes</letterboxd:memberLike>
    <tmdb:movieId>496243</tmdb:movieId></item>
    <item><title>Mi lista</title><link>https://letterboxd.com/u/list/x/</link></item></channel></rss>"""
    es = parse_rss(xml)
    assert len(es) == 1 and es[0].title == "Parasite" and es[0].rating == 5.0 and es[0].liked
    assert es[0].tmdb_id == 496243 and str(es[0].watched_date) == "2026-09-30"


def test_export_csv_formats(demo_client):
    d = demo_client.post("/api/sessions", json={"context": {"moods": ["reir"]}}).json()
    pick = d["deck"][0]
    demo_client.post(f"/api/films/{pick['id']}/state", json={"status": "watched", "rating": 4.0,
                                                           "watched_date": "2026-10-01"})
    csv = demo_client.get("/api/export/letterboxd/diary")
    assert csv.headers["content-type"].startswith("text/csv")
    body = csv.text.lstrip("﻿")
    assert body.splitlines()[0] == "Title,Year,WatchedDate,Rating10,Rewatch,Liked"
    assert "2026-10-01" in body and ",8," in body             # 4★ → 8/10
    assert demo_client.get("/api/export/letterboxd/nope").status_code == 404


# --------------------------------------------------------------------------- Jellyfin / Jellyseerr / Radarr

def jellyfin_handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path
    if p == "/System/Info/Public":
        return httpx.Response(200, json={"Id": "srv123"})
    if p == "/System/Info":
        return httpx.Response(200, json={"ServerName": "Homeserver", "Version": "10.10", "Id": "srv123"})
    if p == "/Users":
        return httpx.Response(200, json=[{"Id": "u1", "Policy": {"IsAdministrator": True}}])
    movie = lambda i, n, y, **kw: {"Id": i, "Name": n, "ProductionYear": y, "RunTimeTicks": 6_000_000_000 * 2,
                                   "Genres": ["Drama"], "ProviderIds": {}, **kw}
    if p == "/Items":
        items = [movie("jf1", "Casablanca", 1942), movie("jf2", "Seven Samurai", 1954),
                 movie("jf3", "Película casera", 2020)]
        return httpx.Response(200, json={"Items": items, "TotalRecordCount": 3})
    if p == "/Users/u1/Items":
        items = [movie("jf1", "Casablanca", 1942, UserData={"Played": True, "LastPlayedDate": "2026-09-20T20:00:00Z"})]
        return httpx.Response(200, json={"Items": items, "TotalRecordCount": 1})
    return httpx.Response(404)


@pytest.fixture()
def jellyfin(client, monkeypatch):
    from app.services import catalog
    from app.services.jellyfin import Jellyfin

    client.put("/api/settings", json={"values": {"jellyfin_url": "http://jf.test:8096", "jellyfin_api_key": "k",
                                                  "jellyfin_public_url": "http://nas:8096"}})
    monkeypatch.setattr(catalog, "jellyfin_client", lambda: Jellyfin(
        "http://jf.test:8096", "k", "", "http://nas:8096", client=mock_client(jellyfin_handler)))
    return client


def test_jellyfin_sync_links_library_and_history(jellyfin):
    c = jellyfin
    j = wait_job(c, c.post("/api/sync/jellyfin").json())
    assert j["state"] == "done", j
    assert j["result"]["items"] == 3 and j["result"]["history"] == 1
    lib = c.get("/api/library", params={"tab": "jellyfin"}).json()
    assert lib["counts"]["jellyfin"] == 3
    cas = next(i for i in lib["items"] if i["title"] == "Casablanca")
    assert cas["status"] == "watched"                                     # historial de reproducciones
    assert cas["availability"]["jellyfin"]["url"] == "http://nas:8096/web/#/details?id=jf1&serverId=srv123"
    # lo que ya está en casa se favorece cuando se pide «solo mi biblioteca»
    d = c.post("/api/sessions", json={"context": {"scope": "library", "allow_seen": True}}).json()
    assert d["deck"] and all(x["availability"]["jellyfin"]["available"] for x in d["deck"])
    ok = c.post("/api/settings/test/jellyfin").json()
    assert ok["ok"] is True and "Homeserver" in ok["message"]


def test_jellyfin_removed_items_are_pruned(jellyfin, monkeypatch):
    from app.services import catalog
    from app.services.jellyfin import Jellyfin

    wait_job(jellyfin, jellyfin.post("/api/sync/jellyfin").json())

    def h2(request):
        r = jellyfin_handler(request)
        if request.url.path == "/Items":
            return httpx.Response(200, json={"Items": [json.loads(r.content)["Items"][0]], "TotalRecordCount": 1})
        return r

    monkeypatch.setattr(catalog, "jellyfin_client",
                        lambda: Jellyfin("http://jf.test:8096", "k", "", "", client=mock_client(h2)))
    j = wait_job(jellyfin, jellyfin.post("/api/sync/jellyfin").json())
    assert j["result"]["removed"] == 2
    assert jellyfin.get("/api/library", params={"tab": "jellyfin"}).json()["counts"]["jellyfin"] == 1


def test_jellyseerr_request_flow(client, monkeypatch):
    from app.services import catalog
    from app.services.jellyseerr import Jellyseerr

    calls = []

    def h(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/v1/request":
            assert json.loads(request.content) == {"mediaType": "movie", "mediaId": 424}
            return httpx.Response(200, json={"id": 7, "media": {"status": 2}})
        return httpx.Response(404)

    client.put("/api/settings", json={"values": {"jellyseerr_url": "http://js.test:5055", "jellyseerr_api_key": "x",
                                                  "jellyseerr_public_url": "http://js.pub/"}})
    monkeypatch.setattr(catalog, "seerr_client", lambda: Jellyseerr("http://js.test:5055", "x", "http://js.pub",
                                                                    client=mock_client(h)))
    from app import db as database
    from app.models import Film

    with database.session_scope() as s:
        f = s.query(Film).filter(Film.title == "La lista de Schindler").first() or s.query(Film).first()
        f.tmdb_id = 424
        fid = f.id
    r = client.post(f"/api/films/{fid}/request")
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["availability"]["seerr"]["status"] == "pending"
    assert card["availability"]["seerr"]["url"] == "http://js.pub/movie/424"
    assert ("POST", "/api/v1/request") in calls
    assert client.get("/api/library", params={"tab": "requested"}).json()["counts"]["requested"] == 1


def test_radarr_progress_in_downloads(client, monkeypatch):
    from app import db as database
    from app.models import Film
    from app.services import catalog
    from app.services.radarr import Radarr

    def h(request):
        return httpx.Response(200, json={"records": [{"size": 1000, "sizeleft": 250, "timeleft": "00:10:00",
                                                       "trackedDownloadState": "downloading",
                                                       "movie": {"tmdbId": 555}}]})

    client.put("/api/settings", json={"values": {"radarr_url": "http://rd.test", "radarr_api_key": "x"}})
    monkeypatch.setattr(catalog, "radarr_client", lambda: Radarr("http://rd.test", "x", client=mock_client(h)))
    with database.session_scope() as s:
        f = s.query(Film).first()
        f.tmdb_id, f.seerr_status = 555, 3
    d = client.get("/api/downloads").json()
    assert d["radarr"] and d["items"][0]["download"]["pct"] == 75


# --------------------------------------------------------------------------- TMDB

def tmdb_handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path
    if p == "/3/configuration":
        return httpx.Response(200, json={"images": {}})
    if p == "/3/search/movie":
        return httpx.Response(200, json={"results": [{"id": 603, "title": "Matrix", "original_title": "The Matrix",
                                                     "release_date": "1999-03-30", "genre_ids": [28, 878],
                                                     "poster_path": "/abc12345.jpg", "vote_average": 8.2,
                                                     "vote_count": 25000, "popularity": 80}]})
    if p == "/3/movie/603":
        return httpx.Response(200, json={
            "id": 603, "title": "Matrix", "original_title": "The Matrix", "release_date": "1999-03-30", "runtime": 136,
            "genres": [{"id": 28, "name": "Action"}, {"id": 878, "name": "Science Fiction"}],
            "poster_path": "/abc12345.jpg", "vote_average": 8.2, "vote_count": 25000, "popularity": 80,
            "overview": "Un hacker descubre la verdad.", "original_language": "en",
            "credits": {"crew": [{"job": "Director", "name": "Lana Wachowski"}], "cast": [{"name": "Keanu Reeves", "order": 0}]},
            "keywords": {"keywords": [{"name": "simulation"}]}, "release_dates": {"results": []},
            "watch/providers": {"results": {"ES": {"flatrate": [{"provider_name": "Netflix", "logo_path": "/n.jpg"}]}}},
            "videos": {"results": []}, "external_ids": {"imdb_id": "tt0133093"}})
    return httpx.Response(404)


def test_tmdb_search_and_add(client, monkeypatch):
    from app.services import catalog
    from app.services.tmdb import TMDB

    client.put("/api/settings", json={"values": {"tmdb_api_key": "key123"}})
    monkeypatch.setattr(catalog, "tmdb_client", lambda: TMDB("key123", client=mock_client(tmdb_handler)))
    assert client.post("/api/settings/test/tmdb").json()["ok"] is True
    r = client.get("/api/search", params={"q": "the matrix reloaded zz"}).json()
    assert r["tmdb"] is True
    hit = next(x for x in r["results"] if x["kind"] == "tmdb")
    assert hit["poster"] == "/api/img/w342/abc12345.jpg"
    added = client.post("/api/films/from-tmdb", json={"tmdb_id": 603}).json()
    assert added["runtime"] == 136 and added["id"]
    card = client.get(f"/api/films/{added['id']}").json()
    assert card["directors"] == ["Lana Wachowski"] and card["attrs"]
    assert [p["name"] for p in card["availability"]["streaming"]] == ["Netflix"]


# --------------------------------------------------------------------------- Ajustes, auth, LLM, imágenes

def test_settings_mask_secrets_and_validate(client):
    r = client.put("/api/settings", json={"values": {"tmdb_api_key": "abcdef1234567890", "region": "ES"}}).json()
    item = next(s for s in r["settings"] if s["key"] == "tmdb_api_key")
    assert item["is_set"] and "abcdef1234567890" not in json.dumps(r) and "•" in item["value"]
    # reenviar el valor enmascarado no sobrescribe el secreto
    client.put("/api/settings", json={"values": {"tmdb_api_key": item["value"]}})
    from app import settings_store as S

    assert S.get("tmdb_api_key") == "abcdef1234567890"
    assert client.put("/api/settings", json={"values": {"llm_extra_body": "{no json"}}).status_code == 400
    assert client.put("/api/settings", json={"values": {"llm_tpm": "abc"}}).status_code == 400
    w = client.put("/api/settings", json={"weights": {"taste": 0.5}}).json()["weights"]
    assert w["taste"]["value"] == 0.5 and w["mood"]["value"] == w["mood"]["default"]
    assert client.post("/api/settings/test/nada").status_code == 404
    assert client.post("/api/settings/test/jellyfin").json()["ok"] is False


def test_weights_change_ranking(demo_client):
    base = demo_client.post("/api/sessions", json={"context": {"moods": ["reir"]}}).json()["deck"]
    demo_client.put("/api/settings", json={"weights": {"mood": 0.0, "quality": 0.4, "taste": 0.0}})
    other = demo_client.post("/api/sessions", json={"context": {"moods": ["reir"]}}).json()["deck"]
    assert [c["id"] for c in base] != [c["id"] for c in other]


def test_password_protection(env):
    env.setenv("ACCESS_PASSWORD", "claqueta!")
    from app import config
    from fastapi.testclient import TestClient

    from app.main import create_app

    config.reset_env()
    with TestClient(create_app()) as c:
        assert c.get("/api/health").status_code == 200
        assert c.get("/api/auth/status").json() == {"required": True, "authenticated": False}
        assert c.get("/api/bootstrap").status_code == 401
        assert c.post("/api/auth/login", json={"password": "nope"}).status_code == 401
        assert c.post("/api/auth/login", json={"password": "claqueta!"}).status_code == 200
        assert c.get("/api/bootstrap").status_code == 200
        assert c.get("/api/auth/status").json()["authenticated"] is True
        c.post("/api/auth/logout")
        assert c.get("/api/bootstrap").status_code == 401
        c.cookies.set("claqueta_session", "9999999999.deadbeef")
        assert c.get("/api/bootstrap").status_code == 401


def test_llm_parse_and_pitch(demo_client, monkeypatch):
    from app.services import llm as llm_mod

    seen = {}

    def h(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen["auth"] = request.headers.get("authorization")
        user = body["messages"][1]["content"]
        if "Convierte" in body["messages"][0]["content"]:
            out = {"moods": ["miedo"], "company": "amigos", "max_minutes": 100, "explanation": "Terror corto con amigos"}
        else:
            out = {"pitch": "Es ágil y divertida: justo lo que pides esta noche."}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(out)}}],
                                         "usage": {"total_tokens": 120}})

    monkeypatch.setattr(llm_mod, "make_client", lambda timeout=60, **kw: mock_client(h))
    demo_client.put("/api/settings", json={"values": {"llm_base_url": "http://llm.test/v1", "llm_api_key": "sk-1",
                                                      "llm_model": "m"}})
    assert demo_client.get("/api/bootstrap").json()["configured"]["llm"] is True
    p = demo_client.post("/api/context/parse", json={"text": "algo de miedo corto con los colegas"}).json()
    assert p["source"] == "llm" and p["context"]["moods"] == ["miedo"] and p["context"]["max_minutes"] == 100
    assert seen["auth"] == "Bearer sk-1"
    d = demo_client.post("/api/sessions", json={"context": {"moods": ["reir"]}}).json()
    pitch = demo_client.post(f"/api/sessions/{d['session_id']}/pitch", json={"film_id": d["deck"][0]["id"]}).json()
    assert pitch["pitch"].startswith("Es ágil")
    again = demo_client.post(f"/api/sessions/{d['session_id']}/pitch", json={"film_id": d["deck"][0]["id"]}).json()
    assert again["source"] == "cache"
    assert demo_client.get("/api/bootstrap").json()["llm"]["used_today"] >= 120


def test_llm_failure_falls_back_to_rules(demo_client, monkeypatch):
    from app.services import llm as llm_mod

    monkeypatch.setattr(llm_mod, "make_client",
                        lambda timeout=60, **kw: mock_client(lambda r: httpx.Response(401, text="bad key")))
    demo_client.put("/api/settings", json={"values": {"llm_base_url": "http://llm.test/v1", "llm_model": "m"}})
    p = demo_client.post("/api/context/parse", json={"text": "quiero reír, hora y media"}).json()
    assert p["source"] == "rules" and p["context"]["max_minutes"] == 90


def test_llm_enrichment_updates_attrs(demo_client, monkeypatch, db):
    from app.models import Film
    from app.services import llm as llm_mod

    # una ficha sin atributos fiables (como las que llegan de TMDB)
    f = db.query(Film).filter(Film.title == "Matrix").one()
    f.attrs_source = "heuristic"
    db.commit()

    def h(request):
        body = json.loads(request.content)
        ids = [int(x) for x in __import__("re").findall(r'"id":\s*(\d+)', body["messages"][1]["content"])]
        films = [{"id": i, **{k: .66 for k in ("pace", "intensity", "tension", "humor", "warmth", "darkness",
                                              "emotional", "complexity", "weirdness", "spectacle", "romance",
                                              "dated", "access", "family", "rewatch")}, "notes": "Ciencia ficción ágil"}
                 for i in ids]
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"films": films})}}],
                                         "usage": {"total_tokens": 500}})

    monkeypatch.setattr(llm_mod, "make_client", lambda timeout=60, **kw: mock_client(h))
    demo_client.put("/api/settings", json={"values": {"llm_base_url": "http://llm.test/v1", "llm_model": "m"}})
    j = wait_job(demo_client, demo_client.post("/api/sync/enrich").json())
    assert j["state"] == "done" and j["result"]["enriched"] >= 1, j
    db.expire_all()
    assert db.query(Film).filter(Film.title == "Matrix").one().attrs_source == "llm"


def test_image_proxy_caches(client, monkeypatch):
    from app.api import media

    hits = []

    def h(request):
        hits.append(str(request.url))
        return httpx.Response(200, content=b"\xff\xd8\xff fake jpeg", headers={"content-type": "image/jpeg"})

    monkeypatch.setattr(media, "_client", mock_client(h))
    r = client.get("/api/img/w500/abc12345.jpg")
    assert r.status_code == 200 and r.content.startswith(b"\xff\xd8")
    assert "immutable" in r.headers["cache-control"]
    assert client.get("/api/img/w500/abc12345.jpg").status_code == 200
    assert len(hits) == 1 and hits[0] == "https://image.tmdb.org/t/p/w500/abc12345.jpg"
    assert client.get("/api/img/w999/abc12345.jpg").status_code == 404
    assert client.get("/api/img/w500/..%2Fsecret.jpg").status_code == 404
    assert client.get("/api/img/w500/notanimage.exe").status_code == 404
