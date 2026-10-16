"""Gestione dei giocatori: CRUD, filtri di ricerca e foto."""

from enum import StrEnum
from uuid import UUID

from app.errors import ConflictError, NotFoundError, ValidationError
from app.models.player import (
    Player,
    PlayerCreate,
    PlayerOut,
    PlayerUpdate,
    Ruolo,
    StatoGiocatore,
    ruolo_index,
)
from app.repositories.base import DataStore
from app.services.upload_service import UploadService
from app.services.views import player_out


class PlayerSort(StrEnum):
    """Ordinamenti disponibili per GET /players (a parità si ordina per cognome e nome)."""

    OVERALL_DESC = "overall_desc"
    OVERALL_ASC = "overall_asc"
    NOME = "nome"
    # Ordine di campo POR, DIF, CEN, ATT (non alfabetico), poi cognome e nome.
    RUOLO = "ruolo"


def _matches_name(player: Player, term: str) -> bool:
    """True se `term` (già normalizzato e in casefold) compare in "nome cognome" o "cognome nome"."""
    nome, cognome = " ".join(player.nome.split()), " ".join(player.cognome.split())
    return term in f"{nome} {cognome}".casefold() or term in f"{cognome} {nome}".casefold()


class PlayerService:
    """CRUD dei giocatori; il campo `goal` non è mai modificabile da qui."""

    def __init__(self, store: DataStore, uploads: UploadService):
        self.store = store
        self.uploads = uploads

    def _teams(self):
        return {t.id: t for t in self.store.teams.list()}

    def _get(self, player_id: UUID) -> Player:
        player = self.store.players.get(player_id)
        if player is None:
            raise NotFoundError("Giocatore non trovato")
        return player

    def _check_team(self, squadra_id: UUID | None) -> None:
        if squadra_id is not None and self.store.teams.get(squadra_id) is None:
            raise ValidationError("La squadra indicata non esiste")

    def list(
        self,
        ruolo: Ruolo | None = None,
        squadra_id: UUID | None = None,
        svincolati: bool = False,
        q: str | None = None,
        sort: PlayerSort = PlayerSort.OVERALL_DESC,
        fascia: int | None = None,
        stato: StatoGiocatore | None = None,
    ) -> list[PlayerOut]:
        """Elenco filtrato e ordinato.

        `svincolati=True` equivale a `stato=svincolato` (mantenuto per
        compatibilità) e prevale su `squadra_id`; `q` cerca senza distinzione
        di maiuscole in "nome cognome" e "cognome nome", con spazi normalizzati.
        """
        if svincolati:
            stato = StatoGiocatore.SVINCOLATO
        players = self.store.players.list()
        if ruolo:
            players = [p for p in players if p.ruolo == ruolo]
        if fascia is not None:
            players = [p for p in players if p.fascia == fascia]
        if stato == StatoGiocatore.SVINCOLATO:
            players = [p for p in players if p.squadra_id is None]
        else:
            if stato == StatoGiocatore.ASSEGNATO:
                players = [p for p in players if p.squadra_id is not None]
            if squadra_id:
                players = [p for p in players if p.squadra_id == squadra_id]
        if q and (term := " ".join(q.split()).casefold()):
            players = [p for p in players if _matches_name(p, term)]
        by_name = lambda p: (p.cognome.casefold(), p.nome.casefold())  # noqa: E731
        match sort:
            case PlayerSort.OVERALL_DESC:
                players.sort(key=lambda p: (-p.overall, *by_name(p)))
            case PlayerSort.OVERALL_ASC:
                players.sort(key=lambda p: (p.overall, *by_name(p)))
            case PlayerSort.NOME:
                players.sort(key=by_name)
            case PlayerSort.RUOLO:
                players.sort(key=lambda p: (ruolo_index(p.ruolo), *by_name(p)))
        teams = self._teams()
        return [player_out(p, teams) for p in players]

    def get(self, player_id: UUID) -> PlayerOut:
        return player_out(self._get(player_id), self._teams())

    def create(self, data: PlayerCreate) -> PlayerOut:
        with self.store.transaction():
            self._check_team(data.squadra_id)
            player = self.store.players.add(Player(**data.model_dump()))
        return self.get(player.id)

    def update(self, player_id: UUID, data: PlayerUpdate) -> PlayerOut:
        with self.store.transaction():
            player = self._get(player_id)
            self._check_team(data.squadra_id)
            # goal e foto non sono modificabili da qui: goal è derivato dai risultati.
            self.store.players.update(player.model_copy(update=data.model_dump()))
        return self.get(player_id)

    def delete(self, player_id: UUID) -> None:
        """Elimina il giocatore e la sua foto; vietato se compare tra i marcatori (409)."""
        with self.store.transaction():
            player = self._get(player_id)
            scored_in = [
                m for m in self.store.matches.list()
                if any(mk.giocatore_id == player_id for mk in m.marcatori)
            ]
            if scored_in:
                raise ConflictError(
                    f"Il giocatore compare tra i marcatori di {len(scored_in)} partite: "
                    "modifica prima quei risultati",
                    details={"partite": [str(m.id) for m in scored_in]},
                )
            self.store.players.delete(player_id)
        self.uploads.delete(player.foto)

    def set_photo(self, player_id: UUID, data: bytes) -> PlayerOut:
        """Salva la nuova foto e cancella la precedente."""
        self._get(player_id)
        # Il file si scrive fuori dal lock; dentro si ricontrolla che il
        # giocatore esista ancora (potrebbe essere stato eliminato nel frattempo).
        url = self.uploads.save_image("players", player_id, data)
        with self.store.transaction():
            player = self.store.players.get(player_id)
            if player is None:
                self.uploads.delete(url)
                raise NotFoundError("Giocatore non trovato")
            old = player.foto
            self.store.players.update(player.model_copy(update={"foto": url}))
        self.uploads.delete(old)
        return self.get(player_id)

    def remove_photo(self, player_id: UUID) -> PlayerOut:
        """Rimuove la foto; il file si cancella dopo aver aggiornato i dati."""
        with self.store.transaction():
            player = self._get(player_id)
            self.store.players.update(player.model_copy(update={"foto": None}))
        self.uploads.delete(player.foto)
        return self.get(player_id)
