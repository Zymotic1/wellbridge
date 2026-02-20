"""
Speech transcription router — POST /speech/transcribe

Accepts an audio file upload and returns the transcribed text using
OpenAI Whisper (whisper-1). Supports all formats MediaRecorder can produce:
  - audio/webm;codecs=opus  (Chrome / Edge)
  - audio/mp4               (Safari / iOS)
  - audio/ogg;codecs=opus   (Firefox)

The transcription result is returned immediately and never stored —
the frontend inserts it into the chat input field for the user to review
before sending.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from openai import AsyncOpenAI

from config import get_settings
from middleware.tenant import get_tenant_context, TenantContext

log = logging.getLogger("wellbridge.speech")
settings = get_settings()

router = APIRouter(prefix="/speech", tags=["speech"])


@router.post("/transcribe")
async def transcribe_audio(
    audio: UploadFile = File(...),
    ctx: TenantContext = Depends(get_tenant_context),
):
    """
    Transcribe an audio recording to text using OpenAI Whisper.

    Expects multipart/form-data with field name 'audio'.
    Returns { "text": "transcribed content" }.
    """
    try:
        audio_bytes = await audio.read()
        if not audio_bytes:
            raise HTTPException(status_code=400, detail="Empty audio file.")

        # Determine file extension so Whisper can detect the format correctly.
        raw_content_type = audio.content_type or "audio/webm"
        # Strip codec parameters — Whisper only accepts the base MIME type
        # e.g. "audio/webm;codecs=opus" → "audio/webm"
        content_type = raw_content_type.lower().split(";")[0].strip()
        ext = _ext_from_content_type(content_type)
        filename = f"recording.{ext}"

        log.info("Transcribing audio: size=%d bytes, type=%s, file=%s",
                 len(audio_bytes), content_type, filename)

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        transcript = await client.audio.transcriptions.create(
            model="whisper-1",
            file=(filename, audio_bytes, content_type),
            language="en",
        )
        return {"text": transcript.text.strip()}

    except HTTPException:
        raise
    except Exception as exc:
        log.warning("Whisper transcription failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Transcription failed: {exc}")


def _ext_from_content_type(ct: str) -> str:
    """Map a MIME type to the file extension Whisper expects."""
    ct = ct.lower().split(";")[0].strip()
    return {
        "audio/webm":  "webm",
        "audio/ogg":   "ogg",
        "audio/mp4":   "mp4",
        "audio/mpeg":  "mp3",
        "audio/wav":   "wav",
        "audio/x-wav": "wav",
        "audio/aac":   "aac",
        "audio/flac":  "flac",
    }.get(ct, "webm")
