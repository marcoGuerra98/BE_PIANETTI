import random

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import build_services, create_app
from app.models.match import Fase, MarcatoreIn, ResultIn
from app.models.player import PlayerCreate, Ruolo
from app.models.team import TeamCreate
from app.services.auth_service import set_admin_password

SECRET = "test-secret-key-che-e-abbastanza-lunga-per-hs256"
ADMIN_USER, ADMIN_PWD = "admin", "password-sicura-123"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(secret_key=SECRET, data_dir=tmp_path / "data", _env_file=None)


@pytest.fixture
def services(settings):
    svc = build_services(settings)
    svc.schedule.rng = random.Random(42)
    return svc


@pytest.fixture
def make_teams(services):
    def _make(n: int):
        return [services.teams.create(TeamCreate(nome=f"Squadra {chr(65 + i)}")) for i in range(n)]

    return _make


@pytest.fixture
def make_player(services):
    def _make(team=None, nome="Mario", cognome="Rossi", ruolo=Ruolo.ATT, overall=70):
        return services.players.create(
            PlayerCreate(
                nome=nome, cognome=cognome, ruolo=ruolo, overall=overall,
                squadra_id=team.id if team else None,
            )
        )

    return _make


@pytest.fixture
def play(services):
    """Inserisce un risultato attribuendo i goal a un "bomber" per squadra, creato al bisogno
    (comodo per testare classifica e fase finale)."""
    bombers = {}

    def _bomber(team_id):
        if team_id not in bombers:
            bombers[team_id] = services.players.create(
                PlayerCreate(nome="Bomber", cognome=str(team_id)[:8], ruolo=Ruolo.ATT, overall=80, squadra_id=team_id)
            )
        return bombers[team_id]

    def _play(match, gc: int, gt: int, rigori=None):
        marcatori = [
            MarcatoreIn(giocatore_id=_bomber(team_id).id, goal=g)
            for team_id, g in ((match.squadra_casa_id, gc), (match.squadra_trasferta_id, gt))
            if g
        ]
        return services.matches.set_result(
            match.id,
            ResultIn(gol_casa=gc, gol_trasferta=gt, marcatori=marcatori, vincitore_rigori_id=rigori),
        )

    return _play


@pytest.fixture
def find_match(services):
    def _find(home_id, away_id=None, fase: Fase | None = None):
        for m in services.store.matches.list():
            if fase and m.fase != fase:
                continue
            teams = {m.squadra_casa_id, m.squadra_trasferta_id}
            if home_id in teams and (away_id is None or away_id in teams):
                return m
        raise AssertionError("partita non trovata")

    return _find


# --- API ---


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def admin(app):
    set_admin_password(app.state.services.store.admin, ADMIN_USER, ADMIN_PWD, create=True)
    return ADMIN_USER, ADMIN_PWD


@pytest.fixture
def auth_headers(client, admin):
    r = client.post("/auth/login", json={"username": admin[0], "password": admin[1]})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
