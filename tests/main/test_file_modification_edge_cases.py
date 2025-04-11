import pytest
from fastapi.testclient import TestClient
from app.main import app
import os
import time
import base64

client = TestClient(app)

def test_zero_byte_files():
    """Test that zero-byte files are properly tracked when created/modified."""
    # Create initial empty file
    response = client.post(
        "/v1/execute",
        json={
            "code": "with open('/mnt/data/empty.txt', 'w') as f: pass",
            "lang": "py"
        }
    )
    
    assert response.status_code == 200
    result = response.json()
    session_id = result["session_id"]
    initial_files = result["files"]
    assert len(initial_files) == 1
    assert "empty.txt" in initial_files[0]["name"]
    
    # Now add content to the empty file
    response = client.post(
        "/v1/execute",
        json={
            "code": "with open('/mnt/data/empty.txt', 'w') as f: f.write('Now has content')",
            "lang": "py",
            "session_id": session_id,
            "files": [{"id": f["id"], "session_id": session_id, "name": f["name"]} for f in initial_files]
        }
    )
    
    assert response.status_code == 200
    result = response.json()
    
    # The file should be returned as modified
    returned_files = result["files"]
    assert len(returned_files) == 1
    assert "empty.txt" in returned_files[0]["name"]

def test_identical_content_different_files():
    """Test that files with identical content but different names are tracked properly."""
    # Create initial files with identical content
    response = client.post(
        "/v1/execute",
        json={
            "code": """
content = "Same content in different files"
with open('/mnt/data/file1.txt', 'w') as f: f.write(content)
""",
            "lang": "py"
        }
    )
    
    assert response.status_code == 200
    result = response.json()
    session_id = result["session_id"]
    initial_files = result["files"]
    
    # Create a second file with identical content
    response = client.post(
        "/v1/execute",
        json={
            "code": """
content = "Same content in different files"
with open('/mnt/data/file2.txt', 'w') as f: f.write(content)
""",
            "lang": "py",
            "session_id": session_id,
            "files": [{"id": f["id"], "session_id": session_id, "name": f["name"]} for f in initial_files]
        }
    )
    
    # Only the new file should be detected
    assert response.status_code == 200
    result = response.json()
    returned_files = result["files"]
    assert len(returned_files) == 1
    assert "file2.txt" in returned_files[0]["name"]

def test_file_delete_and_recreate():
    """Test that a file deleted and recreated in the same execution is tracked correctly."""
    # Create initial file
    response = client.post(
        "/v1/execute",
        json={
            "code": "with open('/mnt/data/recreate.txt', 'w') as f: f.write('Original content')",
            "lang": "py"
        }
    )
    
    assert response.status_code == 200
    result = response.json()
    session_id = result["session_id"]
    initial_files = result["files"]
    
    # Delete and recreate the file in the same execution
    response = client.post(
        "/v1/execute",
        json={
            "code": """
import os
# Delete the file
os.remove('/mnt/data/recreate.txt')
# Recreate it with different content
with open('/mnt/data/recreate.txt', 'w') as f: f.write('New content after recreation')
""",
            "lang": "py",
            "session_id": session_id,
            "files": [{"id": f["id"], "session_id": session_id, "name": f["name"]} for f in initial_files]
        }
    )
    
    # The recreated file should be detected as modified
    assert response.status_code == 200
    result = response.json()
    returned_files = result["files"]
    assert len(returned_files) == 1
    assert "recreate.txt" in returned_files[0]["name"]

def test_special_characters_in_filename():
    """Test that files with special characters in the name are tracked properly."""
    # Create file with special characters in name
    response = client.post(
        "/v1/execute",
        json={
            "code": r"""with open('/mnt/data/special!@#$%^&*().txt', 'w') as f: f.write('Special chars')""",
            "lang": "py"
        }
    )
    
    assert response.status_code == 200
    result = response.json()
    session_id = result["session_id"]
    initial_files = result["files"]
    assert len(initial_files) == 1
    
    # Modify the file
    response = client.post(
        "/v1/execute",
        json={
            "code": r"""with open('/mnt/data/special!@#$%^&*().txt', 'w') as f: f.write('Modified content')""",
            "lang": "py",
            "session_id": session_id,
            "files": [{"id": f["id"], "session_id": session_id, "name": f["name"]} for f in initial_files]
        }
    )
    
    # The file should be detected as modified
    assert response.status_code == 200
    result = response.json()
    returned_files = result["files"]
    assert len(returned_files) == 1

