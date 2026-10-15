"""Eccezioni di dominio. I service sollevano queste, main.py le traduce in HTTP."""

from typing import Any


class DomainError(Exception):
    """Base delle eccezioni di dominio.

    `status_code` è il codice HTTP restituito; `details` (facoltativo) viene
    incluso nel corpo della risposta per dare al client informazioni strutturate.
    """

    status_code = 400

    def __init__(self, message: str, details: Any = None):
        super().__init__(message)
        self.message = message
        self.details = details


class NotFoundError(DomainError):
    """Entità richiesta inesistente."""

    status_code = 404


class ConflictError(DomainError):
    """Operazione in conflitto con lo stato attuale (spesso risolvibile con confirm/force)."""

    status_code = 409


class ValidationError(DomainError):
    """Dati validi nel formato ma non ammessi dalle regole di business."""

    status_code = 422


class AuthError(DomainError):
    """Autenticazione mancante o non valida."""

    status_code = 401


class TooManyAttemptsError(DomainError):
    """Troppi tentativi di login falliti; `retry_after` (secondi) finisce nell'header Retry-After."""

    status_code = 429

    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.retry_after = retry_after
