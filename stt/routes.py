"""Router assembly with versioned prefix."""

from fastapi import APIRouter

from stt.v1.transcriptions.router import router as transcriptions_router

router = APIRouter(prefix="/v1")
router.include_router(transcriptions_router)
