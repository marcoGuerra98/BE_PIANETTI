"""Autenticazione dell'amministratore: hashing argon2, JWT e rate limit del login."""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.errors import AuthError, ForbiddenError, NotFoundError, TooManyAttemptsError, ValidationError
from app.models.auth import AdminCredentials, TokenOut
from app.repositories.base import AdminRepository

_hasher = PasswordHasher()
GENERIC_LOGIN_ERROR = "Credenziali non valide"
MIN_PASSWORD_LENGTH = 8


def hash_password(password: str) -> str:
    """Hash argon2id con salt casuale e parametri predefiniti di argon2-cffi."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """True se la password corrisponde all'hash; un hash malformato vale come errata."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def validate_new_password(password: str) -> None:
    """Regole minime per una nuova password (oggi solo la lunghezza)."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(f"La password deve avere almeno {MIN_PASSWORD_LENGTH} caratteri")


# Hash di riferimento usato quando lo username è sbagliato, così il tempo di
# risposta non rivela se lo username esiste.
_DUMMY_HASH = hash_password("dummy-password-for-constant-time")


@dataclass
class _Attempts:
    """Stato dei tentativi falliti per una chiave (tempi in secondi del clock del limiter)."""

    failures: int = 0
    first_failure: float = 0.0
    locked_until: float = 0.0


class LoginRateLimiter:
    """Blocco temporaneo dopo N tentativi falliti (in memoria, per chiave = IP client).

    I fallimenti si contano in una finestra di `lockout_seconds` dal primo
    errore; al raggiungimento di `max_attempts` la chiave resta bloccata per
    `lockout_seconds`. Lo stato è per processo: con più worker ognuno ha il suo.
    `clock` è iniettabile per i test.
    """

    def __init__(self, max_attempts: int, lockout_seconds: int, clock: Callable[[], float] = time.monotonic):
        self.max_attempts = max_attempts
        self.lockout_seconds = lockout_seconds
        self.clock = clock
        self._data: dict[str, _Attempts] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        """Solleva TooManyAttemptsError se la chiave è bloccata."""
        with self._lock:
            entry = self._data.get(key)
            now = self.clock()
            if entry and entry.locked_until > now:
                # +1 per arrotondare per eccesso i secondi residui.
                retry = int(entry.locked_until - now) + 1
                raise TooManyAttemptsError(
                    f"Troppi tentativi falliti. Riprova tra {max(1, retry // 60)} minuti.", retry_after=retry
                )

    def register_failure(self, key: str) -> None:
        """Conta un tentativo fallito ed eventualmente attiva il blocco."""
        with self._lock:
            now = self.clock()
            entry = self._data.setdefault(key, _Attempts())
            # Finestra scaduta: i fallimenti vecchi non contano più.
            if entry.failures and now - entry.first_failure > self.lockout_seconds:
                entry.failures = 0
            if entry.failures == 0:
                entry.first_failure = now
            entry.failures += 1
            if entry.failures >= self.max_attempts:
                entry.locked_until = now + self.lockout_seconds
                # Allo sblocco si riparte con un nuovo ciclo di tentativi.
                entry.failures = 0

    def reset(self, key: str) -> None:
        """Azzera lo stato della chiave (dopo un login riuscito)."""
        with self._lock:
            self._data.pop(key, None)


class AuthService:
    """Login, verifica dei token e cambio password dell'unico amministratore."""

    def __init__(
        self,
        admin_repo: AdminRepository,
        secret_key: str,
        expire_minutes: int,
        algorithm: str,
        limiter: LoginRateLimiter,
    ):
        self.admin_repo = admin_repo
        self.secret_key = secret_key
        self.expire_minutes = expire_minutes
        self.algorithm = algorithm
        self.limiter = limiter

    def _issue_token(self, admin: AdminCredentials) -> TokenOut:
        """Firma un JWT con `sub` = username e `ver` = token_version corrente."""
        now = datetime.now(UTC)
        payload = {
            "sub": admin.username,
            "ver": admin.token_version,
            "iat": now,
            "exp": now + timedelta(minutes=self.expire_minutes),
        }
        token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
        return TokenOut(access_token=token, expires_in=self.expire_minutes * 60, username=admin.username)

    def login(self, username: str, password: str, client_key: str) -> TokenOut:
        """Verifica le credenziali applicando il rate limit su `client_key`.

        Username o password errati producono lo stesso errore generico.
        """
        self.limiter.check(client_key)
        admin = self.admin_repo.get()
        if admin is not None and admin.username == username:
            ok = verify_password(admin.password_hash, password)
        else:
            # Verifica a vuoto: stesso costo di una verifica reale.
            verify_password(_DUMMY_HASH, password)
            ok = False
        if not ok:
            self.limiter.register_failure(client_key)
            raise AuthError(GENERIC_LOGIN_ERROR)
        self.limiter.reset(client_key)
        # Se i parametri argon2 predefiniti sono cambiati, si aggiorna l'hash
        # approfittando della password in chiaro appena verificata.
        if _hasher.check_needs_rehash(admin.password_hash):
            admin = admin.model_copy(update={"password_hash": hash_password(password)})
            self.admin_repo.save(admin)
        return self._issue_token(admin)

    def verify_token(self, token: str) -> str:
        """Restituisce lo username se il token è valido, altrimenti AuthError."""
        try:
            payload = jwt.decode(
                token, self.secret_key, algorithms=[self.algorithm], options={"require": ["exp", "sub"]}
            )
        except jwt.ExpiredSignatureError:
            raise AuthError("Sessione scaduta, effettua di nuovo il login")
        except jwt.InvalidTokenError:
            raise AuthError("Token non valido")
        # Un token firmato correttamente non basta: dopo un cambio password
        # token_version è aumentata e i token emessi prima vengono rifiutati.
        admin = self.admin_repo.get()
        if admin is None or payload.get("sub") != admin.username or payload.get("ver") != admin.token_version:
            raise AuthError("Token non valido")
        return admin.username

    def verify_admin_password(self, username: str, password: str, client_key: str) -> None:
        """Conferma di un'operazione critica ripetendo la password dell'admin già autenticato.

        Password errata → ForbiddenError (403, non 401: il frontend su 401 fa
        logout). Applica il rate limit su `client_key`, da prefissare per non
        condividere il contatore con il login.
        """
        self.limiter.check(client_key)
        admin = self.admin_repo.get()
        if admin is None or admin.username != username:
            raise AuthError("Token non valido")
        if not verify_password(admin.password_hash, password):
            self.limiter.register_failure(client_key)
            raise ForbiddenError("Password non corretta")
        self.limiter.reset(client_key)

    def change_password(self, username: str, current_password: str, new_password: str) -> TokenOut:
        """Cambia la password, invalida i token esistenti e ne restituisce uno nuovo."""
        admin = self.admin_repo.get()
        if admin is None or admin.username != username:
            raise AuthError("Token non valido")
        if not verify_password(admin.password_hash, current_password):
            raise ValidationError("La password attuale non è corretta")
        validate_new_password(new_password)
        if current_password == new_password:
            raise ValidationError("La nuova password deve essere diversa da quella attuale")
        admin = admin.model_copy(
            update={"password_hash": hash_password(new_password), "token_version": admin.token_version + 1}
        )
        self.admin_repo.save(admin)
        # I token precedenti sono invalidati: se ne restituisce uno nuovo.
        return self._issue_token(admin)


def set_admin_password(repo: AdminRepository, username: str | None, password: str, create: bool) -> None:
    """Usata dagli script CLI di creazione e reset.

    `create=True` crea l'amministratore (errore se esiste già); `create=False`
    sostituisce la password e incrementa token_version (`username` ignorato).
    """
    validate_new_password(password)
    current = repo.get()
    if create:
        if current is not None:
            raise ValidationError("L'amministratore esiste già: usa reset_admin_password.py")
        if not username or not username.strip():
            raise ValidationError("Username obbligatorio")
        repo.save(AdminCredentials(username=username.strip(), password_hash=hash_password(password)))
    else:
        if current is None:
            raise NotFoundError("Nessun amministratore configurato: usa create_admin.py")
        repo.save(
            current.model_copy(
                update={"password_hash": hash_password(password), "token_version": current.token_version + 1}
            )
        )
