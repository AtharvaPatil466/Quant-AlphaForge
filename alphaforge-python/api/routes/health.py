from fastapi import APIRouter

from api.schemas import HealthResponse
from version import __version__

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health_check():
    return HealthResponse(status="ok", version=__version__)
