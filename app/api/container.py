from fastapi import APIRouter, HTTPException

from app.shared.config import get_settings
from app.services.docker_executor import docker_executor


settings = get_settings()
router = APIRouter(prefix=settings.API_PREFIX)


@router.get("/containers/active")
async def get_active_containers():
    """Get information about currently active containers."""
    try:
        containers = await docker_executor.get_active_containers()
        return containers
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
