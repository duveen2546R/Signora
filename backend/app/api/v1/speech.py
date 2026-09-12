"""Bounded localhost speech socket. CORS middleware does not protect WebSockets."""
from __future__ import annotations

import asyncio
import json
import struct
import threading

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel, Field, ValidationError

from app.core.config import settings
from app.core.db import SessionLocal
from app.services.streaming_speech import SpeechSession, engine
from app.services.live_translate_service import _aliases
from app.services.live_motion_service import canonical_clips, library_version
from app.services.translate_service import load_registry
from app.api.v1.live import LiveTranslateRequest, LiveCloseRequest, live_translate, live_close

router = APIRouter(tags=["live"])
active_session = threading.Lock()


class Start(BaseModel):
    type: str
    streamId: str = Field(min_length=1, max_length=100)
    generation: int = Field(ge=0)
    libraryVersion: str = Field(min_length=1, max_length=64)


@router.post("/live/warm")
async def warm():
    state = await asyncio.to_thread(engine.warm)
    from app.services.streaming_library import warm as warm_motion
    def prepare_motion():
        with SessionLocal() as db:
            return warm_motion(db)
    try:
        state["motion"] = await asyncio.to_thread(prepare_motion)
    except ValueError as exc:
        state["motion"] = {"warm": False, "error": str(exc)}
    return state


def session_forms(version):
    with SessionLocal() as db:
        if library_version(db) != version:
            raise ValueError("Library changed. Refresh readiness and restart from neutral.")
        clips = {clip.gloss.name: clip for clip in canonical_clips(db)}
        return [form for form, _ in _aliases(load_registry(), clips)]


def plan_message(kind, body):
    with SessionLocal() as db:
        if kind == "translate":
            result = live_translate(LiveTranslateRequest.model_validate(body), db)
        else:
            result = live_close(LiveCloseRequest.model_validate(body), db)
        if result.get("motion"):
            from app.services.live_payload_cache import put
            result["motionReference"] = put(result.pop("motion"))
        return result


@router.get("/live/motion/{key}")
def motion(key: str):
    from app.services.live_payload_cache import get
    payload = get(key) if len(key) == 64 else None
    if payload is None:
        raise HTTPException(404, "Live motion reference expired; request the same plan again")
    return Response(payload, media_type="application/json", headers={"Cache-Control": "private, max-age=3600", "ETag": f'"{key}"'})


@router.websocket("/live/session")
async def session(ws: WebSocket):
    if ws.headers.get("origin") not in settings.cors_origins:
        await ws.close(code=1008, reason="Origin not allowed")
        return
    if not active_session.acquire(blocking=False):
        await ws.close(code=1013, reason="Another microphone session is active")
        return
    try:
        await ws.accept()
        raw = await asyncio.wait_for(ws.receive_text(), timeout=10)
        if len(raw) > 2048:
            raise ValueError("Start message too large")
        start = Start.model_validate_json(raw)
        if start.type != "start":
            raise ValueError("Expected start message")
        if not engine.status()["warm"]:
            raise ValueError("Warm the local speech model before listening")
        forms = await asyncio.to_thread(session_forms, start.libraryVersion)
        decoder = SpeechSession(engine.recognizer, forms)
        expected = 0
        finished = False

        async def send(event):
            await ws.send_json({**event, "streamId": start.streamId, "generation": start.generation})

        await send({"type": "ready", "speech": engine.status()})
        while True:
            message = await asyncio.wait_for(ws.receive(), timeout=45)
            if message["type"] == "websocket.disconnect":
                break
            packet = message.get("bytes")
            if packet is not None:
                if finished or len(packet) != 652:
                    raise ValueError("Expected 20 ms PCM16 packet with 12-byte header")
                sequence, offset = struct.unpack("<Id", packet[:12])
                if sequence != expected or offset != decoder.samples:
                    raise ValueError("Audio discontinuity; restart the microphone")
                expected += 1
                for event in await asyncio.to_thread(decoder.accept, packet[12:]):
                    await send(event)
                continue
            text = message.get("text", "")
            if len(text) > 8192:
                raise ValueError("Control message too large")
            control = json.loads(text)
            kind = control.get("type")
            if kind == "clear":
                break
            if kind == "stop" and not finished:
                finished = True
                for event in await asyncio.to_thread(decoder.accept, b"", True):
                    await send(event)
                await send({"type": "stopped"})
            elif kind in {"translate", "close"}:
                body = control.get("body", {})
                if body.get("streamId") != start.streamId:
                    raise ValueError("Stream identity mismatch")
                try:
                    result = await asyncio.to_thread(plan_message, kind, body)
                    await send({"type": "response", "requestId": control.get("requestId"), "value": result})
                except (HTTPException, ValidationError, ValueError) as exc:
                    await send({"type": "response", "requestId": control.get("requestId"),
                                "error": str(getattr(exc, "detail", exc)),
                                "status": getattr(exc, "status_code", 422)})
            elif kind == "ping":
                await send({"type": "pong"})
            elif kind == "applied":
                # Acknowledgements carry timing only; neither audio nor transcripts are logged.
                pass
            elif kind != "stop":
                raise ValueError("Unknown control message")
    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    except (ValueError, RuntimeError) as exc:
        try:
            await ws.send_json({"type": "error", "message": str(exc)})
        except (RuntimeError, WebSocketDisconnect):
            pass
    finally:
        active_session.release()
        try:
            await ws.close()
        except (RuntimeError, WebSocketDisconnect):
            pass
