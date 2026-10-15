"""Modelli delle squadre."""

from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator

from app.models.player import PlayerOut


class TeamBase(BaseModel):
    """Campi modificabili; il nome è unico (case-insensitive), controllato nel service."""

    nome: str = Field(min_length=1, max_length=60)

    @field_validator("nome", mode="before")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v


class TeamCreate(TeamBase):
    pass


class TeamUpdate(TeamBase):
    pass


class Team(TeamBase):
    """Entità squadra persistita; `stemma` è l'URL relativo dell'immagine."""

    id: UUID = Field(default_factory=uuid4)
    stemma: str | None = None


class TeamDetail(Team):
    """Squadra con la rosa, per GET /teams/{id}."""

    giocatori: list[PlayerOut] = []
