"""Modelli delle operazioni sul torneo nel suo insieme."""

from pydantic import BaseModel, Field


class ResetIn(BaseModel):
    """Body di POST /tournament/reset: conferma con la password dell'amministratore."""

    password: str = Field(min_length=1, max_length=200)


class ResetResult(BaseModel):
    """Riepilogo di POST /tournament/reset."""

    giocatori_aggiornati: int
    partite_rimosse: int
