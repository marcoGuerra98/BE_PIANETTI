from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.errors import ConflictError, NotFoundError, ValidationError
from app.models.match import MarcatoreIn, ResultIn
from app.models.player import PlayerCreate, PlayerUpdate, Ruolo
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
