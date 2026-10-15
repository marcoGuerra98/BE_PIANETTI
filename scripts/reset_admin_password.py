"""Recupero password: da eseguire sul server, sovrascrive l'hash in data/admin.json.
Invalida anche tutte le sessioni (token) aperte.

Uso:  python scripts/reset_admin_password.py
"""

import sys

from _common import admin_repo, ask_new_password

from app.errors import DomainError
from app.services.auth_service import set_admin_password


def main() -> int:
    """Restituisce il codice di uscita del processo (0 = successo)."""
    repo = admin_repo()
    admin = repo.get()
    if admin is None:
        print("Nessun amministratore configurato: usa scripts/create_admin.py")
        return 1
    print(f"Reset password per l'amministratore '{admin.username}'.")
    try:
        set_admin_password(repo, None, ask_new_password(), create=False)
    except DomainError as e:
        print(f"Errore: {e.message}")
        return 1
    print("Password aggiornata. Le sessioni aperte sono state invalidate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
