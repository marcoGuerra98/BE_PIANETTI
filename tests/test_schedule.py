from collections import Counter
from itertools import combinations
from uuid import uuid4

import pytest

from app.errors import ConflictError, ValidationError
from app.models.match import Fase, MatchUpdate
from app.services.schedule_service import round_robin


@pytest.mark.parametrize("n", range(4, 21))
def test_round_robin_every_pair_once_and_no_team_twice_per_round(n):
    ids = [uuid4() for _ in range(n)]
    rounds = round_robin(ids)
    assert len(rounds) == (n if n % 2 else n - 1)
    pairs = [frozenset(p) for r in rounds for p in r]
    assert len(pairs) == n * (n - 1) // 2
    assert set(pairs) == {frozenset(c) for c in combinations(ids, 2)}
    for r in rounds:
        teams = [t for p in r for t in p]
        assert len(teams) == len(set(teams))
    # casa/trasferta bilanciate: al massimo una partita in casa di differenza
    home = Counter(h for r in rounds for h, _ in r)
    assert max(home.values()) - min(home.get(t, 0) for t in ids) <= 1


def test_generate_requires_four_teams(services, make_teams):
    make_teams(3)
    with pytest.raises(ValidationError):
        services.schedule.generate()


def test_generate_creates_group_only(services, make_teams):
    make_teams(5)
    out = services.schedule.generate()
    assert out.totale_partite == 10
    assert len(out.giornate) == 5
    assert all(g.fase == Fase.GIRONE for g in out.giornate)
    # con squadre dispari, una riposa a ogni giornata
    assert all(len(g.riposa) == 1 for g in out.giornate)
    assert out.giornate[0].partite[0].squadra_casa_nome.startswith("Squadra")


def test_regenerate_requires_confirm_and_resets_goals(services, make_teams, make_player, find_match):
    from app.models.match import MarcatoreIn, ResultIn

    a, b, *_ = make_teams(4)
    p = make_player(a)
    services.schedule.generate()
    m = find_match(a.id, b.id)
    home_is_a = m.squadra_casa_id == a.id
    services.matches.set_result(
        m.id,
        ResultIn(
            gol_casa=1 if home_is_a else 0,
            gol_trasferta=0 if home_is_a else 1,
            marcatori=[MarcatoreIn(giocatore_id=p.id, goal=1)],
        ),
    )
    assert services.players.get(p.id).goal == 1

    with pytest.raises(ConflictError) as exc:
        services.schedule.generate()
    assert exc.value.details == {"partite": 6, "partite_giocate": 1}

    services.schedule.generate(confirm=True)
    assert services.players.get(p.id).goal == 0
    assert services.schedule.get_schedule().partite_giocate == 0


def test_delete_schedule_requires_confirm(services, make_teams):
    make_teams(4)
    services.schedule.generate()
    with pytest.raises(ConflictError):
        services.schedule.delete()
    services.schedule.delete(confirm=True)
    assert services.store.matches.list() == []
    services.schedule.delete()  # calendario vuoto: nessuna conferma necessaria


def _play_group(services, play, ranking):
    """Gioca il girone in modo che la classifica finale segua `ranking`
    (vince sempre la squadra meglio piazzata)."""
    pos = {t.id: i for i, t in enumerate(ranking)}
    for m in services.store.matches.list():
        if m.fase != Fase.GIRONE:
            continue
        home_better = pos[m.squadra_casa_id] < pos[m.squadra_trasferta_id]
        play(m, 1 if home_better else 0, 0 if home_better else 1)


def _knockout(services, fase):
    return [m for m in services.store.matches.list() if m.fase == fase]


def test_semifinals_created_automatically_at_end_of_group(services, make_teams, play):
    teams = make_teams(5)
    services.schedule.generate()
    ranking = [teams[2], teams[0], teams[4], teams[1], teams[3]]

    group = services.store.matches.list()
    _play_group(services, play, ranking)

    semis = _knockout(services, Fase.SEMIFINALE)
    assert len(semis) == 2
    pairs = {(m.squadra_casa_id, m.squadra_trasferta_id) for m in semis}
    assert pairs == {(ranking[0].id, ranking[3].id), (ranking[1].id, ranking[2].id)}
    assert all(m.giornata == max(g.giornata for g in group) + 1 for m in semis)
    assert _knockout(services, Fase.FINALE_1_2) == []


def test_semifinals_not_created_before_group_ends(services, make_teams, play):
    make_teams(4)
    services.schedule.generate()
    group = services.store.matches.list()
    for m in group[:-1]:
        play(m, 1, 0)
    assert _knockout(services, Fase.SEMIFINALE) == []


def test_finals_created_after_semifinals_with_penalties(services, make_teams, play):
    teams = make_teams(4)
    services.schedule.generate()
    first, second, third, fourth = teams
    _play_group(services, play, teams)

    s1 = next(m for m in _knockout(services, Fase.SEMIFINALE) if m.involves(first.id))
    s2 = next(m for m in _knockout(services, Fase.SEMIFINALE) if m.involves(second.id))

    # pareggio in semifinale senza vincitore ai rigori: errore
    with pytest.raises(ValidationError):
        play(s1, 2, 2)
    play(s1, 2, 2, rigori=fourth.id)  # la 4ª vince ai rigori
    assert _knockout(services, Fase.FINALE_1_2) == []
    play(s2, 0, 1)  # vince la trasferta (3ª)

    f12 = _knockout(services, Fase.FINALE_1_2)
    f34 = _knockout(services, Fase.FINALE_3_4)
    assert len(f12) == len(f34) == 1
    assert (f12[0].squadra_casa_id, f12[0].squadra_trasferta_id) == (fourth.id, third.id)
    assert (f34[0].squadra_casa_id, f34[0].squadra_trasferta_id) == (first.id, second.id)
    assert f12[0].giornata == s1.giornata + 1