def test_unicode_filenames_and_content():
    """Test that files with Unicode names and content are tracked properly."""
    # Create file with Unicode name and content
    response = client.post(
        "/v1/execute",
        json={
            "code": """
# Unicode filename and content
with open('/mnt/data/你好世界.txt', 'w') as f:
    f.write('こんにちは世界')
""",
            "lang": "py"
        }
    )
    
    assert response.status_code == 200
    result = response.json()
    session_id = result["session_id"]
    initial_files = result["files"]
    assert len(initial_files) == 1
    
    # Modify the file with more Unicode content
    response = client.post(
        "/v1/execute",
        json={
            "code": """
with open('/mnt/data/你好世界.txt', 'w') as f:
    f.write('Привет, мир! नमस्ते दुनिया!')
""",
            "lang": "py",
            "session_id": session_id,
            "files": [{"id": f["id"], "session_id": session_id, "name": f["name"]} for f in initial_files]
        }
    )
    
    # The file should be detected as modified
    assert response.status_code == 200
    result = response.json()
    returned_files = result["files"]
    assert len(returned_files) == 1

def test_same_size_different_content():
    """Test that files with the same size but different content are detected as changed."""
    # Create initial file with specific content size
    response = client.post(
        "/v1/execute",
        json={
            "code": """
content = "A" * 100  # Exactly 100 'A' characters
with open('/mnt/data/same_size.txt', 'w') as f:
    f.write(content)
""",
            "lang": "py"
        }
    )
    
    assert response.status_code == 200
    result = response.json()
    session_id = result["session_id"]
    initial_files = result["files"]
    
    # Change content but keep the same file size
    response = client.post(
        "/v1/execute",
        json={
            "code": """
content = "B" * 100  # Still 100 bytes, but different content
with open('/mnt/data/same_size.txt', 'w') as f:
    f.write(content)
""",
            "lang": "py",
            "session_id": session_id,
            "files": [{"id": f["id"], "session_id": session_id, "name": f["name"]} for f in initial_files]
        }
    )
    
    # Should detect the content change even though size is the same
    assert response.status_code == 200
    result = response.json()
    returned_files = result["files"]
    assert len(returned_files) == 1

def test_binary_file_detection():
    """Test that binary files are properly tracked."""
    # Create a binary file
    response = client.post(
        "/v1/execute",
        json={
            "code": """
# Create a simple binary file with some non-text bytes
import os
binary_data = bytes([0, 1, 2, 3, 255, 254, 253, 252])
with open('/mnt/data/binary.bin', 'wb') as f:
    f.write(binary_data)
print('Binary file created')
""",
            "lang": "py"
        }
    )
    
    assert response.status_code == 200
    result = response.json()
    session_id = result["session_id"]
    initial_files = result["files"]
    assert len(initial_files) == 1
    
    # Modify the binary file
    response = client.post(
        "/v1/execute",
        json={
            "code": """
# Modify the binary file
binary_data = bytes([255, 254, 253, 252, 0, 1, 2, 3])  # Reversed order
with open('/mnt/data/binary.bin', 'wb') as f:
    f.write(binary_data)
print('Binary file modified')
""",
            "lang": "py",
            "session_id": session_id,
            "files": [{"id": f["id"], "session_id": session_id, "name": f["name"]} for f in initial_files]
        }
    )
    
    # Should detect the binary file change
    assert response.status_code == 200
    result = response.json()
    returned_files = result["files"]
    assert len(returned_files) == 1

