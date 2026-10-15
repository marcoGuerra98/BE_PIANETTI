"""Calcolo dei goal dei giocatori a partire dai marcatori delle partite."""

from collections import Counter
from collections.abc import Iterable
from uuid import UUID

from app.models.match import Match
from app.repositories.base import DataStore


def goals_by_player(matches: Iterable[Match]) -> Counter[UUID]:
    """Somma i goal per giocatore sulle partite giocate (tutte le fasi, autogol esclusi)."""
    totals: Counter[UUID] = Counter()
    for m in matches:
        if m.giocata:
            for mk in m.marcatori:
                if not mk.autogol:  # gli autogol non contano per nessun giocatore
                    totals[mk.giocatore_id] += mk.goal
    return totals


def recalculate_goals(store: DataStore, player_ids: Iterable[UUID] | None = None) -> None:
    """Ricalcola `goal` dai marcatori di tutte le partite giocate.

    Il valore non viene mai incrementato: si riparte sempre dalla somma dei
    marcatori, quindi modificare un risultato non può contare due volte.
    Con `player_ids` si aggiornano solo i giocatori indicati.
    """
    totals = goals_by_player(store.matches.list())
    only = set(player_ids) if player_ids is not None else None
    changed = []
    for p in store.players.list():
        if only is not None and p.id not in only:
            continue
        g = totals.get(p.id, 0)
        if p.goal != g:
            changed.append(p.model_copy(update={"goal": g}))
    store.players.update_many(changed)
