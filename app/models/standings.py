"""Modelli di output delle classifiche (calcolate al volo, mai salvate)."""

from uuid import UUID

from pydantic import BaseModel

from app.models.player import Ruolo


class StandingRow(BaseModel):
    """Riga della classifica del girone."""

    posizione: int
    squadra_id: UUID
    squadra_nome: str
    stemma: str | None = None
    giocate: int = 0
    vinte: int = 0
    pareggiate: int = 0
    perse: int = 0
    gol_fatti: int = 0
    gol_subiti: int = 0
    differenza_reti: int = 0
    punti: int = 0


class ScorerRow(BaseModel):
    """Riga della classifica marcatori; a pari goal la posizione è condivisa."""

    posizione: int
    giocatore_id: UUID
    nome: str
    cognome: str
    ruolo: Ruolo
    foto: str | None = None
    squadra_id: UUID | None = None
    squadra_nome: str | None = None
    goal: int
