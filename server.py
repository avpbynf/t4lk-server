import io
import json
import logging
import os
import site
import time
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path

# Add nvidia DLLs to PATH before importing ctranslate2/faster_whisper
for _sp in site.getsitepackages():
    _site_packages = Path(_sp)
    for _nvidia_pkg in _site_packages.glob("nvidia/*/bin"):
        os.add_dll_directory(str(_nvidia_pkg))
        os.environ["PATH"] = str(_nvidia_pkg) + os.pathsep + os.environ.get("PATH", "")

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from faster_whisper import WhisperModel
from pydantic import BaseModel, Field

load_dotenv()

# Import database and auth modules
from admin import router as admin_router
from auth.dependencies import CurrentToken
from db.database import close_db, init_db

logger = logging.getLogger("whisper-server")

model: WhisperModel | None = None

GOBLIN_FORMALIZER_URL = "https://goblin.tools/api/Formalizer"

GOBLIN_MODS = [
    "professional",
    "technical",
    "accessible",
    "polite",
    "snarky",
    "angry",
    "readable",
    "formal",
    "informal",
    "sociable",
    "concise",
    "calm",
    "passionate",
    "sarcastic",
    "grammatical",
    "bullets",
    "thesaurus",
]


def goblin_format(text: str, conversion: str, spiciness: int, language: str = "fr") -> str | None:
    """Call Goblin Tools Formalizer API to format text."""
    if conversion not in GOBLIN_MODS:
        logger.warning("Unknown goblin conversion '%s', falling back to 'grammatical'", conversion)
        conversion = "grammatical"

    spiciness = max(1, min(5, spiciness))
    url = f"{GOBLIN_FORMALIZER_URL}?l={language}"
    payload = json.dumps({
        "Text": text,
        "Conversion": conversion,
        "Spiciness": str(spiciness),
    }).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        response = urllib.request.urlopen(req, timeout=15)
        result = response.read().decode().strip()
        logger.info(
            "Goblin format: '%s...' -> '%s...' (conversion=%s, spiciness=%d, lang=%s)",
            text[:50], result[:50], conversion, spiciness, language,
        )
        return result if result else None
    except Exception:
        logger.exception("Goblin Tools API failed (conversion=%s, spiciness=%d)", conversion, spiciness)
        return None


class FormatRequest(BaseModel):
    text: str
    style_prompt: str = "grammatical"
    intensity: int = Field(default=3, ge=1, le=5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global model

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Initialize database
    logger.info("Initializing database...")
    await init_db()
    logger.info("Database ready")

    # Load Whisper model
    model_name = os.getenv("WHISPER_MODEL", "Systran/faster-whisper-large-v3")
    logger.info("Loading Whisper model: %s (may take a while on first run)", model_name)
    model = WhisperModel(
        model_name,
        device="cuda",
        compute_type="int8_float16",
    )
    logger.info("Whisper model '%s' loaded on CUDA", model_name)
    logger.info("Formatting backend: goblin_tools (%d mods)", len(GOBLIN_MODS))

    yield

    # Cleanup
    model = None
    await close_db()


app = FastAPI(title="Whisper API", lifespan=lifespan)

# Include admin routes
app.include_router(admin_router)


@app.post("/transcribe")
async def transcribe(
    token: CurrentToken,
    file: UploadFile = File(...),
    language: str | None = None,
    initial_prompt: str | None = Form(None),
):
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    content = await file.read()
    audio_stream = io.BytesIO(content)

    start_time = time.perf_counter()
    segments, info = model.transcribe(
        audio_stream, language=language, initial_prompt=initial_prompt, vad_filter=True,
    )
    text = "".join(segment.text for segment in segments)

    process_time = time.perf_counter() - start_time

    return JSONResponse(
        {
            "text": text.strip(),
            "language": info.language,
            "duration": info.duration,
            "process_time": round(process_time, 3),
        }
    )


@app.post("/transcribe/stream")
async def transcribe_stream(
    token: CurrentToken,
    file: UploadFile = File(...),
    language: str | None = None,
    initial_prompt: str | None = Form(None),
    format_style_prompt: str | None = Form(None),
    format_intensity: int | None = Form(None),
):
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    content = await file.read()
    audio_stream = io.BytesIO(content)

    should_format = format_style_prompt is not None

    def generate():
        start_time = time.perf_counter()

        if should_format:
            yield f"data: {json.dumps({'step': 'transcribing'})}\n\n"

        segments, info = model.transcribe(
            audio_stream, language=language, initial_prompt=initial_prompt, vad_filter=True,
        )

        full_text = ""
        for segment in segments:
            full_text += segment.text
            yield f"data: {json.dumps({'text': segment.text, 'start': segment.start, 'end': segment.end})}\n\n"

        final_text = full_text.strip()
        formatted = False

        if should_format and final_text:
            yield f"data: {json.dumps({'step': 'formatting'})}\n\n"

            intensity = format_intensity if format_intensity is not None else 3
            intensity = max(1, min(5, intensity))

            lang = info.language if info.language else "fr"
            result = goblin_format(final_text, format_style_prompt, intensity, lang)

            if result:
                final_text = result
                formatted = True

        process_time = time.perf_counter() - start_time
        yield f"data: {json.dumps({'done': True, 'text': final_text, 'formatted': formatted, 'process_time': round(process_time, 3), 'language': info.language})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/format")
async def format_text(
    token: CurrentToken,
    request: FormatRequest,
):
    start_time = time.perf_counter()

    result = goblin_format(request.text, request.style_prompt, request.intensity)

    process_time = time.perf_counter() - start_time

    if result is None:
        raise HTTPException(status_code=502, detail="Formatting failed")

    return JSONResponse(
        {
            "text": result,
            "original": request.text,
            "process_time": round(process_time, 3),
        }
    )


@app.get("/format/mods")
async def format_mods():
    """List available Goblin Tools mods and intensity range."""
    return {
        "goblin_mods": GOBLIN_MODS,
        "intensity_range": {"min": 1, "max": 5},
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "whisper_loaded": model is not None,
        "formatters": ["goblin"],
    }


@app.get("/auth/verify")
async def verify_auth(token: CurrentToken):
    """Verify that the provided Bearer token is valid."""
    return {
        "valid": True,
        "token_name": token.name,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
