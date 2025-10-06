from fastapi import APIRouter, UploadFile, File, HTTPException, Path, Form, Request, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from typing import List, Optional
from loguru import logger
from io import BytesIO

from app.api.exceptions import BadLanguageException

from ..models.base import (
    PathParams,
    SuccessResponse,
    CodeExecutionRequest,
)
from ..models.librechat import (
    LibreChatExecuteResponse,
    LibreChatUploadResponse,
    LibreChatFileObject,
    LibreChatError,
)
from ..shared.config import get_settings
from .base import (
    execute_code as base_execute_code,
    upload_files as base_upload_files,
    download_file as base_download_file,
    list_files as base_list_files,
    delete_file as base_delete_file,
)
from .dependencies import verify_api_key

settings = get_settings()
router = APIRouter(prefix=f"{settings.API_PREFIX}/librechat", tags=["librechat"], dependencies=[Depends(verify_api_key)])


def create_error_response(status_code: int, message: str) -> JSONResponse:
    """Create a standardized error response for the LibreChat API.

    Args:
        status_code (int): HTTP status code to return
        message (str): Error message to include in the response

    Returns:
        JSONResponse: A FastAPI JSON response containing the error details in LibreChat format
    """
    return JSONResponse(status_code=status_code, content=LibreChatError(message=message).model_dump())


