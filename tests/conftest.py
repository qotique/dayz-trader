import pytest

from models._utils import reset_counters


@pytest.fixture(autouse=True)
def _reset_counters() -> None:
    reset_counters()
