"""Modelli di partite, risultati, marcatori e calendario."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


class Fase(StrEnum):
    """Fase del torneo a cui appartiene una partita."""

    GIRONE = "GIRONE"
    SEMIFINALE = "SEMIFINALE"
    FINALE_3_4 = "FINALE_3_4"
    FINALE_1_2 = "FINALE_1_2"


# Fasi a eliminazione diretta, generate automaticamente da sync_final_phase.
KNOCKOUT_PHASES = {Fase.SEMIFINALE, Fase.FINALE_3_4, Fase.FINALE_1_2}


class Marcatore(BaseModel):
    """Voce marcatore persistita in una partita (goal aggregati per giocatore)."""

    # None solo per gli autogol, che non sono attribuiti a nessun giocatore.
    giocatore_id: UUID | None
    # Squadra a cui viene assegnato il gol, fissata al momento dell'inserimento:
    # resta valida anche se in seguito il giocatore cambia squadra.
    # Per un autogol è la squadra che beneficia del gol.
    squadra_id: UUID
    goal: int = Field(ge=1, le=50)
    autogol: bool = False

    @model_validator(mode="after")
    def _check_autogol(self):
        if self.autogol != (self.giocatore_id is None):
            raise ValueError("Un autogol non ha giocatore; un gol normale richiede il giocatore")
        return self


class Match(BaseModel):
    """Entità partita persistita.

    `gol_casa`/`gol_trasferta` valgono None finché `giocata` è False.
    """

    id: UUID = Field(default_factory=uuid4)
    giornata: int = Field(ge=1)
    fase: Fase = Fase.GIRONE
    squadra_casa_id: UUID
    squadra_trasferta_id: UUID
    data_ora: datetime | None = None
    gol_casa: int | None = None
    gol_trasferta: int | None = None
    giocata: bool = False
    marcatori: list[Marcatore] = []
    # Solo fase finale: squadra vincitrice ai rigori in caso di pareggio.
    vincitore_rigori_id: UUID | None = None

    def involves(self, team_id: UUID) -> bool:
        """True se la squadra gioca questa partita (in casa o in trasferta)."""
        return team_id in (self.squadra_casa_id, self.squadra_trasferta_id)

    def winner_id(self) -> UUID | None:
        """Vincitrice della partita giocata; in caso di pareggio quella ai rigori (None nel girone)."""
        if not self.giocata:
            return None
        if self.gol_casa > self.gol_trasferta:
            return self.squadra_casa_id
        if self.gol_trasferta > self.gol_casa:
            return self.squadra_trasferta_id
        return self.vincitore_rigori_id

    def loser_id(self) -> UUID | None:
        """Perdente della partita, None se non giocata o senza vincitrice."""
        w = self.winner_id()
        if w is None:
            return None
        return self.squadra_trasferta_id if w == self.squadra_casa_id else self.squadra_casa_id


# --- Input API ---


class MatchUpdate(BaseModel):
    """PATCH: si aggiornano solo i campi presenti nel body."""

    giornata: int | None = Field(default=None, ge=1)
    squadra_casa_id: UUID | None = None
    squadra_trasferta_id: UUID | None = None
    data_ora: datetime | None = None


class MarcatoreIn(BaseModel):
    """Gol normale: `giocatore_id`. Autogol: `autogol=true` e `squadra_id` della squadra
    che beneficia del gol (cioè l'avversaria di chi l'ha segnato)."""

    giocatore_id: UUID | None = None
    goal: int = Field(ge=1, le=50)
    autogol: bool = False
    squadra_id: UUID | None = None

    @model_validator(mode="after")
    def _check(self):
        if self.autogol:
            if self.giocatore_id is not None:
                raise ValueError("Un autogol non va attribuito a un giocatore")
            if self.squadra_id is None:
                raise ValueError("Per un autogol indica la squadra che beneficia del gol (squadra_id)")
        elif self.giocatore_id is None:
            raise ValueError("Indica il giocatore che ha segnato")
        return self


class ResultIn(BaseModel):
    """Body di PUT /matches/{id}/result.

    La somma dei goal dei marcatori (autogol compresi) deve coincidere col
    punteggio di ciascuna squadra; `vincitore_rigori_id` serve solo per un
    pareggio nella fase finale.
    """

    gol_casa: int = Field(ge=0, le=99)
    gol_trasferta: int = Field(ge=0, le=99)
    marcatori: list[MarcatoreIn] = []
    vincitore_rigori_id: UUID | None = None


# --- Output API ---


class MarcatoreOut(Marcatore):
    """Marcatore arricchito con nome e cognome del giocatore (None per gli autogol)."""

    giocatore_nome: str | None = None
    giocatore_cognome: str | None = None


class MatchOut(Match):
    """Partita arricchita con nomi e stemmi delle squadre."""

    squadra_casa_nome: str | None = None
    squadra_casa_stemma: str | None = None
    squadra_trasferta_nome: str | None = None
    squadra_trasferta_stemma: str | None = None
    marcatori: list[MarcatoreOut] = []


class TeamRef(BaseModel):
    """Riferimento sintetico a una squadra (usato per le squadre a riposo)."""

    id: UUID
    nome: str
    stemma: str | None = None


class GiornataOut(BaseModel):
    """Una giornata del calendario con le sue partite e le squadre che riposano."""

    giornata: int
    fase: Fase
    partite: list[MatchOut]
    riposa: list[TeamRef] = []


class ScheduleOut(BaseModel):
    """Calendario completo con i contatori di avanzamento."""

    giornate: list[GiornataOut]
    totale_partite: int
    partite_giocate: int
    girone_completato: bool
