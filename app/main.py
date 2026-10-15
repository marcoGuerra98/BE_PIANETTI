"""Punto di ingresso: composizione dei service e creazione dell'app FastAPI.

Avvio:  uvicorn app.main:create_app --factory
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings, get_settings
from app.deps import Services
from app.errors import AuthError, DomainError, TooManyAttemptsError
from app.repositories.json_store import JsonDataStore
from app.routers import auth, players, schedule, standings, teams
from app.services.auth_service import AuthService, LoginRateLimiter
from app.services.match_service import MatchService
from app.services.player_service import PlayerService
from app.services.schedule_service import ScheduleService
from app.services.standings_service import StandingsService
from app.services.team_service import TeamService
from app.services.upload_service import UploadService

MIN_SECRET_LENGTH = 32


def build_services(settings: Settings) -> Services:
    """Istanzia store e service collegandoli tra loro (usata anche da seed.py e dai test)."""
    store = JsonDataStore(settings.resolved_data_dir)
    uploads = UploadService(settings.uploads_dir, settings.max_upload_bytes)
    schedule_svc = ScheduleService(store)
    return Services(
        settings=settings,
        store=store,
        uploads=uploads,
        players=PlayerService(store, uploads),
        teams=TeamService(store, uploads, schedule_svc),
        schedule=schedule_svc,
        matches=MatchService(store, schedule_svc),
        standings=StandingsService(store),
        auth=AuthService(
            store.admin,
            secret_key=settings.secret_key,
            expire_minutes=settings.access_token_expire_minutes,
            algorithm=settings.jwt_algorithm,
            limiter=LoginRateLimiter(settings.login_max_attempts, settings.login_lockout_seconds),
        ),
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Factory dell'applicazione; senza argomenti legge le impostazioni dall'ambiente.

    Solleva RuntimeError se SECRET_KEY manca o è troppo corta.
    """
    settings = settings or get_settings()
    if len(settings.secret_key) < MIN_SECRET_LENGTH:
        raise RuntimeError(
            f"SECRET_KEY mancante o troppo corta (minimo {MIN_SECRET_LENGTH} caratteri). "
            "Copia .env.example in .env e imposta una chiave casuale."
        )

    app = FastAPI(
        title="Torneo di Calcio - API",
        description="Gestione giocatori, squadre, calendario e classifiche. "
        "Le operazioni di scrittura richiedono il login amministratore (pulsante Authorize).",
        version="1.0.0",
    )
    app.state.services = build_services(settings)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Traduzione eccezioni di dominio → HTTP: corpo {"detail": ..., "details"?: ...}.
    @app.exception_handler(DomainError)
    async def domain_error_handler(_: Request, exc: DomainError):
        body = {"detail": exc.message}
        if exc.details is not None:
            body["details"] = exc.details
        headers = {}
        if isinstance(exc, AuthError):
            headers["WWW-Authenticate"] = "Bearer"
        if isinstance(exc, TooManyAttemptsError):
            headers["Retry-After"] = str(exc.retry_after)
        return JSONResponse(status_code=exc.status_code, content=body, headers=headers)

    for r in (auth.router, players.router, teams.router, schedule.router, standings.router):
        app.include_router(r)

    app.mount("/uploads", StaticFiles(directory=settings.uploads_dir), name="uploads")

    @app.get("/health", tags=["Sistema"])
    def health():
        return {"status": "ok"}

    return app
