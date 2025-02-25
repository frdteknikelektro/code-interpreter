from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from datetime import datetime

from .base import FileObject, ExecuteResponse, UploadResponse, Error


class LibreChatFileRef(BaseModel):
    """LibreChat-specific file reference."""

    id: str  # Unique identifier for the file
    name: str  # Name of the file, just the filename, not the path
    path: Optional[str] = (
        None  # Path to the file in the system, not sure if needed based on LibreChat processCodeOutput method inputs
    )


class LibreChatUploadFileObject(BaseModel):
    """LibreChat-specific upload file object."""

    fileId: str  # just file ID with slightly different name
    filename: str  # just file name with slightly different name


class LibreChatUploadResponse(BaseModel):
    """LibreChat-specific upload response."""

    message: str
    session_id: str
    files: List[LibreChatUploadFileObject]

    @classmethod
    def from_base(cls, response: UploadResponse) -> "LibreChatUploadResponse":
        """Convert base UploadResponse to LibreChat format."""
        return cls(
            message="success",
            session_id=response.session_id,
            files=[LibreChatUploadFileObject(fileId=f.id, filename=f.name) for f in response.files],
        )


class LibreChatFileObject(BaseModel):
    """LibreChat-specific file object."""

    name: str  # Format: session_id/fileId
    lastModified: str

    @classmethod
    def from_base(cls, file: FileObject) -> "LibreChatFileObject":
        """Convert base FileObject to LibreChat format."""
        return cls(
            name=f"{file.session_id}/{file.id}",
            lastModified=file.lastModified,
        )


class LibreChatExecuteResponse(BaseModel):
    """LibreChat-specific execution response."""

    session_id: str
    stdout: str
    stderr: str
    files: Optional[List[LibreChatFileRef]] = None

    @classmethod
    def from_base(cls, response: ExecuteResponse) -> "LibreChatExecuteResponse":
        """Convert base ExecuteResponse to LibreChat format."""
        return cls(
            session_id=response.session_id,
            stdout=response.run.stdout or "",
            stderr=response.run.stderr or "",
            files=[f.model_dump() for f in response.files] if response.files else None,
        )


class LibreChatError(BaseModel):
    """LibreChat-specific error response."""

    message: str

    @classmethod
    def from_base(cls, error: Error) -> "LibreChatError":
        """Convert base Error to LibreChat format."""
        return cls(message=f"{error.error}: {error.details}" if error.details else error.error)
