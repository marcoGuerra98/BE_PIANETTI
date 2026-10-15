"""Crea l'amministratore (solo se data/admin.json non esiste).

Uso:  python scripts/create_admin.py
"""

import sys

from _common import admin_repo, ask_new_password

from app.errors import DomainError
from app.services.auth_service import set_admin_password


def main() -> int:
    """Restituisce il codice di uscita del processo (0 = successo)."""
    repo = admin_repo()
    if repo.get() is not None:
        print("L'amministratore esiste già. Per cambiare password usa scripts/reset_admin_password.py")
        return 1
    username = input("Username amministratore: ").strip()
    if not username:
        print("Username obbligatorio.")
        return 1
    try:
        set_admin_password(repo, username, ask_new_password(), create=True)
    except DomainError as e:
        print(f"Errore: {e.message}")
        return 1
    print(f"Amministratore '{username}' creato.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
