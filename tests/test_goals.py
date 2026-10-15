import pytest

from app.errors import ValidationError
from app.models.match import MarcatoreIn, ResultIn
from app.models.player import PlayerUpdate


@pytest.fixture
def setup(services, make_teams, make_player, find_match):
    a, b, c, d = make_teams(4)
    services.schedule.generate()
    m = find_match(a.id, b.id)
    # normalizziamo: "casa" = a
    if m.squadra_casa_id != a.id:
        a, b = b, a
    pa1 = make_player(a, "Paolo", "Uno")
    pa2 = make_player(a, "Piero", "Due")
    pb1 = make_player(b, "Bruno", "Tre")
    pc = make_player(c, "Carlo", "Quattro")
    return m, (a, b, c, d), (pa1, pa2, pb1, pc)


def _result(gc, gt, *scorers):
    return ResultIn(
        gol_casa=gc, gol_trasferta=gt,
        marcatori=[MarcatoreIn(giocatore_id=p.id, goal=g) for p, g in scorers],
    )


def _goals(services, *players):
    return [services.players.get(p.id).goal for p in players]


def test_result_updates_player_goals(services, setup):
    m, _, (pa1, pa2, pb1, _) = setup
    out = services.matches.set_result(m.id, _result(3, 1, (pa1, 2), (pa2, 1), (pb1, 1)))
    assert out.giocata
    assert _goals(services, pa1, pa2, pb1) == [2, 1, 1]
    assert out.marcatori[0].giocatore_cognome == "Uno"


def test_editing_result_does_not_double_count(services, setup):
    m, _, (pa1, pa2, pb1, _) = setup
    services.matches.set_result(m.id, _result(3, 1, (pa1, 2), (pa2, 1), (pb1, 1)))
    services.matches.set_result(m.id, _result(3, 1, (pa1, 2), (pa2, 1), (pb1, 1)))
    assert _goals(services, pa1, pa2, pb1) == [2, 1, 1]

    services.matches.set_result(m.id, _result(1, 0, (pa2, 1)))
    assert _goals(services, pa1, pa2, pb1) == [0, 1, 0]


def test_goals_sum_across_matches(services, setup, find_match):
    m, (a, b, c, d), (pa1, *_rest) = setup
    services.matches.set_result(m.id, _result(1, 0, (pa1, 1)))
    m2 = find_match(a.id, c.id)
    gc, gt = (2, 0) if m2.squadra_casa_id == a.id else (0, 2)
    services.matches.set_result(m2.id, _result(gc, gt, (pa1, 2)))
    assert _goals(services, pa1) == [3]


def test_clearing_result_removes_goals(services, setup):
    m, _, (pa1, *_rest) = setup
    services.matches.set_result(m.id, _result(1, 0, (pa1, 1)))
    out = services.matches.clear_result(m.id)
    assert not out.giocata and out.gol_casa is None and out.marcatori == []
    assert _goals(services, pa1) == [0]


def test_scorer_must_belong_to_one_of_the_teams(services, setup):
    m, _, (_, _, _, pc) = setup
    with pytest.raises(ValidationError, match="non appartiene"):
        services.matches.set_result(m.id, _result(1, 0, (pc, 1)))
    assert _goals(services, pc) == [0]


def test_scorer_goals_must_match_score_per_team(services, setup):
    m, _, (pa1, _, pb1, _) = setup
    with pytest.raises(ValidationError, match="casa"):
        services.matches.set_result(m.id, _result(2, 0, (pa1, 1)))
    # goal assegnati alla squadra sbagliata: totale giusto, ripartizione no
    with pytest.raises(ValidationError):
        services.matches.set_result(m.id, _result(1, 1, (pa1, 2)))
    # partita invariata dopo un errore
    assert not services.matches.get(m.id).giocata


def test_duplicate_scorer_rejected(services, setup):
    m, _, (pa1, *_rest) = setup
    with pytest.raises(ValidationError):
        services.matches.set_result(m.id, _result(2, 0, (pa1, 1), (pa1, 1)))


def test_unknown_player_rejected(services, setup, make_player):
    from uuid import uuid4

    m, *_ = setup
    with pytest.raises(ValidationError):
        services.matches.set_result(
            m.id, ResultIn(gol_casa=1, gol_trasferta=0, marcatori=[MarcatoreIn(giocatore_id=uuid4(), goal=1)])
        )


