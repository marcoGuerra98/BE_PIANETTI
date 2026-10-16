"""Endpoint del torneo nel suo insieme (operazioni riservate all'amministratore)."""

from fastapi import APIRouter, Request

from app.deps import AdminDep, ServicesDep
from app.models.tournament import ResetIn, ResetResult

router = APIRouter(prefix="/tournament", tags=["Torneo"])


@router.post(
    "/reset",
    response_model=ResetResult,
    responses={
        401: {"description": "Token mancante o non valido"},
        403: {"description": "Password non corretta"},
        429: {"description": "Troppi tentativi falliti"},
    },
)
def reset_tournament(data: ResetIn, request: Request, services: ServicesDep, username: AdminDep):
    """Reset di fine torneo: elimina tutte le partite, svincola tutti i giocatori e ne azzera i goal.

    Le squadre restano. Richiede, oltre al token, la password dell'amministratore.
    """
    # Stessa chiave del login (IP del client) ma con prefisso: contatori separati.
    client = request.client.host if request.client else "unknown"
    return services.tournament.reset(username, data.password, client_key=f"reset:{client}")