@router.post(
    "/exec",
    responses={400: {"model": LibreChatError}, 500: {"model": LibreChatError}},
    response_model=LibreChatExecuteResponse,
    description="Execute Python or R code in a sandboxed environment",
    summary="Execute code",
    response_description="Returns the execution results",
)
async def execute_code(request: CodeExecutionRequest) -> LibreChatExecuteResponse:
    """Execute code in a sandboxed environment.

    This endpoint handles code execution requests from LibreChat. It processes the provided
    code in an isolated environment and returns the execution results.

    Args:
        request (CodeExecutionRequest): Request object containing:
            - code: Code to execute
            - files: Optional list of files needed for execution
            - language: Programming language ('py' for Python or 'r' for R)
            - stdin: Optional standard input for the code

    Returns:
        LibreChatExecuteResponse: Object containing:
            - output: Execution output (stdout/stderr)
            - error: Error message if execution failed
            - exitCode: Process exit code

    Raises:
        HTTPException:
            - 400: Invalid request parameters
            - 401: Unauthorized access
            - 500: Internal server error during execution
            - 503: Service temporarily unavailable
    """
    try:
        logger.info(f"Executing code request: {request.model_dump_json()}")

        result = await base_execute_code(request)
        logger.debug(f"Execution result: {result}")
        return LibreChatExecuteResponse.from_base(result)
    except BadLanguageException as e:
        return JSONResponse(
            status_code=200,
            content={
                "stdout": f"{e.detail}",
                "stderr": None,
                "files": [],
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in execute_code: {str(e)}", exc_info=True)
        return create_error_response(500, str(e))


@router.post(
    "/upload",
    responses={413: {"model": LibreChatError}, 400: {"model": LibreChatError}, 500: {"model": LibreChatError}},
    description="Upload files for code execution",
    summary="Upload files",
    response_description="Returns information about the uploaded files",
)
async def upload_files(
    request: Request,
    file: UploadFile = File(...),
    entity_id: Optional[str] = Form(None),
    session_id: Optional[str] = Form(None),
) -> JSONResponse:
    """Upload files for use in code execution.

    This endpoint handles file uploads from LibreChat clients. Files are stored temporarily
    and can be referenced in subsequent code execution requests.

    Args:
        request (Request): The FastAPI request object containing metadata
        file (UploadFile): The file to be uploaded
        entity_id (Optional[str], optional): Unique identifier for the entity owning the file
        session_id (Optional[str], optional): Existing session identifier to append the file to

    Returns:
        JSONResponse: Response containing:
            - files: List of successfully uploaded file objects
            - error: Error message if upload failed

    Raises:
        HTTPException:
            - 400: Invalid file or request parameters
            - 413: File size exceeds maximum allowed size
            - 500: Internal server error during upload
    """
    try:
        logger.info(f"File: {file.filename}, content_type: {file.content_type}")

        content = await file.read()
        file_size = len(content)
        logger.debug(f"File size: {file_size} bytes")

        if file_size > settings.FILE_MAX_UPLOAD_SIZE:
            return create_error_response(413, f"File exceeds size limit of {settings.FILE_MAX_UPLOAD_SIZE} bytes")

        # Reset file pointer and prepare for upload
        file.file = BytesIO(content)
        response = await base_upload_files(files=[file], entity_id=entity_id, session_id=session_id)

        if not response.files:
            return create_error_response(500, "File upload failed")

        result = LibreChatUploadResponse.from_base(response)
        logger.info(f"Upload successful: {result.model_dump()}")

        return JSONResponse(content=result.model_dump())

    except Exception as e:
        logger.error(f"Error processing upload: {str(e)}", exc_info=True)
        return create_error_response(400, str(e))


@router.get(
    "/download/{session_id}/{file_id}",
    responses={404: {"model": LibreChatError}, 400: {"model": LibreChatError}},
    description="Download a file by session ID and file ID",
    summary="Download a file",
    response_description="Returns the file as a streaming response",
)
async def download_file(
    session_id: str = Path(..., description=PathParams.model_fields["session_id"].description),
    file_id: str = Path(..., description=PathParams.model_fields["file_id"].description),
) -> StreamingResponse:
    """Download a previously uploaded file.

    Retrieves a file that was previously uploaded and streams it back to the client.
    Files are identified by both session ID and file ID for security.

    Args:
        session_id (str): Unique identifier for the session that owns the file
        file_id (str): Unique identifier for the specific file to download

    Returns:
        StreamingResponse: Streams the file content with appropriate content type

    Raises:
        HTTPException:
            - 400: Invalid request parameters
            - 404: File not found
    """
    try:
        logger.info(f"Downloading file {file_id} from session {session_id}")
        return await base_download_file(session_id=session_id, file_id=file_id)
    except Exception as e:
        logger.error(f"Error downloading file: {str(e)}", exc_info=True)
        return create_error_response(404, str(e))


@router.get(
    "/files/{session_id}",
    response_model=List[LibreChatFileObject],
    responses={400: {"model": LibreChatError}, 404: {"model": LibreChatError}},
    description="List all files associated with a session",
    summary="List session files",
    response_description="Returns a list of file objects for the session",
)
async def list_files(
    session_id: str = Path(..., description=PathParams.model_fields["session_id"].description),
    detail: Optional[str] = None,
) -> JSONResponse:
    """List all files associated with a session.

    Retrieves metadata for all files uploaded in a specific session.

    Args:
        session_id (str): Unique identifier for the session
        detail (Optional[str], optional): Level of detail to include in the response.
            If provided, may include additional file metadata.

    Returns:
        JSONResponse: List of LibreChatFileObject containing file metadata:
            - id: Unique file identifier
            - name: Original filename
            - type: File MIME type
            - size: File size in bytes
            - path: Internal storage path
            - session_id: Associated session identifier

    Raises:
        HTTPException:
            - 400: Invalid session ID or parameters
            - 404: Session not found
    """
    try:
        logger.info(f"Listing files for session {session_id}, detail={detail}")
        files = await base_list_files(session_id=session_id)
        logger.debug(f"Found {len(files)} files")

        result: List[LibreChatFileObject] = []
        for file in files:
            logger.debug(f"Processing file: {file.model_dump_json()}")
            file_data = LibreChatFileObject.from_base(file)
            result.append(file_data)

        return result

    except Exception as e:
        logger.error(f"Error listing files: {str(e)}", exc_info=True)
        return create_error_response(400, str(e))


@router.delete(
    "/files/{session_id}/{file_id}",
    response_model=SuccessResponse,
    responses={404: {"model": LibreChatError}, 400: {"model": LibreChatError}},
    description="Delete a specific file by session ID and file ID",
    summary="Delete a file",
    response_description="Returns a success message if file was deleted",
)
async def delete_file(
    session_id: str = Path(..., description=PathParams.model_fields["session_id"].description),
    file_id: str = Path(..., description=PathParams.model_fields["file_id"].description),
) -> SuccessResponse:
    """Delete a specific file from storage.

    Permanently removes a file from the system. The file must belong to the specified session.

    Args:
        session_id (str): Unique identifier for the session that owns the file
        file_id (str): Unique identifier for the specific file to delete

    Returns:
        SuccessResponse: Object confirming successful deletion with message

    Raises:
        HTTPException:
            - 400: Invalid request parameters
            - 404: File or session not found
    """
    try:
        logger.info(f"Deleting file {file_id} from session {session_id}")
        return await base_delete_file(session_id=session_id, file_id=file_id)
    except Exception as e:
        logger.error(f"Error deleting file: {str(e)}", exc_info=True)
        return create_error_response(404, str(e))
