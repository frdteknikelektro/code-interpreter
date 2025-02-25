import pytest
from datetime import datetime
from pydantic import ValidationError

from app.models.base import (
    Error,
    FileRef,
    RequestFile,
    CodeExecutionRequest,
    ExecutionResult,
    ExecuteResponse,
    FileObject,
    UploadResponse,
)
from app.models.librechat import (
    LibreChatFileRef,
    LibreChatUploadResponse,
    LibreChatFileObject,
    LibreChatExecuteResponse,
    LibreChatError,
)


def test_base_error_model():
    """Test Error model validation."""
    error = Error(error="Test error")
    assert error.error == "Test error"
    assert error.details is None

    error_with_details = Error(error="Test error", details="More info")
    assert error_with_details.error == "Test error"
    assert error_with_details.details == "More info"


def test_file_ref_model():
    """Test FileRef model validation."""
    file_ref = FileRef(id="123", name="test.txt")
    assert file_ref.id == "123"
    assert file_ref.name == "test.txt"
    assert file_ref.path is None

    file_ref_with_path = FileRef(id="123", name="test.txt", path="/tmp")
    assert file_ref_with_path.path == "/tmp"


def test_code_execution_request():
    """Test CodeExecutionRequest model validation."""
    # Test valid Python request
    request = CodeExecutionRequest(code="print('hello')", lang="py")
    assert request.code == "print('hello')"
    assert request.lang == "py"

    # Test invalid language
    with pytest.raises(ValidationError):
        CodeExecutionRequest(code="print('hello')", lang="invalid")

    # Test with optional fields
    request = CodeExecutionRequest(
        code="print('hello')",
        lang="py",
        args=["--verbose"],
        user_id="user123",
        entity_id="asst_123",
        files=[RequestFile(id="1", session_id="sess1", name="test.txt")],
    )
    assert request.args == ["--verbose"]
    assert request.user_id == "user123"
    assert request.entity_id == "asst_123"
    assert len(request.files) == 1


def test_execute_response():
    """Test ExecuteResponse model."""
    result = ExecutionResult(stdout="output", stderr="error", code=0)
    response = ExecuteResponse(
        run=result, language="py", version="3.9.0", session_id="sess1", files=[FileRef(id="1", name="output.txt")]
    )
    assert response.run.stdout == "output"
    assert response.run.stderr == "error"
    assert response.language == "py"
    assert len(response.files) == 1


def test_librechat_file_ref():
    """Test LibreChat file reference model."""
    file_ref = LibreChatFileRef(id="123", name="test.txt")
    assert file_ref.id == "123"
    assert file_ref.name == "test.txt"


def test_librechat_upload_response():
    """Test LibreChat upload response model and conversion."""
    # Create base response
    base_response = UploadResponse(
        message="success",
        session_id="sess1",
        files=[FileObject(name="test.txt", id="123", session_id="sess1", size=100)],
    )

    # Convert to LibreChat format
    libre_response = LibreChatUploadResponse.from_base(base_response)
    assert libre_response.message == "success"
    assert libre_response.session_id == "sess1"
    assert len(libre_response.files) == 1
    assert libre_response.files[0].fileId == "123"
    assert libre_response.files[0].filename == "test.txt"


def test_librechat_file_object():
    """Test LibreChat file object model and conversion."""
    last_modified = datetime.now().isoformat()
    # Create base file object
    base_file = FileObject(
        name="test.txt", id="123", session_id="sess1", size=100, contentType="text/plain", lastModified=last_modified
    )

    # Convert to LibreChat format
    libre_file = LibreChatFileObject.from_base(base_file)
    assert libre_file.name == "sess1/123"
    assert libre_file.lastModified == last_modified


def test_librechat_execute_response():
    """Test LibreChat execute response model and conversion."""
    # Create base response
    result = ExecutionResult(stdout="output", stderr="error")
    base_response = ExecuteResponse(
        run=result, language="py", version="3.9.0", session_id="sess1", files=[FileRef(id="1", name="output.txt")]
    )

    # Convert to LibreChat format
    libre_response = LibreChatExecuteResponse.from_base(base_response)
    assert libre_response.session_id == "sess1"
    assert libre_response.stdout == "output"
    assert libre_response.stderr == "error"
    assert libre_response.files is not None
    assert len(libre_response.files) == 1


def test_librechat_error():
    """Test LibreChat error model and conversion."""
    # Create base error
    base_error = Error(error="Test error", details="More info")

    # Convert to LibreChat format
    libre_error = LibreChatError.from_base(base_error)
    assert libre_error.message == "Test error: More info"

    # Test without details
    base_error = Error(error="Test error")
    libre_error = LibreChatError.from_base(base_error)
    assert libre_error.message == "Test error"
