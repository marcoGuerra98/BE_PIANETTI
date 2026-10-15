"""Endpoint delle squadre: letture pubbliche, scritture riservate all'amministratore."""

from uuid import UUID

from fastapi import APIRouter, File, UploadFile, status
from starlette.concurrency import run_in_threadpool

from app.deps import AdminDep, ServicesDep
from app.models.team import Team, TeamCreate, TeamDetail, TeamUpdate
from app.routers.uploads import read_limited
from app.services.team_service import TeamDeleteResult

router = APIRouter(prefix="/teams", tags=["Squadre"])


@router.get("", response_model=list[Team])
def list_teams(services: ServicesDep):
    return services.teams.list()


@router.get("/{team_id}", response_model=TeamDetail)
def get_team(team_id: UUID, services: ServicesDep):
    return services.teams.get(team_id)


@router.post("", response_model=Team, status_code=status.HTTP_201_CREATED)
def create_team(data: TeamCreate, services: ServicesDep, _: AdminDep):
    return services.teams.create(data)


@router.put("/{team_id}", response_model=Team)
def update_team(team_id: UUID, data: TeamUpdate, services: ServicesDep, _: AdminDep):
    return services.teams.update(team_id, data)


@router.delete(
    "/{team_id}",
    response_model=TeamDeleteResult,
    responses={409: {"description": "La squadra ha partite già giocate: ripetere con force=true"}},
)
def delete_team(team_id: UUID, services: ServicesDep, _: AdminDep, force: bool = False):
    """Elimina la squadra svincolando i giocatori; restituisce il riepilogo delle modifiche."""
    return services.teams.delete(team_id, force=force)


@router.post("/{team_id}/logo", response_model=Team)
async def upload_logo(team_id: UUID, services: ServicesDep, _: AdminDep, file: UploadFile = File(...)):
    """Carica lo stemma (JPEG, PNG o WebP, massimo 2 MB) sostituendo il precedente."""
    data = await read_limited(file, services.settings.max_upload_bytes)
    # Il service è sincrono (I/O su file e FileLock): va eseguito nel threadpool
    # per non bloccare l'event loop di questo endpoint async.
    return await run_in_threadpool(services.teams.set_logo, team_id, data)


@router.delete("/{team_id}/logo", response_model=Team)
def delete_logo(team_id: UUID, services: ServicesDep, _: AdminDep):
    return services.teams.remove_logo(team_id)
