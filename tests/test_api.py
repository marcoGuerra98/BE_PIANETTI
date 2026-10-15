"""Test end-to-end via HTTP: codici di stato, upload, flussi principali."""

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def _team(client, h, nome):
    r = client.post("/teams", json={"nome": nome}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def test_validation_and_not_found_codes(client, auth_headers):
    h = auth_headers
    assert client.get("/players/00000000-0000-0000-0000-000000000000").status_code == 404
    assert client.get("/players/non-un-uuid").status_code == 422
    r = client.post("/players", json={"nome": "A", "cognome": "B", "ruolo": "XXX", "overall": 0}, headers=h)
    assert r.status_code == 422
    _team(client, h, "Alfa")
    assert client.post("/teams", json={"nome": "alfa"}, headers=h).status_code == 409


def test_player_photo_upload_flow(client, auth_headers, settings):
    h = auth_headers
    p = client.post("/players", json={"nome": "A", "cognome": "B", "ruolo": "ATT", "overall": 60}, headers=h).json()

    r = client.post(f"/players/{p['id']}/photo", files={"file": ("a.png", PNG, "image/png")}, headers=h)
    assert r.status_code == 200
    url = r.json()["foto"]
    assert url.startswith("/uploads/players/") and url.endswith(".png")
    assert client.get(url).content == PNG

    # sostituzione: il file vecchio viene cancellato
    r = client.post(f"/players/{p['id']}/photo", files={"file": ("a.jpg", JPEG, "image/jpeg")}, headers=h)
    new_url = r.json()["foto"]
    assert new_url.endswith(".jpg")
    assert client.get(url).status_code == 404

    r = client.delete(f"/players/{p['id']}/photo", headers=h)
    assert r.json()["foto"] is None
    assert list((settings.uploads_dir / "players").iterdir()) == []


def test_upload_rejects_wrong_type_and_size(client, auth_headers):
    h = auth_headers
    t = _team(client, h, "Beta")
    # estensione/Content-Type falsi: conta il contenuto
    r = client.post(f"/teams/{t['id']}/logo", files={"file": ("x.png", b"GIF89a....", "image/png")}, headers=h)
    assert r.status_code == 422
    big = PNG + b"0" * (2 * 1024 * 1024)
    r = client.post(f"/teams/{t['id']}/logo", files={"file": ("x.png", big, "image/png")}, headers=h)
    assert r.status_code == 413
    r = client.post(f"/teams/{t['id']}/logo", files={"file": ("x.png", PNG, "image/png")}, headers=h)
    assert r.status_code == 200 and r.json()["stemma"].startswith("/uploads/teams/")


def test_delete_team_conflict_then_force(client, auth_headers):
    h = auth_headers
    teams = [_team(client, h, n) for n in ("A", "B", "C", "D")]
    p = client.post(
        "/players",
        json={"nome": "X", "cognome": "Y", "ruolo": "ATT", "overall": 60, "squadra_id": teams[0]["id"]},
        headers=h,
    ).json()
    assert client.post("/schedule/generate", headers=h).status_code == 201
    assert client.post("/schedule/generate", headers=h).status_code == 409

    sched = client.get("/schedule").json()
    m = next(
        m for g in sched["giornate"] for m in g["partite"]
        if teams[0]["id"] in (m["squadra_casa_id"], m["squadra_trasferta_id"])
    )
    home = m["squadra_casa_id"] == teams[0]["id"]
    r = client.put(
        f"/matches/{m['id']}/result",
        json={
            "gol_casa": 1 if home else 0,
            "gol_trasferta": 0 if home else 1,
            "marcatori": [{"giocatore_id": p["id"], "goal": 1}],
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert client.get("/standings/scorers").json()[0]["goal"] == 1

    r = client.delete(f"/teams/{teams[0]['id']}", headers=h)
    assert r.status_code == 409
    assert r.json()["details"]["partite_giocate"]

    r = client.delete(f"/teams/{teams[0]['id']}?force=true", headers=h)
    assert r.status_code == 200
    assert r.json() == {"giocatori_svincolati": 1, "partite_rimosse": 3}
    assert client.get(f"/players/{p['id']}").json()["squadra_id"] is None
    assert client.get("/standings/scorers").json() == []


def test_full_tournament_via_api(client, auth_headers):
    h = auth_headers
    scorer = {}
    for n in ("Alfa", "Beta", "Gamma", "Delta"):
        t = _team(client, h, n)
        scorer[t["id"]] = client.post(
            "/players",
            json={"nome": "Bomber", "cognome": n, "ruolo": "ATT", "overall": 80, "squadra_id": t["id"]},
            headers=h,
        ).json()["id"]
    client.post("/schedule/generate", headers=h)

    def play_all(fase):
        for g in client.get("/schedule").json()["giornate"]:
            for m in g["partite"]:
                if m["fase"] == fase and not m["giocata"]:
                    body = {
                        "gol_casa": 1,
                        "gol_trasferta": 1,
                        "marcatori": [
                            {"giocatore_id": scorer[m["squadra_casa_id"]], "goal": 1},
                            {"giocatore_id": scorer[m["squadra_trasferta_id"]], "goal": 1},
                        ],
                    }
                    if fase != "GIRONE":
                        body["vincitore_rigori_id"] = m["squadra_casa_id"]
                    r = client.put(f"/matches/{m['id']}/result", json=body, headers=h)
                    assert r.status_code == 200, r.text

    play_all("GIRONE")
    fasi = [g["fase"] for g in client.get("/schedule").json()["giornate"]]
    assert fasi == ["GIRONE"] * 3 + ["SEMIFINALE"]

    play_all("SEMIFINALE")
    sched = client.get("/schedule").json()
    assert sched["giornate"][-1]["fase"] in ("FINALE_1_2", "FINALE_3_4")
    assert {m["fase"] for m in sched["giornate"][-1]["partite"]} == {"FINALE_1_2", "FINALE_3_4"}
    assert sched["girone_completato"] is True

    standings = client.get("/standings").json()
    assert [r["punti"] for r in standings] == [3, 3, 3, 3]
    # tutti pari: ordine alfabetico
    assert [r["squadra_nome"] for r in standings] == ["Alfa", "Beta", "Delta", "Gamma"]


def _assert_called_outside_event_loop(monkeypatch, service, method):
    """Sostituisce `service.method` con un wrapper che registra se è stato chiamato
    nel thread dell'event loop (cioè bloccandolo)."""
    import asyncio

    original = getattr(service, method)
    calls = []

    def wrapper(*args, **kwargs):
        try:
            asyncio.get_running_loop()
            calls.append("event-loop")
        except RuntimeError:
            calls.append("threadpool")
        return original(*args, **kwargs)

    monkeypatch.setattr(service, method, wrapper)
    return calls


def test_uploads_run_service_outside_event_loop(app, client, auth_headers, monkeypatch):
    """Regressione: gli endpoint di upload sono async, ma i service (I/O su file e
    FileLock) devono girare nel threadpool per non bloccare l'event loop."""
    h = auth_headers
    services = app.state.services
    photo_calls = _assert_called_outside_event_loop(monkeypatch, services.players, "set_photo")
    logo_calls = _assert_called_outside_event_loop(monkeypatch, services.teams, "set_logo")

    p = client.post("/players", json={"nome": "A", "cognome": "B", "ruolo": "ATT", "overall": 60}, headers=h).json()
    t = _team(client, h, "Alfa")
    r = client.post(f"/players/{p['id']}/photo", files={"file": ("a.png", PNG, "image/png")}, headers=h)
    assert r.status_code == 200, r.text
    r = client.post(f"/teams/{t['id']}/logo", files={"file": ("a.png", PNG, "image/png")}, headers=h)
    assert r.status_code == 200, r.text

    assert photo_calls == ["threadpool"]
    assert logo_calls == ["threadpool"]
