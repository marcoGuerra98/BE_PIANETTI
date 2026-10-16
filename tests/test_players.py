from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.errors import ConflictError, NotFoundError, ValidationError
from app.models.match import MarcatoreIn, ResultIn
from app.models.player import PlayerCreate, PlayerUpdate, Ruolo, StatoGiocatore
from app.services.player_service import PlayerSort


def test_create_validates_fields():
    with pytest.raises(PydanticValidationError):
        PlayerCreate(nome="", cognome="X", ruolo=Ruolo.ATT, overall=50)
    with pytest.raises(PydanticValidationError):
        PlayerCreate(nome="A", cognome="X", ruolo="POR", overall=100)
    with pytest.raises(PydanticValidationError):
        PlayerCreate(nome="A", cognome="X", ruolo="PORTIERE", overall=50)


def test_create_with_unknown_team_fails(services):
    with pytest.raises(ValidationError):
        services.players.create(
            PlayerCreate(nome="A", cognome="B", ruolo=Ruolo.ATT, overall=50, squadra_id=uuid4())
        )


def test_crud(services, make_teams, make_player):
    (a,) = make_teams(1)
    p = make_player(a)
    assert p.goal == 0 and p.squadra_nome == a.nome

    updated = services.players.update(
        p.id, PlayerUpdate(nome="Mario", cognome="Bianchi", ruolo=Ruolo.CEN, overall=88, squadra_id=None)
    )
    assert (updated.cognome, updated.ruolo, updated.overall, updated.squadra_id) == ("Bianchi", "CEN", 88, None)

    services.players.delete(p.id)
    with pytest.raises(NotFoundError):
        services.players.get(p.id)


def test_list_filters_and_sorting(services, make_teams, make_player):
    a, b = make_teams(2)
    make_player(a, "Gianluigi", "Buffon", Ruolo.POR, 90)
    make_player(a, "Paolo", "Maldini", Ruolo.DIF, 95)
    make_player(b, "Andrea", "Pirlo", Ruolo.CEN, 92)
    make_player(None, "Roberto", "Baggio", Ruolo.ATT, 97)

    assert [p.cognome for p in services.players.list()] == ["Baggio", "Maldini", "Pirlo", "Buffon"]
    assert [p.cognome for p in services.players.list(sort=PlayerSort.OVERALL_ASC)][0] == "Buffon"
    assert [p.cognome for p in services.players.list(sort=PlayerSort.NOME)][0] == "Baggio"
    assert [p.cognome for p in services.players.list(ruolo=Ruolo.DIF)] == ["Maldini"]
    assert {p.cognome for p in services.players.list(squadra_id=a.id)} == {"Buffon", "Maldini"}
    assert [p.cognome for p in services.players.list(svincolati=True)] == ["Baggio"]
    assert [p.cognome for p in services.players.list(q="paolo mal")] == ["Maldini"]
    assert [p.cognome for p in services.players.list(q="PIRLO andrea")] == ["Pirlo"]


def test_cannot_delete_player_who_scored(services, make_teams, make_player, find_match):
    a, b, c, d = make_teams(4)
    p = make_player(a)
    services.schedule.generate()
    m = find_match(a.id, b.id)
    gc, gt = (1, 0) if m.squadra_casa_id == a.id else (0, 1)
    services.matches.set_result(
        m.id, ResultIn(gol_casa=gc, gol_trasferta=gt, marcatori=[MarcatoreIn(giocatore_id=p.id, goal=1)])
    )
    with pytest.raises(ConflictError):
        services.players.delete(p.id)


def test_update_does_not_touch_goal_and_photo(services, make_teams, make_player):
    (a,) = make_teams(1)
    p = make_player(a)
    stored = services.store.players.get(p.id)
    services.store.players.update(stored.model_copy(update={"goal": 4, "foto": "/uploads/players/x.jpg"}))
    out = services.players.update(p.id, PlayerUpdate(**p.model_dump(include=set(PlayerUpdate.model_fields))))
    assert (out.goal, out.foto) == (4, "/uploads/players/x.jpg")


# --- fascia, ricerca, stato e ordinamento per ruolo ---


@pytest.mark.parametrize("fascia", [1, 2, 3, 4, None])
def test_fascia_valid_values(fascia):
    assert PlayerCreate(nome="A", cognome="B", ruolo=Ruolo.ATT, overall=50, fascia=fascia).fascia == fascia


@pytest.mark.parametrize("fascia", [0, 5, -1])
def test_fascia_out_of_range_rejected(fascia):
    with pytest.raises(PydanticValidationError):
        PlayerCreate(nome="A", cognome="B", ruolo=Ruolo.ATT, overall=50, fascia=fascia)


def test_fascia_defaults_to_none_for_existing_data():
    # I JSON salvati prima dell'introduzione del campo restano validi.
    assert PlayerCreate(nome="A", cognome="B", ruolo=Ruolo.ATT, overall=50).fascia is None


