from fastapi.testclient import TestClient
from app.main import app
import os

client = TestClient(app)


def test_create_and_read_file():
    """Test creating and reading a file."""
    # First, create a file
    create_file_code = """
import os
# Write to file
with open('/mnt/data/test.txt', 'w') as f:
    f.write('Hello from file!')
print('File created')
# List files in directory
print('Files in /mnt/data:', os.listdir('/mnt/data'))
"""
    response = client.post("/v1/librechat/exec", json={"code": create_file_code, "lang": "py"})

    assert response.status_code == 200
    result = response.json()
    assert "stdout" in result
    assert "stderr" in result
    assert "File created" in result["stdout"]
    assert "test.txt" in result["stdout"]
    session_id = result["session_id"]

    # Now read the file back using the same session_id
    read_file_code = """
with open('/mnt/data/test.txt', 'r') as f:
    content = f.read()
print(f'File content: {content}')
"""
    response = client.post(
        "/v1/librechat/exec",
        json={
            "code": read_file_code,
            "lang": "py",
            "files": [{"id": result["files"][0]["id"], "session_id": session_id, "name": "test.txt"}],
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert "stdout" in result
    assert "stderr" in result
    assert "File content" in result["stdout"]


def test_file_persistence():
    """Test that files persist between executions in the same session."""
    # Create multiple files
    create_files_code = """
for i in range(3):
    with open(f'/mnt/data/test_{i}.txt', 'w') as f:
        f.write(f'Content {i}')
print('Files created')
"""
    response = client.post("/v1/librechat/exec", json={"code": create_files_code, "lang": "py"})

    assert response.status_code == 200
    result = response.json()
    assert "stdout" in result
    assert "Files created" in result["stdout"]
    session_id = result["session_id"]

    # Read back all files
    read_files_code = """
import os
files = sorted(os.listdir('/mnt/data'))
print('Files:', files)
for file in files:
    with open(f'/mnt/data/{file}', 'r') as f:
        print(f'{file}: {f.read()}')
"""
    response = client.post(
        "/v1/librechat/exec",
        json={
            "code": read_files_code,
            "lang": "py",
            "files": [{"id": f["id"], "session_id": session_id, "name": f["name"]} for f in result["files"]],
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert "stdout" in result
    assert "test_0.txt" in result["stdout"]
    assert "test_1.txt" in result["stdout"]
    assert "test_2.txt" in result["stdout"]
    assert "Content 0" in result["stdout"]
    assert "Content 1" in result["stdout"]
    assert "Content 2" in result["stdout"]


def test_file_isolation():
    """Test that files are isolated between different sessions."""
    # Create a file in first execution
    response = client.post(
        "/v1/librechat/exec",
        json={"code": "with open('/mnt/data/secret.txt', 'w') as f: f.write('secret data')", "lang": "py"},
    )

    assert response.status_code == 200

    # Try to access file in a new session
    response = client.post(
        "/v1/librechat/exec", json={"code": "\nimport os\nprint('Files:', os.listdir('/mnt/data'))\n", "lang": "py"}
    )

    assert response.status_code == 200
    result = response.json()
    assert "stdout" in result
    assert "Files: []" in result["stdout"]  # New session should see no files


def test_file_creation_and_metadata():
    """Test that exec creates a file and stores metadata in SQLite."""
    # Create a file using exec
    create_file_code = """
with open('/mnt/data/test.txt', 'w') as f:
    f.write('Test content')
print('File created')
"""
    response = client.post("/v1/librechat/exec", json={"code": create_file_code, "lang": "py"})

    assert response.status_code == 200
    result = response.json()
    assert "stdout" in result
    assert "File created" in result["stdout"]
    assert "files" in result
    assert len(result["files"]) == 1
    session_id = result["session_id"]
    file_id = result["files"][0]["id"]

    # List files to check metadata
    response = client.get(f"/v1/librechat/files/{session_id}")
    assert response.status_code == 200
    files = response.json()
    assert len(files) == 1
    assert files[0]["name"] == f"{session_id}/{file_id}"
    assert files[0]["lastModified"] is not None


def test_file_download():
    """Test downloading a file using the session file download endpoint."""
    # Create a file with specific content
    test_content = "Hello, this is test content for download!"
    create_file_code = (
        """import os
# Create session directory
os.makedirs('/mnt/data', exist_ok=True)
# Write to file
with open('/mnt/data/download_test.txt', 'w') as f:
    f.write('"""
        + test_content
        + """')
print('File created')
# List files in directory
print('Files in /mnt/data:', os.listdir('/mnt/data'))"""
    )

    response = client.post("/v1/librechat/exec", json={"code": create_file_code, "lang": "py"})

    assert response.status_code == 200
    result = response.json()
    assert "stdout" in result
    assert "File created" in result["stdout"]
    session_id = result["session_id"]
    file_id = result["files"][0]["id"]

    # Download the file
    response = client.get(f"/v1/librechat/download/{session_id}/{file_id}")
    assert response.status_code == 200
    assert response.content.decode() == test_content

    # Test non-existent file
    response = client.get(f"/v1/librechat/download/{session_id}/nonexistent")
    assert response.status_code == 404

    # Test non-existent session
    response = client.get("/v1/librechat/download/nonexistent-session/nonexistent")
    assert response.status_code == 404
