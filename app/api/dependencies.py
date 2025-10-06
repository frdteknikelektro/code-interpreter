from typing import Annotated

from fastapi import Header, HTTPException, status

from app.shared.config import get_settings


async def verify_api_key(x_api_key: Annotated[str | None, Header(alias="X-Api-Key", convert_underscores=False)] = None) -> None:
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
