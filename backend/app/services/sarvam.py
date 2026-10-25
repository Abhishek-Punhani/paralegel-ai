"""Async Sarvam speech integration using the provider's documented REST APIs.

The existing httpx dependency keeps provider requests async, pools connections,
and avoids putting subscription credentials into any browser response.
"""
from __future__ import annotations

import json
import logging
from typing import AsyncIterator

import httpx
from fastapi import HTTPException

from app.config import (
    SARVAM_API_BASE_URL,
    SARVAM_API_KEY,
    SARVAM_STT_MODEL,
    SARVAM_TTS_MODEL,
    SARVAM_TTS_SPEAKER,
)

logger = logging.getLogger(__name__)
MAX_AUDIO_BYTES = 12 * 1024 * 1024
SUPPORTED_LANGUAGES = {
    "hi", "en", "bn", "gu", "kn", "ml", "mr", "od", "pa", "ta", "te",
    "as", "ur", "ne", "kok", "ks", "sd", "sa", "sat", "mni", "brx", "mai", "doi",
}
_client: httpx.AsyncClient | None = None


def language_code(language: str | None, *, detect: bool = False) -> str:
    value = (language or "hi").strip()
    if value == "unknown" and detect:
        return value
    root = value.split("-")[0].lower()
    if root not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail="Unsupported speech language")
    return f"{root}-IN"


def _http_client() -> httpx.AsyncClient:
    global _client
    if not SARVAM_API_KEY:
        raise HTTPException(status_code=503, detail="Speech service is not configured")
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=SARVAM_API_BASE_URL,
            headers={"api-subscription-key": SARVAM_API_KEY},
            timeout=httpx.Timeout(75.0, connect=10.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _check_response(response: httpx.Response) -> None:
    if response.is_success:
        return
    # Provider bodies may contain diagnostic content: never relay them to clients.
    logger.warning("Sarvam speech request failed with HTTP %s", response.status_code)
    if response.status_code == 429:
        raise HTTPException(status_code=429, detail="Speech service is busy. Please try again.", headers={"Retry-After": "3"})
    if response.status_code in (400, 422):
        # Classify provider validation errors without returning its raw response
        # (which may include request metadata) to the client or logs.
        try:
            body = response.json()
            diagnostic = json.dumps(body, ensure_ascii=False).lower() if isinstance(body, (dict, list)) else ""
        except ValueError:
            diagnostic = ""
        if any(term in diagnostic for term in ("duration", "30 second", "too long", "maximum length")):
            detail = "This recording is over Sarvam’s 30-second limit. Please send a shorter response."
        elif any(term in diagnostic for term in ("empty", "audio format", "read the file", "unsupported format", "invalid audio")):
            detail = "I could not read that recording. Please try again, or use ‘Send response’ after speaking clearly."
        else:
            detail = "Speech service rejected this recording. Please try a shorter response, and check that your microphone captured audio."
        raise HTTPException(status_code=422, detail=detail)
    raise HTTPException(status_code=502, detail="Speech service is temporarily unavailable. Please retry.")


async def transcribe(audio: bytes, filename: str, content_type: str, language: str) -> dict:
    if not audio:
        raise HTTPException(status_code=400, detail="No audio was received")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Recording is too large. Please record up to 30 seconds at a time.")
    try:
        response = await _http_client().post(
            "/speech-to-text",
            files={"file": (filename, audio, content_type)},
            data={
                "model": SARVAM_STT_MODEL,
                "language_code": language_code(language, detect=True),
                "mode": "transcribe",
                "keyterms": json.dumps(["FIR", "MACT", "NyayaLens", "insurance", "driving licence"]),
            },
        )
        _check_response(response)
        result = response.json()
        if not isinstance(result, dict) or not isinstance(result.get("transcript"), str):
            raise HTTPException(status_code=502, detail="Speech service returned an invalid transcript")
        return {"transcript": result["transcript"].strip(), "language_code": result.get("language_code")}
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Transcription took too long. Please try again.") from exc
    except (httpx.RequestError, ValueError) as exc:
        logger.warning("Sarvam transcription transport/format failure: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Could not connect to the speech service") from exc


async def stream_speech(text: str, language: str) -> AsyncIterator[bytes]:
    if not text.strip():
        raise HTTPException(status_code=422, detail="Speech text is required")
    if len(text) > 3500:
        raise HTTPException(status_code=422, detail="Speech text exceeds the 3500 character limit")
    code = language_code(language)
    model = SARVAM_TTS_MODEL
    speaker = SARVAM_TTS_SPEAKER
    # v4 has no Malayalam or Odia personas yet; keep the fallback feminine.
    if code in {"ml-IN", "od-IN"} and model == "bulbul:v4-flash":
        model, speaker = "bulbul:v3", ("pooja" if code == "ml-IN" else "ritu")
    try:
        async with _http_client().stream(
            "POST", "/text-to-speech/stream",
            json={
                "text": text,
                "language_code": code,
                "model": model,
                "speaker": speaker,
                "pace": 1.0,
                "speech_sample_rate": 24000,
                "output_audio_codec": "mp3",
            },
        ) as response:
            _check_response(response)
            async for chunk in response.aiter_bytes():
                if chunk:
                    yield chunk
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Speech synthesis took too long. Please try again.") from exc
    except httpx.RequestError as exc:
        logger.warning("Sarvam synthesis transport failure: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Could not connect to the speech service") from exc


async def synthesize(text: str, language: str) -> bytes:
    chunks = [chunk async for chunk in stream_speech(text, language)]
    audio = b"".join(chunks)
    if not audio:
        raise HTTPException(status_code=502, detail="Speech service returned empty audio")
    return audio
