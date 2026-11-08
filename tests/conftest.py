from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def fixture_zip():
    return ROOT / "fixtures" / "synthetic_apple_health_export.zip"


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "health.sqlite3"
