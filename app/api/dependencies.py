from typing import Annotated

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.shared.config import get_settings


api_key_header = APIKeyHeader(name="X-Api-Key", auto_error=False)


async def verify_api_key(x_api_key: Annotated[str | None, Security(api_key_header)] = None) -> None:
    """Ensure that the request provides the expected API key."""
    settings = get_settings()
    expected_key = settings.API_KEY

    if not expected_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API key is not configured",
        )

    if x_api_key != expected_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