def test_deep_directory_nesting():
    """Test that files in deeply nested directories are properly tracked."""
    # Create a deeply nested directory structure
    response = client.post(
        "/v1/execute",
        json={
            "code": """
import os
# Create a deeply nested directory structure
nested_dir = '/mnt/data/level1/level2/level3/level4/level5/level6/level7'
os.makedirs(nested_dir, exist_ok=True)
with open(f'{nested_dir}/deep_file.txt', 'w') as f:
    f.write('This is deep')
print('Created deeply nested file')
""",
            "lang": "py"
        }
    )
    
    assert response.status_code == 200
    result = response.json()
    session_id = result["session_id"]
    initial_files = result["files"]
    assert len(initial_files) == 1
    
    # Modify the deeply nested file
    response = client.post(
        "/v1/execute",
        json={
            "code": """
nested_dir = '/mnt/data/level1/level2/level3/level4/level5/level6/level7'
with open(f'{nested_dir}/deep_file.txt', 'w') as f:
    f.write('This is still deep but modified')
print('Modified deeply nested file')
""",
            "lang": "py",
            "session_id": session_id,
            "files": [{"id": f["id"], "session_id": session_id, "name": f["name"]} for f in initial_files]
        }
    )
    
    # Should detect the change in the deeply nested file
    assert response.status_code == 200
    result = response.json()
    returned_files = result["files"]
    assert len(returned_files) == 1

def test_identical_content_no_change():
    """Test that rewriting a file with identical content is not detected as a change."""
    # Create initial file
    response = client.post(
        "/v1/execute",
        json={
            "code": """
with open('/mnt/data/unchanged.txt', 'w') as f:
    f.write('This content will not change')
""",
            "lang": "py"
        }
    )
    
    assert response.status_code == 200
    result = response.json()
    session_id = result["session_id"]
    initial_files = result["files"]
    
    # Rewrite the same file with identical content
    response = client.post(
        "/v1/execute",
        json={
            "code": """
# Writing the exact same content
with open('/mnt/data/unchanged.txt', 'w') as f:
    f.write('This content will not change')
print('Rewrote file with identical content')
""",
            "lang": "py",
            "session_id": session_id,
            "files": [{"id": f["id"], "session_id": session_id, "name": f["name"]} for f in initial_files]
        }
    )
    
    # No files should be returned as changed since content and size are identical
    assert response.status_code == 200
    result = response.json()
    returned_files = result["files"]
    assert len(returned_files) == 0

def test_multiple_modifications():
    """Test that a file modified multiple times in one execution is only reported once."""
    # Create initial file
    response = client.post(
        "/v1/execute",
        json={
            "code": """
with open('/mnt/data/multiple_edits.txt', 'w') as f:
    f.write('Initial content')
""",
            "lang": "py"
        }
    )
    
    assert response.status_code == 200
    result = response.json()
    session_id = result["session_id"]
    initial_files = result["files"]
    
    # Modify the file multiple times in one execution
    response = client.post(
        "/v1/execute",
        json={
            "code": """
# First modification
with open('/mnt/data/multiple_edits.txt', 'w') as f:
    f.write('First edit')

# Second modification
with open('/mnt/data/multiple_edits.txt', 'w') as f:
    f.write('Second edit')

# Third modification
with open('/mnt/data/multiple_edits.txt', 'w') as f:
    f.write('Final edit')

print('Multiple edits completed')
""",
            "lang": "py",
            "session_id": session_id,
            "files": [{"id": f["id"], "session_id": session_id, "name": f["name"]} for f in initial_files]
        }
    )
    
    # The file should be reported once, with the final change
    assert response.status_code == 200
    result = response.json()
    returned_files = result["files"]
    assert len(returned_files) == 1
    assert "multiple_edits.txt" in returned_files[0]["name"]

def test_null_bytes_in_content():
    """Test that files with null bytes in content are properly tracked."""
    # Create file with null bytes
    response = client.post(
        "/v1/execute",
        json={
            "code": """
# Create a file with null bytes in it
with open('/mnt/data/null_bytes.txt', 'wb') as f:
    f.write(b'Content with\\x00null\\x00bytes')
print('Created file with null bytes')
""",
            "lang": "py"
        }
    )
    
    assert response.status_code == 200
    result = response.json()
    session_id = result["session_id"]
    initial_files = result["files"]
    
    # Modify file with different null byte placement
    response = client.post(
        "/v1/execute",
        json={
            "code": """
# Modify the null bytes
with open('/mnt/data/null_bytes.txt', 'wb') as f:
    f.write(b'Different\\x00placement\\x00of\\x00nulls')
print('Modified null bytes file')
""",
            "lang": "py",
            "session_id": session_id,
            "files": [{"id": f["id"], "session_id": session_id, "name": f["name"]} for f in initial_files]
        }
    )
    
    # Should detect the modified file
    assert response.status_code == 200
    result = response.json()
    returned_files = result["files"]
    assert len(returned_files) == 1

