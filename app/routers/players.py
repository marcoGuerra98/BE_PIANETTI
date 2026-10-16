"""Endpoint dei giocatori: letture pubbliche, scritture riservate all'amministratore."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Query, UploadFile, status
from starlette.concurrency import run_in_threadpool

from app.deps import AdminDep, ServicesDep
from app.models.player import PlayerCreate, PlayerOut, PlayerUpdate, Ruolo, StatoGiocatore
from app.routers.uploads import read_limited
from app.services.player_service import PlayerSort

router = APIRouter(prefix="/players", tags=["Giocatori"])


@router.get("", response_model=list[PlayerOut])
def list_players(
    services: ServicesDep,
    ruolo: Ruolo | None = None,
    squadra_id: UUID | None = None,
    svincolati: Annotated[
        bool, Query(description="Solo giocatori senza squadra (equivale a stato=svincolato)")
    ] = False,
    q: Annotated[str | None, Query(description="Ricerca su nome e cognome, in qualsiasi ordine")] = None,
    sort: PlayerSort = PlayerSort.OVERALL_DESC,
    fascia: Annotated[int | None, Query(ge=1, le=4, description="Fascia di valore (1 = migliore)")] = None,
    stato: Annotated[StatoGiocatore | None, Query(description="svincolato o assegnato a una squadra")] = None,
):
    """Elenco con filtri per ruolo, fascia, squadra, stato e ricerca testuale `q`.

    Esempio: `?stato=assegnato&sort=ruolo` elenca i giocatori di tutte le
    squadre ordinati per ruolo (POR, DIF, CEN, ATT), cognome e nome.
    """
    return services.players.list(
        ruolo=ruolo, squadra_id=squadra_id, svincolati=svincolati, q=q, sort=sort, fascia=fascia, stato=stato
    )


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
    # Il service è sincrono (I/O su file e FileLock): va eseguito nel threadpool
    # per non bloccare l'event loop di questo endpoint async.
    return await run_in_threadpool(services.players.set_photo, player_id, data)


@router.delete("/{player_id}/photo", response_model=PlayerOut)
def delete_photo(player_id: UUID, services: ServicesDep, _: AdminDep):
    return services.players.remove_photo(player_id)
