"""Sarvam browser voice turns backed by the existing LangGraph intake engine."""
from __future__ import annotations

import asyncio
import base64
import logging
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from langchain_core.messages import HumanMessage
from langgraph.types import Command
from pydantic import BaseModel, Field

from app.services import sarvam

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/voice", tags=["Sarvam Voice"])
_turn_locks: dict[str, asyncio.Lock] = {}


class StartVoiceRequest(BaseModel):
    language: str = "hi"


class SynthesisRequest(BaseModel):
    text: str = Field(min_length=1, max_length=3500)
    language: str = "hi"


def _runtime():
    # Import on requests to keep the main application and router import acyclic.
    from app import main
    return main


def _require_session(session_id: str):
    runtime = _runtime()
    runtime._session_metadata(session_id)
    current = runtime._get_current_state(session_id)
    if session_id not in runtime.active_sessions:
        if current is None:
            raise HTTPException(status_code=404, detail="Intake link not found. Ask your lawyer for a new link.")
        runtime.active_sessions[session_id] = {
            "language": current.get("language", "hi"),
            "lawyer_name": current.get("lawyer_name"),
            "lawyer_contact": current.get("lawyer_contact"),
            "status": "INTAKE",
        }
    return runtime, current


def _pending_prompt(snapshot) -> dict:
    for task in snapshot.tasks or ():
        for interruption in task.interrupts or ():
            value = interruption.value
            if isinstance(value, dict):
                return value
    return {}


def _document_requests(state: dict) -> list[dict]:
    documents = []
    for doc in state.get("documents", []):
        item = doc.model_dump() if hasattr(doc, "model_dump") else doc
        if item.get("upload_status") == "requested":
            documents.append({"doc_id": item["doc_id"], "doc_type": item["doc_type"]})
    return documents


async def _reply(snapshot, language: str, transcript: str = "") -> dict:
    state = snapshot.values or {}
    prompt = _pending_prompt(snapshot)
    spoken_response = prompt.get("spoken_response") or prompt.get("next_question") or ""
    complete = not snapshot.next and not prompt
    if complete and not spoken_response:
        spoken_response = (
            "Thank you. Your interview has been saved for your lawyer to review."
            if language.startswith("en") else
            "धन्यवाद। आपकी जानकारी सुरक्षित कर दी गई है। आपके वकील इसकी समीक्षा करेंगे।"
        )
    result = {
        "transcript": transcript,
        "spoken_response": spoken_response,
        "audio_base64": None,
        "audio_mime": "audio/mpeg",
        "pending_documents": _document_requests(state),
        "interview_stage": prompt.get("stage") or state.get("interview_stage", "narrative"),
        "question_key": prompt.get("key"),
        "consent_step": prompt.get("consent_step"),
        "complete": complete,
    }
    if spoken_response:
        try:
            audio = await sarvam.synthesize(spoken_response, language)
            result["audio_base64"] = base64.b64encode(audio).decode("ascii")
        except HTTPException as exc:
            # Preserve the saved interview turn and display its real text if TTS fails.
            logger.warning("Voice playback unavailable (HTTP %s)", exc.status_code)
            result["audio_error"] = exc.detail
    return result


@router.post("/{session_id}/start")
async def start_voice(session_id: str, request: StartVoiceRequest):
    """Start after the client agrees to intake, or recover the pending question."""
    sarvam.language_code(request.language)
    runtime, current = _require_session(session_id)
    async with _turn_locks.setdefault(session_id, asyncio.Lock()):
        config = runtime._graph_config(session_id)
        current = runtime._get_current_state(session_id)
        if not current:
            metadata = runtime.active_sessions[session_id]
            initial = runtime._initial_state(
                session_id, request.language.split("-")[0],
                metadata.get("lawyer_name"), metadata.get("lawyer_contact"),
            )
            initial["messages"] = [HumanMessage(content="[Client agreed to voice intake. Begin the interview.]")]
            initial["lawyer_id"] = metadata.get("lawyer_id")
            await runtime.intake_graph.ainvoke(initial, config=config)
        snapshot = runtime.intake_graph.get_state(config)
        if snapshot.next and not _pending_prompt(snapshot):
            try:
                await runtime.intake_graph.ainvoke(None, config=config)
            except Exception:
                logger.exception("Saved intake response retry failed")
                return JSONResponse({"detail": "Your answer is saved but could not be processed. Retry the saved answer.", "requires_retry": True}, status_code=503)
            snapshot = runtime.intake_graph.get_state(config)
        await runtime.broadcast(session_id, {"event": "intake_started", "session_id": session_id})
        return await _reply(snapshot, request.language)


