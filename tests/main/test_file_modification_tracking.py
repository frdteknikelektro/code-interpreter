import pytest
from fastapi.testclient import TestClient
from app.main import app
import os
import time

client = TestClient(app)

def test_only_new_files_are_returned():
    """Test that only newly created files are returned by execute endpoint."""
    # Create initial files in session
    initial_code = """
import os
# Create initial file and untouched file
with open('/mnt/data/initial.txt', 'w') as f:
    f.write('Initial content')
with open('/mnt/data/untouched.txt', 'w') as f:
    f.write('Untouched content')
print('Initial files created')
"""
    response = client.post(
        "/v1/execute",
        json={
            "code": initial_code,
            "lang": "py"
        }
    )
    
    assert response.status_code == 200
    result = response.json()
    assert result["run"]["status"] == "ok"
    assert "Initial files created" in result["run"]["stdout"]
    
    # Verify initial files are returned
    initial_files = result["files"]
    assert len(initial_files) == 2
    
    session_id = result["session_id"]
    
    # Create new files (should be returned)
    # Modify existing file (should be returned)
    # Leave untouched file alone (should NOT be returned)
    execute_code = """
import os
# Create a new file
with open('/mnt/data/new.txt', 'w') as f:
    f.write('New content')

# Modify existing file
with open('/mnt/data/initial.txt', 'w') as f:
    f.write('Modified content')

# Create nested directory and file
os.makedirs('/mnt/data/nested', exist_ok=True)
with open('/mnt/data/nested/nested.txt', 'w') as f:
    f.write('Nested content')

print('Files created and modified')
"""
    response = client.post(
        "/v1/execute",
        json={
            "code": execute_code,
            "lang": "py",
            "session_id": session_id,
            "files": [{"id": f["id"], "session_id": session_id, "name": f["name"]} for f in initial_files]
        }
    )
    
    assert response.status_code == 200
    result = response.json()
    assert result["run"]["status"] == "ok"
    assert "Files created and modified" in result["run"]["stdout"]
    
    # Verify only new and modified files are returned
    returned_files = result["files"]
    returned_names = [f["name"] for f in returned_files]
    
    # Should have 3 files: new.txt, initial.txt (modified), nested/nested.txt
    assert len(returned_files) == 3
    assert any("new.txt" in name for name in returned_names)
    assert any("initial.txt" in name for name in returned_names)
    
    # Verify nested file is included
    assert any("nested" in name and "nested.txt" in name for name in returned_names)
    
    # Verify untouched file is not returned
    assert not any("untouched.txt" in name for name in returned_names)
    
def test_modification_detection():
    """Test that file modifications are properly detected."""
    # Create initial file
    create_code = """
with open('/mnt/data/detect.txt', 'w') as f:
    f.write('Initial content')
print('File created')
"""
    response = client.post(
        "/v1/execute",
        json={
            "code": create_code,
            "lang": "py"
        }
    )
    
    assert response.status_code == 200
    initial_result = response.json()
    session_id = initial_result["session_id"]
    initial_files = initial_result["files"]
    
    # Ensure there's a delay between file operations to guarantee different timestamps
    time.sleep(1)
    
    # Test scenarios:
    # 1. Content modification
    # 2. Metadata modification (size change)
    modify_code = """
# Content modification (same size)
with open('/mnt/data/detect.txt', 'w') as f:
    f.write('Changed content')

# Create a new file for size change test
with open('/mnt/data/size_test.txt', 'w') as f:
    f.write('Small')
print('Modifications complete')
"""
    response = client.post(
        "/v1/execute",
        json={
            "code": modify_code,
            "lang": "py",
            "session_id": session_id,
            "files": [{"id": f["id"], "session_id": session_id, "name": f["name"]} for f in initial_files]
        }
    )
    
    assert response.status_code == 200
    result = response.json()
    assert "Modifications complete" in result["run"]["stdout"]
    
    returned_files = result["files"]
    returned_names = [f["name"] for f in returned_files]
    
    # Should detect both the content change and new file
    assert len(returned_files) == 2
    assert any("detect.txt" in name for name in returned_names)
    assert any("size_test.txt" in name for name in returned_names)
    
    # Now test growing a file (size change)
    grow_code = """
# Make file larger
with open('/mnt/data/size_test.txt', 'w') as f:
    f.write('This is now a much larger content than before')
print('Size change complete')
"""
    response = client.post(
        "/v1/execute",
        json={
            "code": grow_code,
            "lang": "py",
            "session_id": session_id,
            "files": [{"id": f["id"], "session_id": session_id, "name": f["name"]} for f in returned_files]
        }
    )
    
    assert response.status_code == 200
    result = response.json()
    returned_files = result["files"]
    
    # Should only detect the size change
    assert len(returned_files) == 1
    assert "size_test.txt" in returned_files[0]["name"]

def test_deleted_files_detection():
    """Test that deleted files are not included in returned files."""
    # Create initial files
    create_code = """
# Create files
with open('/mnt/data/stay.txt', 'w') as f:
    f.write('This file stays')
with open('/mnt/data/delete.txt', 'w') as f:
    f.write('This file will be deleted')
print('Files created')
"""
    response = client.post(
        "/v1/execute",
        json={
            "code": create_code,
            "lang": "py"
        }
    )
    
    assert response.status_code == 200
    initial_result = response.json()
    session_id = initial_result["session_id"]
    initial_files = initial_result["files"]
    
    # Delete one file
    delete_code = """
import os
# Delete one file
os.remove('/mnt/data/delete.txt')
# Create a new file
with open('/mnt/data/new.txt', 'w') as f:
    f.write('New file')
print('File deleted and new file created')
"""
    response = client.post(
        "/v1/execute",
        json={
            "code": delete_code,
            "lang": "py",
            "session_id": session_id,
            "files": [{"id": f["id"], "session_id": session_id, "name": f["name"]} for f in initial_files]
        }
    )
    
    assert response.status_code == 200
    result = response.json()
    
    # Only the new file should be in the returned files
    # The deleted file should not be there
    returned_files = result["files"]
    assert len(returned_files) == 1
    assert "new.txt" in returned_files[0]["name"] 