"""Salvataggio e cancellazione delle immagini caricate (foto giocatori, stemmi)."""

import secrets
from pathlib import Path
from uuid import UUID

from app.errors import DomainError, ValidationError


class PayloadTooLargeError(DomainError):
    """File oltre il limite di dimensione (HTTP 413)."""

    status_code = 413


# Il tipo si riconosce dai magic bytes, non dall'estensione o dal Content-Type
# dichiarato dal client (entrambi falsificabili).
def detect_image_ext(data: bytes) -> str | None:
    """Estensione (jpg, png, webp) dedotta dall'intestazione del file, None se non riconosciuta."""
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


class UploadService:
    """Gestisce i file in `uploads_dir/<kind>/`, esposti come `/uploads/<kind>/<file>`."""

    URL_PREFIX = "/uploads"

    def __init__(self, uploads_dir: Path, max_bytes: int):
        self.uploads_dir = uploads_dir
        self.max_bytes = max_bytes
        for kind in ("players", "teams"):
            (uploads_dir / kind).mkdir(parents=True, exist_ok=True)

    def save_image(self, kind: str, owner_id: UUID, data: bytes) -> str:
        """Valida e salva l'immagine, restituendo il suo URL relativo.

        `kind` è "players" o "teams"; il vecchio file non viene toccato qui.
        """
        if len(data) > self.max_bytes:
            raise PayloadTooLargeError(
                f"File troppo grande (massimo {self.max_bytes // (1024 * 1024)} MB)"
            )
        if not data:
            raise ValidationError("File vuoto")
        ext = detect_image_ext(data)
        if ext is None:
            raise ValidationError("Formato non supportato: usa JPEG, PNG o WebP")
        # Suffisso casuale: un nuovo upload cambia URL ed evita immagini vecchie in cache.
        filename = f"{owner_id}-{secrets.token_hex(4)}.{ext}"
        (self.uploads_dir / kind / filename).write_bytes(data)
        return f"{self.URL_PREFIX}/{kind}/{filename}"

    def delete(self, url: str | None) -> None:
        """Cancella il file corrispondente all'URL; URL nulli o esterni sono ignorati."""
        if not url or not url.startswith(self.URL_PREFIX + "/"):
            return
        path = (self.uploads_dir / url.removeprefix(self.URL_PREFIX + "/")).resolve()
        # Difesa da path traversal: si cancella solo dentro uploads/.
        if self.uploads_dir.resolve() in path.parents and path.is_file():
            path.unlink()
