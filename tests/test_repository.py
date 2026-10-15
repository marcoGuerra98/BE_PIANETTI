import json

import pytest

from app.models.team import Team
from app.repositories.json_store import JsonDataStore


def test_crud_and_persistence(tmp_path):
    store = JsonDataStore(tmp_path)
    t = store.teams.add(Team(nome="Alfa"))
    assert store.teams.get(t.id).nome == "Alfa"
    assert store.teams.get_by_name("  aLFa ").id == t.id

    # una nuova istanza rilegge dal file
    other = JsonDataStore(tmp_path)
    assert [x.nome for x in other.teams.list()] == ["Alfa"]

    store.teams.update(t.model_copy(update={"nome": "Beta"}))
    assert json.loads((tmp_path / "teams.json").read_text())[0]["nome"] == "Beta"

    assert store.teams.delete(t.id) is True
    assert store.teams.delete(t.id) is False
    assert store.teams.list() == []


def test_update_of_missing_item_fails(tmp_path):
    store = JsonDataStore(tmp_path)
    with pytest.raises(KeyError):
        store.teams.update(Team(nome="Fantasma"))


def test_atomic_write_leaves_no_temp_files(tmp_path):
    store = JsonDataStore(tmp_path)
    for i in range(5):
        store.teams.add(Team(nome=f"T{i}"))
    leftovers = [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_empty_file_is_treated_as_empty_list(tmp_path):
    (tmp_path / "players.json").write_text("")
    assert JsonDataStore(tmp_path).players.list() == []