def test_transferred_player_keeps_previous_team_in_old_match(services, setup):
    m, (a, b, c, d), (pa1, pa2, _, _) = setup
    services.matches.set_result(m.id, _result(2, 0, (pa1, 1), (pa2, 1)))

    # pa1 passa alla squadra C dopo aver segnato
    p = services.players.get(pa1.id)
    services.players.update(p.id, PlayerUpdate(**p.model_dump(include=set(PlayerUpdate.model_fields)) | {"squadra_id": c.id}))

    # Rimodificando il risultato, i suoi goal restano attribuiti alla squadra di allora
    out = services.matches.set_result(m.id, _result(2, 0, (pa1, 1), (pa2, 1)))
    assert next(mk for mk in out.marcatori if mk.giocatore_id == pa1.id).squadra_id == a.id
    assert _goals(services, pa1) == [1]


# --- Autogol ---


def _own_goal(team, goal=1):
    return MarcatoreIn(autogol=True, squadra_id=team.id, goal=goal)


def test_own_goal_counts_for_team_but_not_for_any_player(services, setup):
    m, (a, b, c, d), (pa1, pa2, pb1, _) = setup
    # 2-1: un gol di pa1 + un autogol a favore di A; per B segna pb1
    out = services.matches.set_result(
        m.id,
        ResultIn(
            gol_casa=2, gol_trasferta=1,
            marcatori=[MarcatoreIn(giocatore_id=pa1.id, goal=1), _own_goal(a), MarcatoreIn(giocatore_id=pb1.id, goal=1)],
        ),
    )
    own = next(mk for mk in out.marcatori if mk.autogol)
    assert own.giocatore_id is None and own.squadra_id == a.id
    assert _goals(services, pa1, pa2, pb1) == [1, 0, 1]
    assert {r.cognome for r in services.standings.scorers()} == {"Uno", "Tre"}
    assert sum(r.goal for r in services.standings.scorers()) == 2


def test_only_own_goals(services, setup):
    m, (a, b, *_), players = setup
    services.matches.set_result(
        m.id, ResultIn(gol_casa=2, gol_trasferta=1, marcatori=[_own_goal(a, 2), _own_goal(b, 1)])
    )
    assert _goals(services, *players) == [0, 0, 0, 0]
    row_a = next(r for r in services.standings.standings() if r.squadra_id == a.id)
    assert (row_a.punti, row_a.gol_fatti, row_a.gol_subiti) == (3, 2, 1)


def test_own_goal_validation(services, setup):
    from pydantic import ValidationError as PydanticValidationError

    m, (a, b, c, d), (pa1, *_rest) = setup
    # squadra estranea alla partita
    with pytest.raises(ValidationError):
        services.matches.set_result(m.id, ResultIn(gol_casa=0, gol_trasferta=0, marcatori=[_own_goal(c)]))
    # autogol duplicati per la stessa squadra
    with pytest.raises(ValidationError):
        services.matches.set_result(m.id, ResultIn(gol_casa=2, gol_trasferta=0, marcatori=[_own_goal(a), _own_goal(a)]))
    # l'autogol rientra nel controllo somma = punteggio
    with pytest.raises(ValidationError):
        services.matches.set_result(m.id, ResultIn(gol_casa=1, gol_trasferta=0, marcatori=[_own_goal(b)]))
    # forma non valida: autogol con giocatore, o senza squadra
    with pytest.raises(PydanticValidationError):
        MarcatoreIn(autogol=True, giocatore_id=pa1.id, squadra_id=a.id, goal=1)
    with pytest.raises(PydanticValidationError):
        MarcatoreIn(autogol=True, goal=1)
    with pytest.raises(PydanticValidationError):
        MarcatoreIn(goal=1)


def test_own_goal_via_api(client, auth_headers):
    h = auth_headers
    for n in "ABCD":
        client.post("/teams", json={"nome": n}, headers=h)
    client.post("/schedule/generate", headers=h)
    m = client.get("/schedule").json()["giornate"][0]["partite"][0]
    r = client.put(
        f"/matches/{m['id']}/result",
        json={"gol_casa": 1, "gol_trasferta": 0, "marcatori": [{"autogol": True, "squadra_id": m["squadra_casa_id"], "goal": 1}]},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["marcatori"] == [
        {
            "giocatore_id": None, "squadra_id": m["squadra_casa_id"], "goal": 1, "autogol": True,
            "giocatore_nome": None, "giocatore_cognome": None,
        }
    ]