def test_penalty_winner_rejected_in_group_and_ignored_when_not_draw(services, make_teams, play):
    teams = make_teams(4)
    services.schedule.generate()
    m = services.store.matches.list()[0]
    with pytest.raises(ValidationError):
        play(m, 1, 1, rigori=m.squadra_casa_id)

    _play_group(services, play, teams)
    semi = _knockout(services, Fase.SEMIFINALE)[0]
    out = play(semi, 3, 1, rigori=semi.squadra_trasferta_id)
    assert out.vincitore_rigori_id is None


def test_group_result_change_realigns_unplayed_semifinals(services, make_teams, play, find_match):
    teams = make_teams(4)
    a, b, c, d = teams
    services.schedule.generate()
    _play_group(services, play, teams)
    semi = next(m for m in _knockout(services, Fase.SEMIFINALE) if m.involves(a.id))
    services.matches.update(semi.id, MatchUpdate(data_ora="2026-11-01T15:00:00"))

    # D batte A 5-0 e C 5-0: nuova classifica D, B, A, C
    for opp in (a, c):
        m = find_match(d.id, opp.id, Fase.GIRONE)
        play(m, *((5, 0) if m.squadra_casa_id == d.id else (0, 5)))

    top = [r.squadra_id for r in services.standings.standings()[:4]]
    assert top == [d.id, b.id, a.id, c.id]
    semis = _knockout(services, Fase.SEMIFINALE)
    assert len(semis) == 2
    assert {(m.squadra_casa_id, m.squadra_trasferta_id) for m in semis} == {(d.id, c.id), (b.id, a.id)}
    assert any(m.data_ora is not None for m in semis)  # data e ora conservate


def test_group_result_locked_once_knockout_played(services, make_teams, play):
    teams = make_teams(4)
    services.schedule.generate()
    _play_group(services, play, teams)
    play(_knockout(services, Fase.SEMIFINALE)[0], 1, 0)

    group_match = next(m for m in services.store.matches.list() if m.fase == Fase.GIRONE)
    with pytest.raises(ConflictError):
        play(group_match, 0, 0)
    with pytest.raises(ConflictError):
        services.matches.clear_result(group_match.id)


def test_clearing_group_result_removes_unplayed_knockout(services, make_teams, play):
    teams = make_teams(4)
    services.schedule.generate()
    _play_group(services, play, teams)
    assert len(_knockout(services, Fase.SEMIFINALE)) == 2

    group_match = next(m for m in services.store.matches.list() if m.fase == Fase.GIRONE)
    services.matches.clear_result(group_match.id)
    assert _knockout(services, Fase.SEMIFINALE) == []


def test_update_match_date_day_and_teams(services, make_teams):
    a, b, c, d, e = make_teams(5)
    services.schedule.generate(shuffle=False)
    m = services.store.matches.list()[0]

    out = services.matches.update(m.id, MatchUpdate(data_ora="2026-10-20T20:45:00"))
    assert out.data_ora.hour == 20
    out = services.matches.update(m.id, MatchUpdate(data_ora=None))
    assert out.data_ora is None

    with pytest.raises(ValidationError):
        services.matches.update(m.id, MatchUpdate(squadra_casa_id=m.squadra_trasferta_id))
    # coppia già esistente in un'altra partita del girone
    other = services.store.matches.list()[1]
    with pytest.raises(ConflictError):
        services.matches.update(
            m.id,
            MatchUpdate(squadra_casa_id=other.squadra_casa_id, squadra_trasferta_id=other.squadra_trasferta_id),
        )

    # spostamento in una giornata nuova (libera)
    out = services.matches.update(m.id, MatchUpdate(giornata=10))
    assert out.giornata == 10


def test_move_to_day_where_team_already_plays_is_rejected(services, make_teams):
    make_teams(4)
    services.schedule.generate(shuffle=False)
    matches = services.store.matches.list()
    m = matches[0]
    clash = next(x for x in matches if x.giornata != m.giornata and (x.involves(m.squadra_casa_id)))
    with pytest.raises(ConflictError):
        services.matches.update(m.id, MatchUpdate(giornata=clash.giornata))


def test_knockout_teams_and_day_not_editable(services, make_teams, play):
    teams = make_teams(4)
    services.schedule.generate()
    _play_group(services, play, teams)
    semi = _knockout(services, Fase.SEMIFINALE)[0]
    with pytest.raises(ValidationError):
        services.matches.update(semi.id, MatchUpdate(giornata=99))
    services.matches.update(semi.id, MatchUpdate(data_ora="2026-12-01T18:00:00"))


def test_cannot_change_teams_of_played_match(services, make_teams, play):
    a, b, c, d, e = make_teams(5)
    services.schedule.generate(shuffle=False)
    m = services.store.matches.list()[0]
    play(m, 1, 0)
    free = next(t for t in (a, b, c, d, e) if not m.involves(t.id))
    with pytest.raises(ConflictError):
        services.matches.update(m.id, MatchUpdate(squadra_casa_id=free.id))