@router.post("/{session_id}/turn")
async def voice_turn(
    session_id: str,
    audio: Optional[UploadFile] = File(default=None),
    language: str = Form(default="hi"),
    text: Optional[str] = Form(default=None),
):
    """Transcribe one browser recording and resume exactly one graph interview turn."""
    sarvam.language_code(language)
    runtime, current = _require_session(session_id)
    if not current:
        raise HTTPException(status_code=409, detail="Start the call before sending a response")
    lock = _turn_locks.setdefault(session_id, asyncio.Lock())
    if lock.locked():
        raise HTTPException(status_code=409, detail="The previous response is still being processed")
    async with lock:
        transcript = (text or "").strip()
        if audio is not None:
            data = await audio.read(sarvam.MAX_AUDIO_BYTES + 1)
            result = await sarvam.transcribe(
                data, audio.filename or "response.webm",
                audio.content_type or "audio/webm", language,
            )
            transcript = result["transcript"]
        if not transcript:
            raise HTTPException(status_code=422, detail="No speech was detected. Please try again.")
        if len(transcript) > 20000:
            raise HTTPException(status_code=422, detail="Response is too long. Please send a shorter answer.")
        config = runtime._graph_config(session_id)
        snapshot = runtime.intake_graph.get_state(config)
        if not _pending_prompt(snapshot):
            raise HTTPException(status_code=409, detail="This interview is complete and ready for lawyer review")
        await runtime.broadcast(session_id, {"event": "voice_transcribed", "transcript": transcript})
        try:
            await runtime.intake_graph.ainvoke(Command(resume=transcript), config=config)
        except Exception:
            logger.exception("Intake answer processing failed")
            return JSONResponse({"detail": "Your answer is saved but could not be processed. Retry the saved answer.", "requires_retry": True}, status_code=503)
        snapshot = runtime.intake_graph.get_state(config)
        state = snapshot.values or {}
        await runtime.broadcast(session_id, {
            "event": "response_processed",
            "interview_stage": state.get("interview_stage"),
            "state": runtime._serialize_state(state),
        })
        return await _reply(snapshot, language, transcript)


@router.post("/{session_id}/retry")
async def retry_voice(session_id: str, request: StartVoiceRequest):
    runtime, _ = _require_session(session_id)
    async with _turn_locks.setdefault(session_id, asyncio.Lock()):
        config = runtime._graph_config(session_id)
        snapshot = runtime.intake_graph.get_state(config)
        if snapshot.next and not _pending_prompt(snapshot):
            try:
                await runtime.intake_graph.ainvoke(None, config=config)
            except Exception:
                logger.exception("Saved intake response retry failed")
                return JSONResponse({"detail": "The analysis service is still busy. Retry this saved answer shortly.", "requires_retry": True}, status_code=503)
            snapshot = runtime.intake_graph.get_state(config)
        return await _reply(snapshot, request.language)


@router.post("/transcribe")
async def transcribe_audio(audio: UploadFile = File(...), language: str = Form(default="hi")):
    data = await audio.read(sarvam.MAX_AUDIO_BYTES + 1)
    return await sarvam.transcribe(data, audio.filename or "response.webm", audio.content_type or "audio/webm", language)


@router.post("/synthesize")
async def synthesize_audio(request: SynthesisRequest):
    audio = await sarvam.synthesize(request.text, request.language)
    return Response(audio, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})


@router.post("/synthesize/stream")
async def synthesize_audio_stream(request: SynthesisRequest):
    # Fetch the first provider chunk before committing response headers so an
    # authentication or validation error can still return an HTTP error status.
    stream = sarvam.stream_speech(request.text, request.language)
    first = await anext(stream, None)
    if not first:
        raise HTTPException(status_code=502, detail="Speech service returned empty audio")

    async def body():
        try:
            yield first
            async for chunk in stream:
                yield chunk
        finally:
            await stream.aclose()

    return StreamingResponse(body(), media_type="audio/mpeg", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
