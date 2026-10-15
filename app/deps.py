"""Dipendenze FastAPI: accesso ai service e protezione degli endpoint di scrittura."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings
from app.errors import AuthError
from app.repositories.base import DataStore
from app.services.auth_service import AuthService
from app.services.match_service import MatchService
from app.services.player_service import PlayerService
from app.services.schedule_service import ScheduleService
from app.services.standings_service import StandingsService
from app.services.team_service import TeamService
from app.services.upload_service import UploadService


@dataclass
class Services:
    """Contenitore dei service condivisi, creato una volta in `build_services`."""

    settings: Settings
    store: DataStore
    uploads: UploadService
    players: PlayerService
    teams: TeamService
    schedule: ScheduleService
    matches: MatchService
    standings: StandingsService
    auth: AuthService


def get_services(request: Request) -> Services:
    """Recupera i service salvati in `app.state` da `create_app`."""
    return request.app.state.services


ServicesDep = Annotated[Services, Depends(get_services)]

# auto_error=False: l'assenza del token è gestita da require_admin, così la
# risposta è un 401 nel formato d'errore comune con header WWW-Authenticate.
_bearer = HTTPBearer(auto_error=False)


def require_admin(
    services: ServicesDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> str:
    """Protegge gli endpoint di scrittura: 401 se il token manca, è scaduto o non è valido."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthError("Autenticazione richiesta")
    return services.auth.verify_token(credentials.credentials)


# Da aggiungere come parametro agli endpoint protetti; il valore è lo username.
AdminDep = Annotated[str, Depends(require_admin)]
