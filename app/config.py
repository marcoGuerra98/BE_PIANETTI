"""Configurazione dell'applicazione, letta da variabili d'ambiente e dal file `.env`."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Impostazioni dell'applicazione.

    Ogni campo si può sovrascrivere con la variabile d'ambiente omonima in
    maiuscolo (es. `SECRET_KEY`, `CORS_ORIGINS` in formato JSON).
    """

    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    # Chiave di firma dei JWT: vuota di default, create_app rifiuta di avviarsi
    # se è più corta di 32 caratteri.
    secret_key: str = ""
    access_token_expire_minutes: int = 180
    jwt_algorithm: str = "HS256"
    data_dir: Path = BASE_DIR / "data"
    cors_origins: list[str] = ["http://localhost:4200"]

    # Limiti per gli upload di immagini e per il rate limit del login.
    max_upload_bytes: int = 2 * 1024 * 1024
    login_max_attempts: int = 5
    login_lockout_seconds: int = 15 * 60

    @property
    def resolved_data_dir(self) -> Path:
        """Cartella dei dati; un percorso relativo è risolto rispetto alla radice del progetto."""
        d = self.data_dir
        return d if d.is_absolute() else BASE_DIR / d

    @property
    def uploads_dir(self) -> Path:
        """Cartella delle immagini caricate, servita come statica su `/uploads`."""
        return self.resolved_data_dir / "uploads"


@lru_cache
def get_settings() -> Settings:
    """Restituisce le impostazioni, lette una sola volta per processo."""
    return Settings()
