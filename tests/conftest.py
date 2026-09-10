from pathlib import Path
from tempfile import TemporaryDirectory

import pytest


@pytest.fixture
def tmp_path():
    # Keep test CSVs isolated from both real trades and the Windows global temp ACLs.
    with TemporaryDirectory(prefix=".test-", dir=Path(__file__).resolve().parents[1]) as folder:
        yield Path(folder)
