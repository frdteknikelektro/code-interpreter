from pathlib import Path
from typing import List, Dict, Any
import aiofiles
from loguru import logger
import hashlib
import magic
from datetime import datetime, timezone

from ..shared.config import get_settings
from .database import db_manager
from app.utils.generate_id import generate_id

settings = get_settings()


class FileManager:
    """Manages file operations for code interpreter sessions."""

    def __init__(self):
        self.upload_path = Path("/app/uploads")
        self.upload_path.mkdir(parents=True, exist_ok=True)
        self._mime = magic.Magic(mime=True)

    def _get_session_dir(self, session_id: str) -> Path:
        """Get the directory for a specific session."""
        session_dir = self.upload_path / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir

    def _calculate_etag(self, content: bytes) -> str:
        """Calculate ETag for file content."""
        return hashlib.md5(content).hexdigest()

    def _get_content_type(self, content: bytes, filename: str) -> str:
        """Detect content type of the file."""
        return self._mime.from_buffer(content)

    async def save_file(self, session_id: str, file_content: bytes, filename: str) -> Dict[str, Any]:
        """Save a file for a session."""
        try:
            # Validate file extension
            ext = Path(filename).suffix[1:].lower()
            if ext not in settings.FILE_ALLOWED_EXTENSIONS:
                logger.error(f"File extension {ext} not allowed")
                raise ValueError(f"File extension {ext} not allowed")

            # Generate unique ID and calculate metadata
            file_id = generate_id()
            etag = self._calculate_etag(file_content)
            content_type = self._get_content_type(file_content, filename)
            current_time = datetime.now(timezone.utc).isoformat()

            # Save file in session directory with original name
            session_dir = self._get_session_dir(session_id)
            file_path = session_dir / filename

            logger.info(f"Saving file to path: {file_path}")
            logger.info(f"File content size: {len(file_content)} bytes")

            # Save file
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(file_content)

            # Verify file was written
            if not file_path.exists():
                logger.error(f"File was not written to disk: {file_path}")
                raise RuntimeError(f"Failed to write file to disk: {file_path}")

            actual_size = file_path.stat().st_size
            if actual_size != len(file_content):
                logger.error(f"File size mismatch. Expected: {len(file_content)}, Got: {actual_size}")
                raise RuntimeError("File size mismatch after writing to disk")

            logger.info(f"File successfully written to disk: {file_path}")

            # Prepare file metadata
            file_data = {
                "id": file_id,
                "session_id": session_id,
                "filename": filename,
                "filepath": str(file_path.relative_to(self.upload_path)),
                "size": actual_size,
                "content_type": content_type,
                "original_filename": filename,
                "etag": etag,
                "metadata": {"content-type": content_type, "original-filename": filename, "lastModified": current_time},
            }

            # Save to database
            await db_manager.add_file(file_data)
            logger.info(f"File metadata saved to database: {file_id}")

            # Format response according to API spec
            return {
                "name": filename,
                "id": file_id,
                "session_id": session_id,
                "size": len(file_content),
                "lastModified": current_time,
                "etag": etag,
                "metadata": {"content-type": content_type, "original-filename": filename, "lastModified": current_time},
                "contentType": content_type,
            }
        except Exception as e:
            logger.error(f"Error saving file {filename}: {str(e)}", exc_info=True)
            raise

    async def get_file(self, session_id: str, file_id: str, include_content: bool = True) -> Dict[str, Any]:
        """Get file information and optionally its content."""
        # Get file metadata from database
        file_info = await db_manager.get_file(session_id, file_id)
        if not file_info:
            raise FileNotFoundError(f"File {file_id} not found")

        file_path = self.upload_path / file_info["filepath"]

        response = {
            "name": file_info["filename"],
            "id": file_id,
            "session_id": session_id,
            "size": file_info["size"],
            "lastModified": file_info["last_modified"],
            "etag": file_info["etag"],
            "metadata": {
                "content-type": file_info["content_type"],
                "original-filename": file_info["original_filename"],
            },
            "contentType": file_info["content_type"],
        }

        if include_content:
            async with aiofiles.open(file_path, "rb") as f:
                content = await f.read()
                response["content"] = content

        return response

    async def delete_file(self, session_id: str, file_id: str) -> None:
        """Delete a file."""
        # Get file info from database
        file_info = await db_manager.get_file(session_id, file_id)
        if not file_info:
            raise FileNotFoundError(f"File {file_id} not found")

        # Delete from filesystem
        file_path = self.upload_path / file_info["filepath"]
        if file_path.exists():
            file_path.unlink()

        # Delete from database
        await db_manager.delete_file(session_id, file_id)

        # Clean up empty session directory
        session_dir = file_path.parent
        if session_dir.exists() and not any(session_dir.iterdir()):
            session_dir.rmdir()

    async def list_files(self, session_id: str) -> List[Dict[str, Any]]:
        """List all files for a session."""
        files = await db_manager.list_files(session_id)

        return [
            {
                "name": file["filename"],
                "id": file["id"],
                "session_id": session_id,
                "size": file["size"],
                "lastModified": file["last_modified"],
                "etag": file["etag"],
                "metadata": {"content-type": file["content_type"], "original-filename": file["original_filename"]},
                "contentType": file["content_type"],
            }
            for file in files
        ]

    async def cleanup_session(self, session_id: str) -> None:
        """Clean up all files for a session.
        Note: This method should only be used when you're certain that all files
        for this session should be removed. For normal cleanup, prefer the TTL-based
        cleanup mechanism in the cleanup service."""
        # Get files from database first
        files = await db_manager.list_files(session_id)

        # Delete each file properly
        for file in files:
            try:
                await self.delete_file(session_id, file["id"])
            except Exception as e:
                logger.error(f"Error deleting file {file['id']}: {e}")


# Create a singleton instance
file_manager = FileManager()
