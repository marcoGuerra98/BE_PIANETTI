"""Classifica del girone e classifica marcatori, calcolate a ogni richiesta."""

from collections.abc import Iterable

from app.models.match import Fase, Match
from app.models.player import Player
from app.models.standings import ScorerRow, StandingRow
from app.models.team import Team
from app.repositories.base import DataStore

POINTS_WIN, POINTS_DRAW = 3, 1


def compute_standings(teams: Iterable[Team], matches: Iterable[Match]) -> list[StandingRow]:
    """Classifica del girone: solo partite di fase GIRONE già giocate.

    Ordine: punti, differenza reti, gol fatti, poi nome (spareggio deterministico).
    Compaiono tutte le squadre passate in `teams`, anche senza partite giocate.
    """
    rows = {
        t.id: StandingRow(posizione=0, squadra_id=t.id, squadra_nome=t.nome, stemma=t.stemma)
        for t in teams
    }
    for m in matches:
        if m.fase != Fase.GIRONE or not m.giocata:
            continue
        home, away = rows.get(m.squadra_casa_id), rows.get(m.squadra_trasferta_id)
        # Difensivo: partite che riferiscono squadre non più esistenti.
        if home is None or away is None:
            continue
        for row, gf, gs in ((home, m.gol_casa, m.gol_trasferta), (away, m.gol_trasferta, m.gol_casa)):
            row.giocate += 1
            row.gol_fatti += gf
            row.gol_subiti += gs
            if gf > gs:
                row.vinte += 1
                row.punti += POINTS_WIN
            elif gf == gs:
                row.pareggiate += 1
                row.punti += POINTS_DRAW
            else:
                row.perse += 1

    ordered = sorted(
        rows.values(),
        key=lambda r: (
            -r.punti,
            -(r.gol_fatti - r.gol_subiti),
            -r.gol_fatti,
            r.squadra_nome.casefold(),
        ),
    )
    for i, r in enumerate(ordered, start=1):
        r.posizione = i
        r.differenza_reti = r.gol_fatti - r.gol_subiti
    return ordered


def compute_scorers(players: Iterable[Player], teams: Iterable[Team]) -> list[ScorerRow]:
    """Classifica marcatori: solo giocatori con almeno un goal, a pari merito stessa posizione."""
    team_names = {t.id: t.nome for t in teams}
    scorers = sorted(
        (p for p in players if p.goal > 0),
        key=lambda p: (-p.goal, p.cognome.casefold(), p.nome.casefold()),
    )
    rows: list[ScorerRow] = []
    for i, p in enumerate(scorers, start=1):
        # Classifica "a pari merito": 1, 2, 2, 4, ...
        pos = rows[-1].posizione if rows and rows[-1].goal == p.goal else i
        rows.append(
            ScorerRow(
                posizione=pos,
                giocatore_id=p.id,
                nome=p.nome,
                cognome=p.cognome,
                ruolo=p.ruolo,
                foto=p.foto,
                squadra_id=p.squadra_id,
                squadra_nome=team_names.get(p.squadra_id),
                goal=p.goal,
            )
        )
    return rows


class StandingsService:
    """Espone le classifiche calcolate sui dati correnti."""

    def __init__(self, store: DataStore):
        self.store = store

    def standings(self) -> list[StandingRow]:
        return compute_standings(self.store.teams.list(), self.store.matches.list())

    def scorers(self) -> list[ScorerRow]:
        return compute_scorers(self.store.players.list(), self.store.teams.list())
