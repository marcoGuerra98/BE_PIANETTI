from app.models.match import Fase, Match
from app.models.player import Player, Ruolo
from app.models.team import Team
from app.services.standings_service import compute_scorers, compute_standings


def _m(home, away, gc=None, gt=None, fase=Fase.GIRONE):
    return Match(
        giornata=1, fase=fase, squadra_casa_id=home.id, squadra_trasferta_id=away.id,
        gol_casa=gc, gol_trasferta=gt, giocata=gc is not None,
    )


def test_points_and_stats():
    a, b, c = Team(nome="A"), Team(nome="B"), Team(nome="C")
    rows = compute_standings([a, b, c], [_m(a, b, 2, 0), _m(b, c, 1, 1), _m(c, a, 3, 1), _m(a, c)])
    by = {r.squadra_nome: r for r in rows}

    assert (by["A"].punti, by["A"].vinte, by["A"].perse, by["A"].giocate) == (3, 1, 1, 2)
    assert (by["A"].gol_fatti, by["A"].gol_subiti, by["A"].differenza_reti) == (3, 3, 0)
    assert (by["B"].punti, by["B"].pareggiate, by["B"].differenza_reti) == (1, 1, -2)
    assert (by["C"].punti, by["C"].vinte, by["C"].pareggiate) == (4, 1, 1)
    assert [r.squadra_nome for r in rows] == ["C", "A", "B"]
    assert [r.posizione for r in rows] == [1, 2, 3]


def test_ordering_tiebreakers_goal_difference_then_goals_for_then_name():
    a, b, c, d, e = (Team(nome=n) for n in "EDCBA")  # nomi invertiti per testare l'ultimo criterio
    x = Team(nome="X")
    matches = [
        _m(a, x, 3, 0),  # E: 3 pt, DR +3, GF 3
        _m(b, x, 4, 1),  # D: 3 pt, DR +3, GF 4  -> davanti a E per GF
        _m(c, x, 1, 0),  # C: 3 pt, DR +1
        _m(d, x, 1, 0),  # B: 3 pt, DR +1, GF 1 -> pari con C, ordine alfabetico: B prima di C
    ]
    rows = compute_standings([a, b, c, d, e, x], matches)
    assert [r.squadra_nome for r in rows][:4] == ["D", "E", "B", "C"]


def test_knockout_and_unplayed_matches_are_ignored():
    a, b = Team(nome="A"), Team(nome="B")
    rows = compute_standings([a, b], [_m(a, b), _m(a, b, 5, 0, fase=Fase.SEMIFINALE)])
    assert all(r.giocate == 0 and r.punti == 0 for r in rows)


def test_scorers_sorted_desc_with_shared_positions():
    t = Team(nome="T")
    p = [
        Player(nome="A", cognome="Uno", ruolo=Ruolo.ATT, overall=80, goal=3, squadra_id=t.id),
        Player(nome="B", cognome="Due", ruolo=Ruolo.CEN, overall=80, goal=5),
        Player(nome="C", cognome="Tre", ruolo=Ruolo.ATT, overall=80, goal=3),
        Player(nome="D", cognome="Zero", ruolo=Ruolo.DIF, overall=80, goal=0),
    ]
    rows = compute_scorers(p, [t])
    assert [(r.cognome, r.goal, r.posizione) for r in rows] == [("Due", 5, 1), ("Tre", 3, 2), ("Uno", 3, 2)]
    assert rows[2].squadra_nome == "T" and rows[0].squadra_nome is None
