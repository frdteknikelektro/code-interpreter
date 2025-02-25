from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_simple_code_execution():
    """Test executing a simple Python code snippet."""
    response = client.post(
        "/v1/execute",
        json={
            "code": "print('Hello from Python!')\nx = 1 + 1\nprint(f'Result: {x}')",
            "lang": "py"
        }
    )
    
    assert response.status_code == 200
    result = response.json()
    assert result["run"]["status"] == "ok"
    assert "Hello from Python!" in result["run"]["stdout"]
    assert "Result: 2" in result["run"]["stdout"]
    assert result["run"]["stderr"] == ""
    assert isinstance(result["files"], list)  # Should have files list, even if empty

def test_code_execution_error():
    """Test executing code that raises an error."""
    response = client.post(
        "/v1/execute",
        json={
            "code": "x = 1/0  # This will raise a ZeroDivisionError",
            "lang": "py"
        }
    )
    
    assert response.status_code == 200
    result = response.json()
    assert result["run"]["status"] == "error"
    assert "ZeroDivisionError" in result["run"]["stderr"]
    assert result["run"]["stdout"] == ""
    assert isinstance(result["files"], list)

def test_syntax_error():
    """Test executing code with syntax errors."""
    response = client.post(
        "/v1/execute",
        json={
            "code": "print('Unclosed string  # Missing closing quote",
            "lang": "py"
        }
    )
    
    assert response.status_code == 200
    result = response.json()
    assert result["run"]["status"] == "error"
    assert "SyntaxError" in result["run"]["stderr"] 