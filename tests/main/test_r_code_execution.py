import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_r_code_execution():
    """Test executing a simple R code snippet."""
    response = client.post("/v1/execute", json={"code": "x <- 1 + 1; cat('Result:', x)", "lang": "r"})

    assert response.status_code == 200
    result = response.json()
    assert result["run"]["status"] == "ok"
    assert "Result: 2" in result["run"]["stdout"]
    assert result["run"]["stderr"] == ""
    assert isinstance(result["files"], list)
    assert result["language"] == "r"
    assert "R (Jupyter R-notebook)" in result["version"]


def test_r_code_execution_error():
    """Test executing R code that raises an error."""
    response = client.post(
        "/v1/execute", json={"code": "x <- 1/0  # This will produce Inf, not an error in R", "lang": "r"}
    )

    assert response.status_code == 200
    result = response.json()
    # R handles division by zero differently than Python
    assert result["run"]["status"] == "ok"
    assert result["run"]["stdout"] == "Empty. Make sure to use print() or cat() to display results in R"
    assert isinstance(result["files"], list)
