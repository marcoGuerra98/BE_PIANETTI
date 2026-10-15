"""Modelli dei giocatori."""

from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


class Ruolo(StrEnum):
    """Ruolo in campo: portiere, difensore, centrocampista, attaccante."""

    POR = "POR"
    DIF = "DIF"
    CEN = "CEN"
    ATT = "ATT"


class PlayerBase(BaseModel):
    """Campi modificabili dal client; `goal` e `foto` sono esclusi di proposito."""

    nome: str = Field(min_length=1, max_length=50)
    cognome: str = Field(min_length=1, max_length=50)
    ruolo: Ruolo
    squadra_id: UUID | None = None
    overall: int = Field(ge=1, le=99)
    descrizione: str = Field(default="", max_length=1000)

    # mode="before": gli spazi si tolgono prima del controllo di lunghezza,
    # così nome e cognome fatti di soli spazi vengono rifiutati.
    @field_validator("nome", "cognome", "descrizione", mode="before")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v


class PlayerCreate(PlayerBase):
    pass


class PlayerUpdate(PlayerBase):
    pass


class Player(PlayerBase):
    """Entità persistita."""

    id: UUID = Field(default_factory=uuid4)
    # Derivato: ricalcolato sempre dai marcatori delle partite giocate (services/goals.py).
    goal: int = Field(default=0, ge=0)
    # URL relativo dell'immagine, es. /uploads/players/<id>-<hex>.png
    foto: str | None = None


class PlayerOut(Player):
    """Entità arricchita con il nome della squadra per la visualizzazione."""

    squadra_nome: str | None = None
