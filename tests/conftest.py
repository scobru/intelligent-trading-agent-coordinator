import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
import db_utils


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """DB SQLite temporaneo e inizializzato per ogni test (niente dipendenza da coordinator.db)."""
    monkeypatch.setattr(config, "SQLITE_DB_PATH", str(tmp_path / "test.db"))
    db_utils.init_db()
