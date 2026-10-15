"""Conversione entità → modelli di output arricchiti con i nomi."""

from uuid import UUID

from app.models.match import MarcatoreOut, Match, MatchOut
from app.models.player import Player, PlayerOut
from app.models.team import Team


def player_out(player: Player, teams: dict[UUID, Team]) -> PlayerOut:
    """Aggiunge il nome della squadra; `teams` è precaricato per evitare letture ripetute."""
    team = teams.get(player.squadra_id) if player.squadra_id else None
    return PlayerOut(**player.model_dump(), squadra_nome=team.nome if team else None)


def match_out(match: Match, teams: dict[UUID, Team], players: dict[UUID, Player]) -> MatchOut:
    """Aggiunge nomi e stemmi delle squadre e nome/cognome dei marcatori."""
    casa = teams.get(match.squadra_casa_id)
    trasf = teams.get(match.squadra_trasferta_id)
    marcatori = []
    for mk in match.marcatori:
        p = players.get(mk.giocatore_id) if mk.giocatore_id else None
        marcatori.append(
            MarcatoreOut(
                **mk.model_dump(),
                giocatore_nome=p.nome if p else None,
                giocatore_cognome=p.cognome if p else None,
            )
        )
    return MatchOut(
        **match.model_dump(exclude={"marcatori"}),
        marcatori=marcatori,
        squadra_casa_nome=casa.nome if casa else None,
        squadra_casa_stemma=casa.stemma if casa else None,
        squadra_trasferta_nome=trasf.nome if trasf else None,
        squadra_trasferta_stemma=trasf.stemma if trasf else None,
    )