def test_filter_by_fascia(services, make_player):
    p1 = make_player(None, "A", "Uno")
    make_player(None, "B", "Due")
    services.players.update(p1.id, PlayerUpdate(**{**p1.model_dump(include=set(PlayerUpdate.model_fields)), "fascia": 2}))
    assert [p.cognome for p in services.players.list(fascia=2)] == ["Uno"]
    assert services.players.list(fascia=1) == []


@pytest.mark.parametrize("q", ["rossi", "mario ross", "ROSSI mario", "  mario    rossi  ", "Mario Rossi"])
def test_search_name_and_surname(services, make_player, q):
    make_player(None, "Mario", "Rossi")
    make_player(None, "Luigi", "Verdi")
    assert [p.cognome for p in services.players.list(q=q)] == ["Rossi"]


def test_search_no_match(services, make_player):
    make_player(None, "Mario", "Rossi")
    assert services.players.list(q="rossi luigi") == []


def test_filter_by_stato(services, make_teams, make_player):
    (a,) = make_teams(1)
    make_player(a, "A", "Assegnato")
    make_player(None, "S", "Svincolato")
    assert [p.cognome for p in services.players.list(stato=StatoGiocatore.ASSEGNATO)] == ["Assegnato"]
    assert [p.cognome for p in services.players.list(stato=StatoGiocatore.SVINCOLATO)] == ["Svincolato"]
    # svincolati=true resta equivalente a stato=svincolato
    assert [p.cognome for p in services.players.list(svincolati=True)] == ["Svincolato"]


def test_sort_by_ruolo_then_surname_and_name(services, make_teams, make_player):
    a, b = make_teams(2)
    make_player(a, "Zeno", "Bianchi", Ruolo.ATT, 99)
    make_player(b, "Anna", "Bianchi", Ruolo.ATT, 50)
    make_player(a, "Carlo", "Verdi", Ruolo.CEN, 70)
    make_player(b, "Dario", "alfieri", Ruolo.DIF, 60)
    make_player(a, "Elio", "Zanetti", Ruolo.DIF, 90)
    make_player(b, "Franco", "Neri", Ruolo.POR, 40)
    make_player(None, "Svinco", "Lato", Ruolo.POR, 80)

    out = services.players.list(stato=StatoGiocatore.ASSEGNATO, sort=PlayerSort.RUOLO)
    assert [(p.ruolo, p.cognome, p.nome) for p in out] == [
        ("POR", "Neri", "Franco"),
        ("DIF", "alfieri", "Dario"),
        ("DIF", "Zanetti", "Elio"),
        ("CEN", "Verdi", "Carlo"),
        ("ATT", "Bianchi", "Anna"),
        ("ATT", "Bianchi", "Zeno"),
    ]
    assert all(p.squadra_nome for p in out)


def test_list_players_query_params_api(client, auth_headers):
    h = auth_headers
    team = client.post("/teams", json={"nome": "Alfa"}, headers=h).json()
    body = {"nome": "Mario", "cognome": "Rossi", "ruolo": "DIF", "overall": 70, "fascia": 1, "squadra_id": team["id"]}
    r = client.post("/players", json=body, headers=h)
    assert r.status_code == 201 and r.json()["fascia"] == 1
    client.post("/players", json={"nome": "Gino", "cognome": "Bassi", "ruolo": "POR", "overall": 60}, headers=h)

    assert client.post("/players", json={**body, "fascia": 0}, headers=h).status_code == 422
    assert client.post("/players", json={**body, "fascia": 5}, headers=h).status_code == 422
    assert client.get("/players", params={"fascia": 5}).status_code == 422
    assert client.get("/players", params={"stato": "boh"}).status_code == 422

    assert [p["cognome"] for p in client.get("/players", params={"fascia": 1}).json()] == ["Rossi"]
    r = client.get("/players", params={"stato": "assegnato", "sort": "ruolo"})
    assert [(p["cognome"], p["squadra_nome"]) for p in r.json()] == [("Rossi", "Alfa")]
    assert [p["cognome"] for p in client.get("/players", params={"stato": "svincolato"}).json()] == ["Bassi"]
    assert [p["cognome"] for p in client.get("/players", params={"q": "ROSSI mario"}).json()] == ["Rossi"]

    # update: fascia modificabile e azzerabile
    pid = client.get("/players", params={"q": "rossi"}).json()[0]["id"]
    r = client.put(f"/players/{pid}", json={**body, "fascia": 4}, headers=h)
    assert r.status_code == 200 and r.json()["fascia"] == 4
    assert client.put(f"/players/{pid}", json={**body, "fascia": 5}, headers=h).status_code == 422
    r = client.put(f"/players/{pid}", json={**body, "fascia": None}, headers=h)
    assert r.status_code == 200 and r.json()["fascia"] is None
