"""Endpoint delle classifiche (pubblici, calcolati a ogni richiesta)."""

from fastapi import APIRouter

from app.deps import ServicesDep
from app.models.standings import ScorerRow, StandingRow

router = APIRouter(prefix="/standings", tags=["Classifiche"])


@router.get("", response_model=list[StandingRow])
def standings(services: ServicesDep):
    """Classifica del girone (le partite della fase finale non contano)."""
    return services.standings.standings()


@router.get("/scorers", response_model=list[ScorerRow])
def scorers(services: ServicesDep):
    """Classifica marcatori, autogol esclusi."""
    return services.standings.scorers()
