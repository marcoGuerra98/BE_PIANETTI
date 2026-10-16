"""Reset di fine torneo: POST /tournament/reset."""

from app.models.match import MarcatoreIn, ResultIn

from .conftest import ADMIN_PWD


def _setup_played_tournament(services, make_teams, make_player, find_match):
    a, b, c, d = make_teams(4)
    scorer = make_player(a, "Mario", "Rossi")
    make_player(b, "Luigi", "Verdi")
    make_player(None, "Gino", "Svincolato")
    services.schedule.generate()
    m = find_match(a.id, b.id)
    gc, gt = (2, 0) if m.squadra_casa_id == a.id else (0, 2)
    services.matches.set_result(
        m.id, ResultIn(gol_casa=gc, gol_trasferta=gt, marcatori=[MarcatoreIn(giocatore_id=scorer.id, goal=2)])
    )
    assert services.players.get(scorer.id).goal == 2
    return [a, b, c, d]


def _snapshot(services):
    return (
        [p.model_dump() for p in services.store.players.list()],
        [m.model_dump() for m in services.store.matches.list()],
        [t.model_dump() for t in services.store.teams.list()],
    )


def test_reset_with_correct_password(app, client, auth_headers, make_teams, make_player, find_match):
    services = app.state.services
    teams = _setup_played_tournament(services, make_teams, make_player, find_match)
    n_matches = len(services.store.matches.list())
    assert n_matches > 0

    r = client.post("/tournament/reset", json={"password": ADMIN_PWD}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"giocatori_aggiornati": 3, "partite_rimosse": n_matches}

    players = services.store.players.list()
    assert all(p.squadra_id is None and p.goal == 0 for p in players)
    assert services.store.matches.list() == []
    assert {t.id for t in services.store.teams.list()} == {t.id for t in teams}
    # Il token resta valido dopo il reset.
    assert client.get("/auth/me", headers=auth_headers).status_code == 200


def test_reset_with_wrong_password_changes_nothing(app, client, auth_headers, make_teams, make_player, find_match):
    services = app.state.services
    _setup_played_tournament(services, make_teams, make_player, find_match)
    before = _snapshot(services)

    r = client.post("/tournament/reset", json={"password": "sbagliata"}, headers=auth_headers)
    assert r.status_code == 403
    assert r.json() == {"detail": "Password non corretta"}
    assert _snapshot(services) == before


def test_reset_requires_token(client, admin):
    assert client.post("/tournament/reset", json={"password": ADMIN_PWD}).status_code == 401
    r = client.post("/tournament/reset", json={"password": ADMIN_PWD}, headers={"Authorization": "Bearer x"})
    assert r.status_code == 401


def test_reset_body_validation(client, auth_headers):
    assert client.post("/tournament/reset", json={"password": ""}, headers=auth_headers).status_code == 422
    assert client.post("/tournament/reset", json={}, headers=auth_headers).status_code == 422
    assert client.post("/tournament/reset", json={"password": "x" * 201}, headers=auth_headers).status_code == 422


def test_reset_rate_limited(client, auth_headers):
    for _ in range(5):
        r = client.post("/tournament/reset", json={"password": "x"}, headers=auth_headers)
        assert r.status_code == 403
    r = client.post("/tournament/reset", json={"password": ADMIN_PWD}, headers=auth_headers)
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0
    # Contatore separato da quello del login.
    assert client.get("/auth/me", headers=auth_headers).status_code == 200


def test_reset_success_clears_failures(client, auth_headers):
    for _ in range(4):
        client.post("/tournament/reset", json={"password": "x"}, headers=auth_headers)
    assert client.post("/tournament/reset", json={"password": ADMIN_PWD}, headers=auth_headers).status_code == 200
    for _ in range(4):
        assert client.post("/tournament/reset", json={"password": "x"}, headers=auth_headers).status_code == 403
    assert client.post("/tournament/reset", json={"password": ADMIN_PWD}, headers=auth_headers).status_code == 200


def test_reset_with_empty_tournament(client, auth_headers):
    r = client.post("/tournament/reset", json={"password": ADMIN_PWD}, headers=auth_headers)
    assert r.json() == {"giocatori_aggiornati": 0, "partite_rimosse": 0}
