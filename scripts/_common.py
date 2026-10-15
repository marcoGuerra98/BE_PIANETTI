"""Funzioni condivise dagli script CLI.

L'import di questo modulo aggiunge la radice del progetto a sys.path, così gli
script possono importare `app` anche se lanciati come `python scripts/<nome>.py`.
"""

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.repositories.json_store import JsonDataStore  # noqa: E402
from app.services.auth_service import MIN_PASSWORD_LENGTH  # noqa: E402


def admin_repo():
    """Repository dell'amministratore sulla cartella dati configurata."""
    return JsonDataStore(get_settings().resolved_data_dir).admin


def ask_new_password() -> str:
    """Chiede la nuova password due volte (senza eco) finché è valida e confermata."""
    while True:
        pwd = getpass.getpass(f"Nuova password (min {MIN_PASSWORD_LENGTH} caratteri): ")
        if len(pwd) < MIN_PASSWORD_LENGTH:
            print("Password troppo corta, riprova.")
            continue
        if getpass.getpass("Ripeti la password: ") != pwd:
            print("Le password non coincidono, riprova.")
            continue
        return pwd
