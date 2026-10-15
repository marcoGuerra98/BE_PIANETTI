"""Implementazione su file JSON.

- Ogni scrittura è atomica: si scrive su un file temporaneo nella stessa
  cartella, si fa fsync e poi `os.replace`, così un lettore vede sempre o la
  versione vecchia o quella nuova, mai un file troncato.
- Un unico FileLock (rientrante) serializza tutte le scritture, anche tra
  processi diversi (es. uvicorn + script CLI).
"""

import json
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Generic, TypeVar
from uuid import UUID

from filelock import FileLock
from pydantic import BaseModel, TypeAdapter

from app.models.auth import AdminCredentials
from app.models.match import Match
from app.models.player import Player
from app.models.team import Team
from app.repositories.base import (
    AdminRepository,
    DataStore,
    MatchRepository,
    PlayerRepository,
    Repository,
    TeamRepository,
)

M = TypeVar("M", bound=BaseModel)


def atomic_write_json(path: Path, data) -> None:
    """Scrive `data` in JSON sostituendo il file in modo atomico."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Il temporaneo sta nella stessa cartella: os.replace è atomico solo
    # all'interno dello stesso filesystem.
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            # flush + fsync: i dati sono su disco prima che il file diventi visibile.
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        # Anche su KeyboardInterrupt: non lasciare temporanei orfani.
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def read_json(path: Path, default):
    """Legge un file JSON; file assente o vuoto restituiscono `default`."""
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as f:
        content = f.read().strip()
    return json.loads(content) if content else default


class JsonRepository(Repository[M], Generic[M]):
    """Repository su un file JSON contenente la lista delle entità.

    Ogni operazione rilegge l'intero file (nessuna cache in memoria), così più
    processi vedono sempre dati aggiornati. Le letture non prendono il lock
    perché la scrittura atomica garantisce un file sempre integro; le scritture
    sì, per non perdere modifiche concorrenti (lettura-modifica-scrittura).
    """

    def __init__(self, path: Path, model: type[M], lock: FileLock):
        self._path = path
        self._lock = lock
        self._adapter = TypeAdapter(list[model])

    def _load(self) -> list[M]:
        return self._adapter.validate_python(read_json(self._path, []))

    def _save(self, items: list[M]) -> None:
        atomic_write_json(self._path, self._adapter.dump_python(items, mode="json"))

    def list(self) -> list[M]:
        return self._load()

    def get(self, item_id: UUID) -> M | None:
        return next((i for i in self._load() if i.id == item_id), None)

    def add(self, item: M) -> M:
        with self._lock:
            items = self._load()
            items.append(item)
            self._save(items)
        return item

    def update(self, item: M) -> M:
        self.update_many([item])
        return item

    def update_many(self, items: Iterable[M]) -> None:
        changes = {i.id: i for i in items}
        if not changes:
            return
        with self._lock:
            current = self._load()
            # Tutto o niente: se manca anche un solo id non si scrive nulla.
            found = {i.id for i in current} & changes.keys()
            missing = changes.keys() - found
            if missing:
                raise KeyError(f"Elementi inesistenti: {missing}")
            self._save([changes.get(i.id, i) for i in current])

    def delete(self, item_id: UUID) -> bool:
        return self.delete_many([item_id]) > 0

    def delete_many(self, item_ids: Iterable[UUID]) -> int:
        ids = set(item_ids)
        if not ids:
            return 0
        with self._lock:
            current = self._load()
            kept = [i for i in current if i.id not in ids]
            if len(kept) != len(current):
                self._save(kept)
            return len(current) - len(kept)


class JsonPlayerRepository(JsonRepository[Player], PlayerRepository):
    pass


class JsonTeamRepository(JsonRepository[Team], TeamRepository):
    def get_by_name(self, nome: str) -> Team | None:
        key = nome.strip().casefold()
        return next((t for t in self._load() if t.nome.casefold() == key), None)


class JsonMatchRepository(JsonRepository[Match], MatchRepository):
    pass


class JsonAdminRepository(AdminRepository):
    """Credenziali admin in un singolo oggetto JSON (data/admin.json)."""

    def __init__(self, path: Path, lock: FileLock):
        self._path = path
        self._lock = lock

    def get(self) -> AdminCredentials | None:
        data = read_json(self._path, None)
        return AdminCredentials.model_validate(data) if data else None

    def save(self, credentials: AdminCredentials) -> None:
        with self._lock:
            atomic_write_json(self._path, credentials.model_dump(mode="json"))
        # Permessi ristretti al proprietario; ignorati dove non supportati.
        try:
            os.chmod(self._path, 0o600)
        except OSError:
            pass


class JsonDataStore(DataStore):
    """DataStore su file: players.json, teams.json, matches.json, admin.json in `data_dir`."""

    def __init__(self, data_dir: Path):
        data_dir.mkdir(parents=True, exist_ok=True)
        # Un solo lock condiviso da tutti i repository: un service può aprire
        # transaction() e chiamare più repository senza deadlock (lock rientrante).
        self._lock = FileLock(data_dir / ".store.lock", timeout=10)
        self.players = JsonPlayerRepository(data_dir / "players.json", Player, self._lock)
        self.teams = JsonTeamRepository(data_dir / "teams.json", Team, self._lock)
        self.matches = JsonMatchRepository(data_dir / "matches.json", Match, self._lock)
        self.admin = JsonAdminRepository(data_dir / "admin.json", self._lock)

    def transaction(self):
        """Lock globale come context manager.

        Serializza le operazioni ma non offre rollback: le scritture già
        eseguite restano anche se il blocco termina con un'eccezione.
        """
        return self._lock