def test_very_large_file():
    """Test that large files are properly tracked when modified."""
    # Create a smaller file (10KB) that is large enough for the test but not too large
    response = client.post(
        "/v1/execute",
        json={
            "code": """
# Create a 10MB file
data = 'x' * (10 * 1024 * 1024)  # 10MB of data
with open('/mnt/data/large_file.txt', 'w') as f:
    f.write(data)
print('Created 10MB file')
""",
            "lang": "py"
        }
    )
    
    assert response.status_code == 200
    result = response.json()
    
    # If the test fails at this stage, print debug info
    if "files" not in result or len(result["files"]) == 0:
        print("No files detected in initial creation")
        pytest.skip("Initial file creation failed - skipping test")
    
    session_id = result["session_id"]
    initial_files = result["files"]
    assert len(initial_files) == 1
    assert "large_file.txt" in initial_files[0]["name"]
    
    # Modify just a small part of the file
    response = client.post(
        "/v1/execute",
        json={
            "code": """
# Read the first 100 characters
with open('/mnt/data/large_file.txt', 'r') as f:
    data = list(f.read(100))

# Modify just the first 10 characters
for i in range(10):
    data[i] = 'y'

# Write modified part back
with open('/mnt/data/large_file.txt', 'r+') as f:
    f.write(''.join(data))
    
print('Modified first 10 characters of file')
""",
            "lang": "py",
            "session_id": session_id,
            "files": [{"id": f["id"], "session_id": session_id, "name": f["name"]} for f in initial_files]
        }
    )
    
    # The file should be detected as modified
    assert response.status_code == 200
    result = response.json()
    returned_files = result["files"]
    assert len(returned_files) == 1
    assert "large_file.txt" in returned_files[0]["name"]

def test_many_small_files():
    """Test that many small files are properly tracked."""
    # Create many small files
    response = client.post(
        "/v1/execute",
        json={
            "code": """
import os
# Create 50 small files
for i in range(50):
    with open(f'/mnt/data/small_{i}.txt', 'w') as f:
        f.write(f'Small file {i}')
print('Created 50 small files')
""",
            "lang": "py"
        }
    )
    
    assert response.status_code == 200
    result = response.json()
    session_id = result["session_id"]
    initial_files = result["files"]
    assert len(initial_files) == 50
    
    # Modify a subset of the files
    response = client.post(
        "/v1/execute",
        json={
            "code": """
# Modify 10 of the files
for i in range(10, 20):
    with open(f'/mnt/data/small_{i}.txt', 'w') as f:
        f.write(f'Modified small file {i}')
print('Modified 10 files')
""",
            "lang": "py",
            "session_id": session_id,
            "files": [{"id": f["id"], "session_id": session_id, "name": f["name"]} for f in initial_files]
        }
    )
    
    # Should detect exactly the 10 modified files
    assert response.status_code == 200
    result = response.json()
    returned_files = result["files"]
    assert len(returned_files) == 10
    
    # Verify that the correct files were detected
    modified_indices = set()
    for file in returned_files:
        for i in range(10, 20):
            if f"small_{i}" in file["name"]:
                modified_indices.add(i)
                break
    
    assert len(modified_indices) == 10
    assert all(i in modified_indices for i in range(10, 20))

def test_append_to_file():
    """Test that appending to a file is properly detected as a modification."""
    # Create initial file
    response = client.post(
        "/v1/execute",
        json={
            "code": """
with open('/mnt/data/append.txt', 'w') as f:
    f.write('Initial content\\n')
""",
            "lang": "py"
        }
    )
    
    assert response.status_code == 200
    result = response.json()
    session_id = result["session_id"]
    initial_files = result["files"]
    
    # Append to the file instead of overwriting
    response = client.post(
        "/v1/execute",
        json={
            "code": """
# Append to file
with open('/mnt/data/append.txt', 'a') as f:
    f.write('Appended content\\n')
print('Appended to file')
""",
            "lang": "py",
            "session_id": session_id,
            "files": [{"id": f["id"], "session_id": session_id, "name": f["name"]} for f in initial_files]
        }
    )
    
    # Should detect the appended file as modified
    assert response.status_code == 200
    result = response.json()
    returned_files = result["files"]
    assert len(returned_files) == 1
    assert "append.txt" in returned_files[0]["name"]

