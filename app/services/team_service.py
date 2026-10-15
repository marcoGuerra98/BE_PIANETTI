"""Gestione delle squadre: CRUD, stemmi ed eliminazione con integrità referenziale."""

from uuid import UUID

from pydantic import BaseModel

from app.errors import ConflictError, NotFoundError
from app.models.match import KNOCKOUT_PHASES
from app.models.team import Team, TeamCreate, TeamDetail, TeamUpdate
from app.repositories.base import DataStore
from app.services.goals import recalculate_goals
from app.services.schedule_service import ScheduleService
from app.services.upload_service import UploadService
from app.services.views import player_out


class TeamDeleteResult(BaseModel):
    """Riepilogo degli effetti a cascata di DELETE /teams/{id}."""

    giocatori_svincolati: int
    partite_rimosse: int


class TeamService:
    """CRUD delle squadre; nome unico senza distinzione di maiuscole."""

    def __init__(self, store: DataStore, uploads: UploadService, schedule: ScheduleService):
        self.store = store
        self.uploads = uploads
        self.schedule = schedule

    def _get(self, team_id: UUID) -> Team:
        team = self.store.teams.get(team_id)
        if team is None:
            raise NotFoundError("Squadra non trovata")
        return team

    def _check_unique(self, nome: str, exclude_id: UUID | None = None) -> None:
        existing = self.store.teams.get_by_name(nome)
        if existing is not None and existing.id != exclude_id:
            raise ConflictError(f"Esiste già una squadra chiamata '{existing.nome}'")

    def list(self) -> list[Team]:
        """Squadre ordinate per nome."""
        return sorted(self.store.teams.list(), key=lambda t: t.nome.casefold())

    def get(self, team_id: UUID) -> TeamDetail:
        """Squadra con la rosa ordinata per ruolo (POR, DIF, CEN, ATT), overall decrescente e cognome."""
        team = self._get(team_id)
        teams = {team.id: team}
        roster = sorted(
            (p for p in self.store.players.list() if p.squadra_id == team_id),
            key=lambda p: ("POR DIF CEN ATT".index(p.ruolo), -p.overall, p.cognome.casefold()),
        )
        return TeamDetail(**team.model_dump(), giocatori=[player_out(p, teams) for p in roster])

    def create(self, data: TeamCreate) -> Team:
        with self.store.transaction():
            self._check_unique(data.nome)
            return self.store.teams.add(Team(**data.model_dump()))

    def update(self, team_id: UUID, data: TeamUpdate) -> Team:
        # Giocatori e partite referenziano la squadra per id: la rinomina non
        # richiede aggiornamenti a cascata, il nome viene risolto in lettura.
        with self.store.transaction():
            team = self._get(team_id)
            self._check_unique(data.nome, exclude_id=team_id)
            return self.store.teams.update(team.model_copy(update=data.model_dump()))

    def delete(self, team_id: UUID, force: bool = False) -> TeamDeleteResult:
        """Elimina la squadra mantenendo coerenti i riferimenti.

        - i giocatori della rosa diventano svincolati;
        - le sue partite non giocate vengono rimosse;
        - se ha partite giocate serve `force=True` (altrimenti 409): vengono
          rimosse anche quelle, tutta la fase finale e i goal relativi;
        - infine la fase finale viene riallineata al girone rimasto.
        """
        with self.store.transaction():
            team = self._get(team_id)
            matches = self.store.matches.list()
            own = [m for m in matches if m.involves(team_id)]
            played = [m for m in own if m.giocata]
            if played and not force:
                teams = {t.id: t.nome for t in self.store.teams.list()}
                raise ConflictError(
                    f"La squadra ha {len(played)} partite già giocate: eliminandola verranno "
                    "rimosse anche quelle (con i relativi goal). Ripeti con force=true per confermare.",
                    details={
                        "partite_giocate": [
                            {
                                "id": str(m.id),
                                "giornata": m.giornata,
                                "descrizione": f"{teams.get(m.squadra_casa_id)} {m.gol_casa}-"
                                f"{m.gol_trasferta} {teams.get(m.squadra_trasferta_id)}",
                            }
                            for m in played
                        ]
                    },
                )

            to_remove = {m.id: m for m in own}
            if played:
                # Il girone cambia: la fase finale va ricalcolata da zero.
                to_remove |= {m.id: m for m in matches if m.fase in KNOCKOUT_PHASES}
            self.store.matches.delete_many(to_remove)

            roster = [p for p in self.store.players.list() if p.squadra_id == team_id]
            self.store.players.update_many(p.model_copy(update={"squadra_id": None}) for p in roster)

            scorers = {mk.giocatore_id for m in to_remove.values() for mk in m.marcatori if mk.giocatore_id}
            if scorers:
                recalculate_goals(self.store, scorers)

            self.store.teams.delete(team_id)
            self.schedule.sync_final_phase()

        self.uploads.delete(team.stemma)
        return TeamDeleteResult(giocatori_svincolati=len(roster), partite_rimosse=len(to_remove))

    def set_logo(self, team_id: UUID, data: bytes) -> Team:
        """Salva il nuovo stemma e cancella il precedente (stesso schema di set_photo)."""
        self._get(team_id)
        url = self.uploads.save_image("teams", team_id, data)
        with self.store.transaction():
            team = self.store.teams.get(team_id)
            if team is None:
                self.uploads.delete(url)
                raise NotFoundError("Squadra non trovata")
            old = team.stemma
            team = self.store.teams.update(team.model_copy(update={"stemma": url}))
        self.uploads.delete(old)
        return team

    def remove_logo(self, team_id: UUID) -> Team:
        """Rimuove lo stemma e cancella il file."""
        with self.store.transaction():
            team = self._get(team_id)
            updated = self.store.teams.update(team.model_copy(update={"stemma": None}))
        self.uploads.delete(team.stemma)
        return updated
