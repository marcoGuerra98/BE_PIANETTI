"""Endpoint di autenticazione dell'amministratore."""

from fastapi import APIRouter, Request

from app.deps import AdminDep, ServicesDep
from app.models.auth import ChangePasswordIn, LoginIn, MeOut, TokenOut

router = APIRouter(prefix="/auth", tags=["Autenticazione"])


@router.post("/login", response_model=TokenOut, responses={401: {}, 429: {}})
def login(data: LoginIn, request: Request, services: ServicesDep):
    """Restituisce un JWT; 401 per credenziali errate, 429 dopo troppi tentativi."""
    # Chiave del rate limit: IP del client visto dal server (dietro un reverse
    # proxy è l'IP del proxy, a meno di configurare uvicorn --proxy-headers).
    client = request.client.host if request.client else "unknown"
    return services.auth.login(data.username, data.password, client_key=client)


@router.post("/change-password", response_model=TokenOut)
def change_password(data: ChangePasswordIn, services: ServicesDep, username: AdminDep):
    """Cambia la password e restituisce un nuovo token (i precedenti sono invalidati)."""
    return services.auth.change_password(username, data.current_password, data.new_password)


@router.get("/me", response_model=MeOut)
def me(username: AdminDep):
    """Verifica il token e restituisce lo username."""
    return MeOut(username=username)
