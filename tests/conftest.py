import os
from pathlib import Path
os.environ["HOST_PATH"] = str(Path.cwd())

import pytest
from app.services.database import db_manager
from fastapi.testclient import TestClient
from app.main import app
from loguru import logger


logger.remove()
logger.add("logs/test.log")



@pytest.fixture(autouse=True)
async def init_db():
    """Initialize the database before running tests."""
    # Ensure the data directory exists
    Path("data").mkdir(exist_ok=True)

    # Initialize the database
    await db_manager.initialize()

    yield

    # Cleanup after tests
    try:
        Path("data/files.db").unlink(missing_ok=True)
    except Exception as e:
        print(f"Failed to cleanup database: {e}")


@pytest.fixture
def client():
    return TestClient(app)
