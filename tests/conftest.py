import os
from pathlib import Path

from app.shared.const import CONFIG_PATH

os.environ["HOST_PATH"] = str(Path.cwd())

import pytest
from app.services.database import db_manager
from fastapi.testclient import TestClient
from app.main import app
from loguru import logger


logger.remove()
logs_path = Path("logs/test.log")
logs_path.parent.mkdir(exist_ok=True, parents=True)
# logs_path.unlink(missing_ok=True)
logger.add(logs_path)


@pytest.fixture(autouse=True)
async def init_db():
    """Initialize the database before running tests."""
    # Ensure the data directory exists
    Path(CONFIG_PATH).mkdir(exist_ok=True, parents=True)

    # Initialize the database
    await db_manager.initialize()

    yield

    # Cleanup after tests
    try:
        (CONFIG_PATH / "test_database.db").unlink(missing_ok=True)
    except Exception as e:
        print(f"Failed to cleanup database: {e}")


@pytest.fixture
def client():
    return TestClient(app)
