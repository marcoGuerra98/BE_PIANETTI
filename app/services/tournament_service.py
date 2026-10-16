"""Operazioni sul torneo nel suo insieme (reset di fine torneo)."""

from app.models.tournament import ResetResult
from app.repositories.base import DataStore
from app.services.auth_service import AuthService


class TournamentService:
    """Reset del torneo, confermato dalla password dell'amministratore."""

    def __init__(self, store: DataStore, auth: AuthService):
        self.store = store
        self.auth = auth

    def reset(self, username: str, password: str, client_key: str) -> ResetResult:
        """Chiude il torneo: elimina tutte le partite e svincola tutti i giocatori azzerandone i goal.

        Le squadre restano. La password viene verificata prima di qualsiasi
        scrittura: se è errata (403) o si è oltre il rate limit (429) nulla cambia.
        """
        self.auth.verify_admin_password(username, password, client_key)
        with self.store.transaction():
            matches = self.store.matches.list()
            players = self.store.players.list()
            # Le partite vanno eliminate tutte: i goal sono derivati dai
            # marcatori e verrebbero ricalcolati dalle partite rimaste.
            removed = self.store.matches.delete_many(m.id for m in matches)
            self.store.players.update_many(
                p.model_copy(update={"squadra_id": None, "goal": 0}) for p in players
            )
        return ResetResult(giocatori_aggiornati=len(players), partite_rimosse=removed)
