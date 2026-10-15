"""Utility condivise dagli endpoint di upload."""

from fastapi import UploadFile

from app.services.upload_service import PayloadTooLargeError

CHUNK = 64 * 1024


async def read_limited(file: UploadFile, max_bytes: int) -> bytes:
    """Legge l'upload a blocchi interrompendosi appena supera il limite."""
    buf = bytearray()
    while chunk := await file.read(CHUNK):
        buf += chunk
        if len(buf) > max_bytes:
            raise PayloadTooLargeError(f"File troppo grande (massimo {max_bytes // (1024 * 1024)} MB)")
    return bytes(buf)
