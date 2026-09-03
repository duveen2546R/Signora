import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def hello_take():
    from app.ingest.rokoko import parse_csv
    return parse_csv(FIXTURES / "hello.csv")
