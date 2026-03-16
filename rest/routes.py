"""Router assembly with versioned prefix."""

from fastapi import APIRouter

from rest.v1.transcriptions.router import router as transcriptions_router

router = APIRouter(prefix="/v1")
router.include_router(transcriptions_router)
