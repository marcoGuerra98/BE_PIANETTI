"""Endpoint dei giocatori: letture pubbliche, scritture riservate all'amministratore."""

from uuid import UUID

from fastapi import APIRouter, File, UploadFile, status

from app.deps import AdminDep, ServicesDep
from app.models.player import PlayerCreate, PlayerOut, PlayerUpdate, Ruolo
from app.routers.uploads import read_limited
from app.services.player_service import PlayerSort

router = APIRouter(prefix="/players", tags=["Giocatori"])


@router.get("", response_model=list[PlayerOut])
def list_players(
    services: ServicesDep,
    ruolo: Ruolo | None = None,
    squadra_id: UUID | None = None,
    svincolati: bool = False,
    q: str | None = None,
    sort: PlayerSort = PlayerSort.OVERALL_DESC,
):
    """Elenco con filtri per ruolo, squadra o svincolati e ricerca testuale `q`."""
    return services.players.list(ruolo=ruolo, squadra_id=squadra_id, svincolati=svincolati, q=q, sort=sort)


@router.get("/{player_id}", response_model=PlayerOut)
def get_player(player_id: UUID, services: ServicesDep):
    return services.players.get(player_id)


@router.post("", response_model=PlayerOut, status_code=status.HTTP_201_CREATED)
def create_player(data: PlayerCreate, services: ServicesDep, _: AdminDep):
    return services.players.create(data)


@router.put("/{player_id}", response_model=PlayerOut)
def update_player(player_id: UUID, data: PlayerUpdate, services: ServicesDep, _: AdminDep):
    return services.players.update(player_id, data)


@router.delete("/{player_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_player(player_id: UUID, services: ServicesDep, _: AdminDep):
    services.players.delete(player_id)


@router.post("/{player_id}/photo", response_model=PlayerOut)
async def upload_photo(player_id: UUID, services: ServicesDep, _: AdminDep, file: UploadFile = File(...)):
    """Carica la foto (JPEG, PNG o WebP, massimo 2 MB) sostituendo la precedente."""
    data = await read_limited(file, services.settings.max_upload_bytes)
    return services.players.set_photo(player_id, data)


@router.delete("/{player_id}/photo", response_model=PlayerOut)
def delete_photo(player_id: UUID, services: ServicesDep, _: AdminDep):
    return services.players.remove_photo(player_id)
