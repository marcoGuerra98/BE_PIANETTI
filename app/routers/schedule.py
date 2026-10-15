"""Endpoint del calendario e delle singole partite."""

from uuid import UUID

from fastapi import APIRouter, status

from app.deps import AdminDep, ServicesDep
from app.models.match import MatchOut, MatchUpdate, ResultIn, ScheduleOut

router = APIRouter(tags=["Calendario"])


@router.get("/schedule", response_model=ScheduleOut)
def get_schedule(services: ServicesDep):
    return services.schedule.get_schedule()


@router.post(
    "/schedule/generate",
    response_model=ScheduleOut,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"description": "Esiste già un calendario: ripetere con confirm=true"}},
)
def generate_schedule(services: ServicesDep, _: AdminDep, confirm: bool = False, shuffle: bool = True):
    """Genera il girone unico (solo andata). Le semifinali (1ª-4ª, 2ª-3ª) vengono
    create automaticamente al termine del girone, le finali al termine delle semifinali."""
    return services.schedule.generate(confirm=confirm, shuffle=shuffle)


@router.delete(
    "/schedule",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={409: {"description": "Richiede confirm=true"}},
)
def delete_schedule(services: ServicesDep, _: AdminDep, confirm: bool = False):
    """Elimina tutte le partite e azzera i goal derivati dai risultati."""
    services.schedule.delete(confirm=confirm)


@router.get("/matches/{match_id}", response_model=MatchOut, tags=["Partite"])
def get_match(match_id: UUID, services: ServicesDep):
    return services.matches.get(match_id)


@router.patch("/matches/{match_id}", response_model=MatchOut, tags=["Partite"])
def update_match(match_id: UUID, data: MatchUpdate, services: ServicesDep, _: AdminDep):
    """Modifica parziale: data/ora, giornata e squadre (queste ultime solo nel girone)."""
    return services.matches.update(match_id, data)


@router.put("/matches/{match_id}/result", response_model=MatchOut, tags=["Partite"])
def set_result(match_id: UUID, data: ResultIn, services: ServicesDep, _: AdminDep):
    """Inserisce o sostituisce risultato e marcatori; aggiorna goal e fase finale."""
    return services.matches.set_result(match_id, data)


@router.delete("/matches/{match_id}/result", response_model=MatchOut, tags=["Partite"])
def clear_result(match_id: UUID, services: ServicesDep, _: AdminDep):
    """Annulla il risultato; 409 se la fase successiva ha già risultati che ne dipendono."""
    return services.matches.clear_result(match_id)