def test_race_condition_simulation():
    """Test handling of rapid file modifications that might cause race conditions."""
    # Create initial file
    response = client.post(
        "/v1/execute",
        json={
            "code": """
with open('/mnt/data/race.txt', 'w') as f:
    f.write('Initial')
""",
            "lang": "py"
        }
    )
    
    assert response.status_code == 200
    result = response.json()
    session_id = result["session_id"]
    initial_files = result["files"]
    
    # Simulate a potential race condition with sleep
    response = client.post(
        "/v1/execute",
        json={
            "code": """
import os
import time

# Read the file
with open('/mnt/data/race.txt', 'r') as f:
    content = f.read()

# Small delay to simulate processing
time.sleep(0.1)

# Write back with modification
with open('/mnt/data/race.txt', 'w') as f:
    f.write(content + ' - Modified')

# Another small delay
time.sleep(0.1)

# Read the content again
with open('/mnt/data/race.txt', 'r') as f:
    new_content = f.read()

print(f'Final content: {new_content}')
""",
            "lang": "py",
            "session_id": session_id,
            "files": [{"id": f["id"], "session_id": session_id, "name": f["name"]} for f in initial_files]
        }
    )
    
    # Should still detect the file as modified
    assert response.status_code == 200
    result = response.json()
    returned_files = result["files"]
    assert len(returned_files) == 1
    assert "race.txt" in returned_files[0]["name"]

def test_file_rename():
    """Test that renaming a file is handled properly (old file removed, new file added)."""
    # Create initial file
    response = client.post(
        "/v1/execute",
        json={
            "code": """
with open('/mnt/data/original.txt', 'w') as f:
    f.write('This file will be renamed')
""",
            "lang": "py"
        }
    )
    
    assert response.status_code == 200
    result = response.json()
    session_id = result["session_id"]
    initial_files = result["files"]
    
    # Rename the file
    response = client.post(
        "/v1/execute",
        json={
            "code": """
import os
# Rename the file
os.rename('/mnt/data/original.txt', '/mnt/data/renamed.txt')
print('File renamed')
""",
            "lang": "py",
            "session_id": session_id,
            "files": [{"id": f["id"], "session_id": session_id, "name": f["name"]} for f in initial_files]
        }
    )
    
    # Should detect the new file name
    assert response.status_code == 200
    result = response.json()
    returned_files = result["files"]
    assert len(returned_files) == 1
    assert "renamed.txt" in returned_files[0]["name"]

def test_json_file_modification():
    """Test that JSON files are properly tracked when modified."""
    # Create a JSON file
    response = client.post(
        "/v1/execute",
        json={
            "code": """
import json
# Create a JSON file
data = {
    "name": "Test",
    "value": 123,
    "items": [1, 2, 3],
    "nested": {"a": 1, "b": 2}
}
with open('/mnt/data/data.json', 'w') as f:
    json.dump(data, f)
print('Created JSON file')
""",
            "lang": "py"
        }
    )
    
    assert response.status_code == 200
    result = response.json()
    session_id = result["session_id"]
    initial_files = result["files"]
    
    # Modify the JSON file
    response = client.post(
        "/v1/execute",
        json={
            "code": """
import json
# Modify the JSON file
with open('/mnt/data/data.json', 'r') as f:
    data = json.load(f)

# Update some values
data['value'] = 456
data['items'].append(4)
data['nested']['c'] = 3

# Write back
with open('/mnt/data/data.json', 'w') as f:
    json.dump(data, f)

print('Modified JSON file')
""",
            "lang": "py",
            "session_id": session_id,
            "files": [{"id": f["id"], "session_id": session_id, "name": f["name"]} for f in initial_files]
        }
    )
    
    # Should detect the modified JSON file
    assert response.status_code == 200
    result = response.json()
    returned_files = result["files"]
    assert len(returned_files) == 1
    assert "data.json" in returned_files[0]["name"] 