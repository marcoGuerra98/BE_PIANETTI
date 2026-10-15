import pytest

from app.errors import ConflictError, NotFoundError
from app.models.match import Fase, MarcatoreIn, ResultIn
from app.models.team import TeamCreate, TeamUpdate


def test_team_name_unique_case_insensitive(services):
    services.teams.create(TeamCreate(nome="Juventus"))
    with pytest.raises(ConflictError):
        services.teams.create(TeamCreate(nome="  juventus "))


def test_rename_unique_and_reflected_in_players_and_matches(services, make_teams, make_player):
    a, b, c, d = make_teams(4)
    p = make_player(a)
    services.schedule.generate()

    with pytest.raises(ConflictError):
        services.teams.update(a.id, TeamUpdate(nome=b.nome.upper()))
    services.teams.update(a.id, TeamUpdate(nome=a.nome.upper()))  # stessa squadra: consentito
    services.teams.update(a.id, TeamUpdate(nome="Nuovo Nome"))

    assert services.players.get(p.id).squadra_nome == "Nuovo Nome"
    assert services.players.get(p.id).squadra_id == a.id
    sched = services.schedule.get_schedule()
    names = {n for g in sched.giornate for m in g.partite for n in (m.squadra_casa_nome, m.squadra_trasferta_nome)}
    assert "Nuovo Nome" in names and a.nome not in names


def test_delete_team_unassigns_players_and_removes_unplayed_matches(services, make_teams, make_player):
    a, b, c, d, e = make_teams(5)
    p1, p2 = make_player(a), make_player(a, nome="Luca")
    other = make_player(b, nome="Altro")
    services.schedule.generate()
    assert sum(m.involves(a.id) for m in services.store.matches.list()) == 4

    result = services.teams.delete(a.id)

    assert result.giocatori_svincolati == 2 and result.partite_rimosse == 4
    assert services.players.get(p1.id).squadra_id is None
    assert services.players.get(p2.id).squadra_id is None
    assert services.players.get(other.id).squadra_id == b.id
    assert not any(m.involves(a.id) for m in services.store.matches.list())
    assert len(services.store.matches.list()) == 6
    with pytest.raises(NotFoundError):
        services.teams.get(a.id)


def test_delete_team_with_played_matches_requires_force(services, make_teams, make_player, find_match):
    a, b, c, d = make_teams(4)
    pa, pb = make_player(a), make_player(b, nome="Bepi")
    services.schedule.generate()
    m = find_match(a.id, b.id)
    services.matches.set_result(
        m.id,
        ResultIn(
            gol_casa=1, gol_trasferta=1,
            marcatori=[MarcatoreIn(giocatore_id=pa.id, goal=1), MarcatoreIn(giocatore_id=pb.id, goal=1)],
        ),
    )
    assert services.players.get(pa.id).goal == 1

    with pytest.raises(ConflictError) as exc:
        services.teams.delete(a.id)
    assert len(exc.value.details["partite_giocate"]) == 1
    # nulla è cambiato
    assert services.players.get(pa.id).squadra_id == a.id
    assert len(services.store.matches.list()) == 6

    services.teams.delete(a.id, force=True)
    assert len(services.store.matches.list()) == 3
    # i goal segnati nella partita rimossa vengono sottratti
    assert services.players.get(pa.id).goal == 0
    assert services.players.get(pb.id).goal == 0


def test_delete_team_after_group_completed_recomputes_knockout(services, make_teams, play):
    teams = make_teams(5)
    services.schedule.generate()
    for m in services.store.matches.list():
        play(m, 1, 0)
    assert any(m.fase == Fase.SEMIFINALE for m in services.store.matches.list())

    services.teams.delete(teams[0].id, force=True)

    semis = [m for m in services.store.matches.list() if m.fase == Fase.SEMIFINALE]
    assert len(semis) == 2
    assert not any(m.involves(teams[0].id) for m in services.store.matches.list())
    top = [r.squadra_id for r in services.standings.standings()[:4]]
    assert {(m.squadra_casa_id, m.squadra_trasferta_id) for m in semis} == {(top[0], top[3]), (top[1], top[2])}


def test_team_detail_contains_roster(services, make_teams, make_player):
    from app.models.player import Ruolo

    a, b = make_teams(2)
    make_player(a, cognome="Att", ruolo=Ruolo.ATT)
    make_player(a, cognome="Por", ruolo=Ruolo.POR)
    make_player(b, cognome="Altro")
    detail = services.teams.get(a.id)
    assert [p.cognome for p in detail.giocatori] == ["Por", "Att"]
    assert all(p.squadra_nome == a.nome for p in detail.giocatori)
