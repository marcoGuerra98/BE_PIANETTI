"""Modelli dell'autenticazione amministratore."""

from pydantic import BaseModel, Field


class AdminCredentials(BaseModel):
    """Contenuto di data/admin.json. Mai la password in chiaro."""

    username: str
    password_hash: str
    # Incrementata a ogni cambio password: invalida i token emessi prima.
    token_version: int = 0


class LoginIn(BaseModel):
    """Body di POST /auth/login."""

    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class ChangePasswordIn(BaseModel):
    """Body di POST /auth/change-password."""

    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class TokenOut(BaseModel):
    """Token JWT emesso al login; `expires_in` è in secondi."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    username: str


class MeOut(BaseModel):
    """Risposta di GET /auth/me."""

    username: str
