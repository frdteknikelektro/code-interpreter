import pytest
import logging
from app.services.docker_executor import docker_executor
from app.shared.config import get_settings
from app.utils.generate_id import generate_id

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
settings = get_settings()


@pytest.fixture(scope="function", autouse=True)
async def setup_docker():
    """Setup and teardown Docker for tests."""
    # Initialize Docker
    await docker_executor.initialize()

    # Yield control to tests
    yield

    # Cleanup
    await docker_executor.close()


@pytest.mark.asyncio
async def test_memory_limit_enforced():
    """Test that Docker container memory limits are enforced."""
    # Set a low memory limit (50MB)
    memory_limit_mb = 50
    session_id = generate_id()

    # Print test info
    print(f"\nRunning memory limit test with limit: {memory_limit_mb}MB")

    # Python code that attempts to allocate more memory than the limit
    code = """
import numpy as np
# Try to allocate more memory than the limit
# Each float64 is 8 bytes, so 13,000,000 elements is about 100MB
try:
    # Create a large array (> 50MB)
    large_array = np.ones(13_000_000, dtype=np.float64)
    print(f"Array created with shape {large_array.shape} and size {large_array.nbytes / (1024*1024):.2f} MB")
except MemoryError:
    print("MemoryError: Memory limit enforced successfully")
except Exception as e:
    print(f"Unexpected error: {type(e).__name__}: {e}")
"""

    # Call docker_executor directly instead of using the API
    result = await docker_executor.execute(
        code=code, session_id=session_id, lang="py", config={"memory_limit_mb": memory_limit_mb}
    )

    # Print the result for debugging
    print(f"Memory limit test result: {result}")

    # When memory limit is enforced, we could see either:
    # 1. A status of 'error' with empty stdout/stderr (container killed by OOM)
    # 2. A MemoryError message explicitly caught
    # 3. A 'Killed' message in stderr

    # Check if memory limit enforcement was detected
    memory_error_detected = False

    # Case 1: The container was terminated by OOM with status 'error'
    if result["status"] == "error" and result["stdout"] == "" and result["stderr"] == "":
        memory_error_detected = True
        print("Memory limit enforcement detected: Container was terminated with error status")

    # Case 2: Explicit MemoryError caught by Python
    elif "MemoryError" in result["stdout"] or "MemoryError" in result["stderr"]:
        memory_error_detected = True
        print("Memory limit enforcement detected: MemoryError in output")

    # Case 3: Process was killed due to memory limit
    elif "Killed" in result["stderr"]:
        memory_error_detected = True
        print("Memory limit enforcement detected: Process was killed")

    # Container could also be terminated abnormally
    elif result["status"] == "error":
        memory_error_detected = True
        print("Memory limit enforcement detected: Container terminated abnormally")

    # Assert that memory limit enforcement was detected in some form
    assert memory_error_detected, f"Memory limit enforcement not detected. Output: {result}"


@pytest.mark.asyncio
async def test_memory_limit_adequate():
    """Test that adequate memory limits allow execution."""
    # Set a higher memory limit that should be sufficient
    memory_limit_mb = 200
    session_id = generate_id()

    # Print test info
    print(f"\nRunning memory limit test with adequate limit: {memory_limit_mb}MB")

    # Python code that allocates memory but stays under the limit
    code = """
import numpy as np
# Create an array that should fit within memory limits
# Each float64 is 8 bytes, so ~13 million elements is about 100MB
array = np.ones(13_000_000, dtype=np.float64)
print(f"Array created with shape {array.shape} and size {array.nbytes / (1024*1024):.2f} MB")
"""

    # Call docker_executor directly instead of using the API
    result = await docker_executor.execute(
        code=code, session_id=session_id, lang="py", config={"memory_limit_mb": memory_limit_mb}
    )

    # Print the result for debugging
    print(f"Adequate memory test result: {result}")

    # The code should execute successfully
    assert result["status"] == "ok"
    assert "Array created with shape" in result["stdout"]
    assert "MB" in result["stdout"]
