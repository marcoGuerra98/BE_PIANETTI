from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.errors import TooManyAttemptsError
from app.services.auth_service import LoginRateLimiter, set_admin_password

from .conftest import ADMIN_PWD, ADMIN_USER, SECRET


def _login(client, username=ADMIN_USER, password=ADMIN_PWD):
    return client.post("/auth/login", json={"username": username, "password": password})


def test_password_stored_as_argon2_hash(app, admin, settings):
    raw = (settings.resolved_data_dir / "admin.json").read_text()
    assert ADMIN_PWD not in raw
    assert app.state.services.store.admin.get().password_hash.startswith("$argon2")


def test_login_success_returns_jwt(client, admin):
    r = _login(client)
    assert r.status_code == 200
    body = r.json()
    payload = jwt.decode(body["access_token"], SECRET, algorithms=["HS256"])
    assert payload["sub"] == ADMIN_USER
    assert body["expires_in"] == 180 * 60
    assert payload["exp"] - payload["iat"] == 180 * 60


def test_wrong_username_and_password_give_same_generic_error(client, admin):
    r1 = _login(client, password="sbagliata")
    r2 = _login(client, username="nessuno")
    assert r1.status_code == r2.status_code == 401
    assert r1.json() == r2.json() == {"detail": "Credenziali non valide"}


def test_login_rate_limited_after_five_failures(client, admin):
    for _ in range(5):
        assert _login(client, password="x").status_code == 401
    r = _login(client)  # anche con la password giusta
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0


def test_rate_limiter_unlocks_after_timeout():
    now = [0.0]
    limiter = LoginRateLimiter(max_attempts=5, lockout_seconds=900, clock=lambda: now[0])
    for _ in range(5):
        limiter.check("ip")
        limiter.register_failure("ip")
    with pytest.raises(TooManyAttemptsError):
        limiter.check("ip")
    now[0] = 901
    limiter.check("ip")


def test_successful_login_resets_failures(client, admin):
    for _ in range(4):
        _login(client, password="x")
    assert _login(client).status_code == 200
    for _ in range(4):
        assert _login(client, password="x").status_code == 401
    assert _login(client).status_code == 200


WRITE_ENDPOINTS = [
    ("post", "/players", {"nome": "A", "cognome": "B", "ruolo": "ATT", "overall": 50}),
    ("put", "/players/00000000-0000-0000-0000-000000000000", {}),
    ("delete", "/players/00000000-0000-0000-0000-000000000000", None),
    ("post", "/teams", {"nome": "X"}),
    ("put", "/teams/00000000-0000-0000-0000-000000000000", {"nome": "X"}),
    ("delete", "/teams/00000000-0000-0000-0000-000000000000", None),
    ("post", "/schedule/generate", None),
    ("delete", "/schedule", None),
    ("patch", "/matches/00000000-0000-0000-0000-000000000000", {}),
    ("put", "/matches/00000000-0000-0000-0000-000000000000/result", {"gol_casa": 0, "gol_trasferta": 0}),
    ("delete", "/matches/00000000-0000-0000-0000-000000000000/result", None),
    ("post", "/auth/change-password", {"current_password": "a", "new_password": "abcdefgh"}),
    ("put", "/teams/00000000-0000-0000-0000-000000000000/players/00000000-0000-0000-0000-000000000000", None),
    ("post", "/tournament/reset", {"password": "x"}),
]


@pytest.mark.parametrize("method,url,body", WRITE_ENDPOINTS)
def test_write_endpoints_require_token(client, admin, method, url, body):
    kwargs = {"json": body} if body is not None else {}
    r = getattr(client, method)(url, **kwargs)
    assert r.status_code == 401, (url, r.text)
    assert r.headers.get("WWW-Authenticate") == "Bearer"

    r = getattr(client, method)(url, headers={"Authorization": "Bearer non-un-token"}, **kwargs)
    assert r.status_code == 401


def test_upload_endpoints_require_token(client, admin):
    files = {"file": ("x.png", b"\x89PNG\r\n\x1a\n" + b"0" * 10, "image/png")}
    assert client.post("/players/00000000-0000-0000-0000-000000000000/photo", files=files).status_code == 401
    assert client.post("/teams/00000000-0000-0000-0000-000000000000/logo", files=files).status_code == 401


def test_read_endpoints_are_public(client):
    for url in ("/players", "/teams", "/schedule", "/standings", "/standings/scorers"):
        assert client.get(url).status_code == 200


def test_expired_token_rejected(client, admin):
    now = datetime.now(UTC)
    token = jwt.encode(
        {"sub": ADMIN_USER, "ver": 0, "iat": now - timedelta(hours=4), "exp": now - timedelta(hours=1)},
        SECRET, algorithm="HS256",
    )
    r = client.post("/teams", json={"nome": "X"}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert "scaduta" in r.json()["detail"]


def test_token_signed_with_other_key_rejected(client, admin):
    now = datetime.now(UTC)
    token = jwt.encode(
        {"sub": ADMIN_USER, "ver": 0, "exp": now + timedelta(hours=1)}, "x" * 40, algorithm="HS256"
    )
    r = client.post("/teams", json={"nome": "X"}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_valid_token_grants_access(client, auth_headers):
    assert client.post("/teams", json={"nome": "X"}, headers=auth_headers).status_code == 201
    assert client.get("/auth/me", headers=auth_headers).json() == {"username": ADMIN_USER}


def test_change_password(client, auth_headers):
    r = client.post(
        "/auth/change-password",
        json={"current_password": "sbagliata", "new_password": "nuova-password-1"},
        headers=auth_headers,
    )
    assert r.status_code == 422

    r = client.post(
        "/auth/change-password",
        json={"current_password": ADMIN_PWD, "new_password": "nuova-password-1"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    new_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    # il vecchio token non vale più, il nuovo sì
    assert client.get("/auth/me", headers=auth_headers).status_code == 401
    assert client.get("/auth/me", headers=new_headers).status_code == 200
    assert _login(client).status_code == 401
    assert _login(client, password="nuova-password-1").status_code == 200


def test_cli_reset_password_invalidates_sessions(app, client, auth_headers):
    set_admin_password(app.state.services.store.admin, None, "reset-password-9", create=False)
    assert client.get("/auth/me", headers=auth_headers).status_code == 401
    assert _login(client, password="reset-password-9").status_code == 200


def test_create_admin_refuses_if_exists(app, admin):
    from app.errors import ValidationError

    with pytest.raises(ValidationError):
        set_admin_password(app.state.services.store.admin, "altro", "password-lunga", create=True)


def test_app_refuses_to_start_without_secret(tmp_path):
    from app.config import Settings
    from app.main import create_app

    with pytest.raises(RuntimeError):
        create_app(Settings(secret_key="", data_dir=tmp_path, _env_file=None))
