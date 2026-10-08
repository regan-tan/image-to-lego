from fastapi import APIRouter

from app.api.v1.artifacts import router as artifacts_router
from app.api.v1.health import router as health_router
from app.api.v1.profile import router as profile_router
from app.api.v1.projects import router as projects_router
from app.api.v1.reconstructions import router as reconstructions_router
from app.api.v1.uploads import router as uploads_router

router = APIRouter(prefix="/api/v1")
router.include_router(artifacts_router)
router.include_router(health_router)
router.include_router(profile_router)
router.include_router(projects_router)
router.include_router(reconstructions_router)
router.include_router(uploads_router)
