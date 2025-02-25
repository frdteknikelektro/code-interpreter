from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class Error(BaseModel):
    """Base error model as defined in OpenAPI spec."""

    error: str
    details: Optional[str] = None


class FileRef(BaseModel):
    """File reference model as defined in OpenAPI spec."""

    id: str
    name: str  # Name of the file, just the filename, not the path
    path: Optional[str] = None


class RequestFile(BaseModel):
    """Request file model as defined in OpenAPI spec."""

    id: str
    session_id: str
    name: str


class CodeExecutionRequest(BaseModel):
    """Code execution request model as defined in OpenAPI spec."""

    code: str = Field(..., description="The source code to be executed")
    lang: str = Field(
        ...,
        description="The programming language of the code",
        examples=["py"],
        pattern="^(c|cpp|d|f90|go|java|js|php|py|rs|ts|r)$",
    )
    args: Optional[List[str]] = Field(None, description="Optional command line arguments to pass to the program")
    user_id: Optional[str] = Field(None, description="Optional user identifier")
    entity_id: Optional[str] = Field(
        None,
        description="Optional assistant/agent identifier for file sharing and reference",
        max_length=40,
        pattern="^[A-Za-z0-9_-]+$",
        examples=["asst_axIyVEqAa3UVppsVP3WTl5So"],
    )
    files: Optional[List[RequestFile]] = Field(None, description="Array of file references to be used during execution")


class ExecutionResult(BaseModel):
    """Execution result model as defined in OpenAPI spec."""

    stdout: Optional[str] = None
    stderr: Optional[str] = None
    code: Optional[int] = None
    signal: Optional[str] = None
    output: Optional[str] = None
    memory: Optional[int] = None
    message: Optional[str] = None
    status: Optional[str] = None
    cpu_time: Optional[float] = None
    wall_time: Optional[float] = None


class ExecuteResponse(BaseModel):
    """Execute response model as defined in OpenAPI spec."""

    run: ExecutionResult
    language: str
    version: str
    session_id: str
    files: List[FileRef] = []


class FileMetadata(BaseModel):
    """File metadata model as defined in OpenAPI spec."""

    content_type: Optional[str] = Field(None, alias="content-type")
    original_filename: Optional[str] = Field(None, alias="original-filename")


class FileObject(BaseModel):
    """File object model as defined in OpenAPI spec."""

    name: str  # just request filename, not the path
    id: str
    session_id: str
    content: Optional[str] = None
    size: Optional[int]
    lastModified: Optional[str] = None
    etag: Optional[str] = None
    metadata: Optional[FileMetadata] = None
    contentType: Optional[str] = None


class UploadResponse(BaseModel):
    """Upload response model as defined in OpenAPI spec."""

    message: str
    session_id: str
    files: List[FileObject]


class PathParams(BaseModel):
    """Path parameters model."""

    session_id: str = Field(..., description="Session identifier")
    file_id: str = Field(..., description="File identifier")


class SuccessResponse(BaseModel):
    """Success response model."""

    message: str
