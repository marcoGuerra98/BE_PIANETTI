"""Interfacce del layer di persistenza.

I service dipendono solo da queste astrazioni: per passare a un database vero
basta fornire un'altra implementazione di `DataStore` (es. SQLAlchemy), dove
`transaction()` diventa una transazione del DB.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterable
from contextlib import AbstractContextManager
from typing import Generic, TypeVar
from uuid import UUID

from app.models.auth import AdminCredentials
from app.models.match import Match
from app.models.player import Player
from app.models.team import Team

T = TypeVar("T")


class Repository(ABC, Generic[T]):
    """Repository CRUD generico per entità identificate da `id: UUID`.

    `update`/`update_many` sollevano KeyError se un elemento non esiste.
    """

    @abstractmethod
    def list(self) -> list[T]: ...

    @abstractmethod
    def get(self, item_id: UUID) -> T | None: ...

    @abstractmethod
    def add(self, item: T) -> T: ...

    @abstractmethod
    def update(self, item: T) -> T: ...

    @abstractmethod
    def update_many(self, items: Iterable[T]) -> None: ...

    @abstractmethod
    def delete(self, item_id: UUID) -> bool: ...

    @abstractmethod
    def delete_many(self, item_ids: Iterable[UUID]) -> int:
        """Elimina gli elementi indicati e restituisce quanti ne ha rimossi."""


class PlayerRepository(Repository[Player], ABC):
    pass


class TeamRepository(Repository[Team], ABC):
    @abstractmethod
    def get_by_name(self, nome: str) -> Team | None:
        """Ricerca case-insensitive."""


class MatchRepository(Repository[Match], ABC):
    pass


class AdminRepository(ABC):
    """Credenziali dell'unico amministratore (None se non ancora creato)."""

    @abstractmethod
    def get(self) -> AdminCredentials | None: ...

    @abstractmethod
    def save(self, credentials: AdminCredentials) -> None: ...


class DataStore(ABC):
    """Punto di accesso unico ai repository, condiviso da tutti i service."""

    players: PlayerRepository
    teams: TeamRepository
    matches: MatchRepository
    admin: AdminRepository

    @abstractmethod
    def transaction(self) -> AbstractContextManager:
        """Serializza le operazioni di lettura-modifica-scrittura su più entità."""
