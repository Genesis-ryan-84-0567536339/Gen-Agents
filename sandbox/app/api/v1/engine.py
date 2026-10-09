import asyncio
import json
import logging

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.core.exceptions import BadRequestException
from app.schemas.engine import (
    EngineSendRequest,
    EngineSendResponse,
    EngineStartRequest,
    EngineStartResponse,
    EngineStatusResponse,
    EngineStopRequest,
    EngineStopResponse,
)
from app.schemas.response import Response
from app.services.engine import engine_service

logger = logging.getLogger(__name__)

router = APIRouter()

# Keepalive SSE comment moi 15s — khong de proxy/sandbox tu dong het timeout
# giua mot ket noi dai (docs/design/dot-2-cli-engine.md muc 1.3).
_SSE_KEEPALIVE_SECONDS = 15


@router.post("/start", response_model=Response)
async def engine_start(request: EngineStartRequest):
    """Khoi chay (hoac noi lai, idempotent) mot tien trinh CLI engine dai."""
    if not request.engine_id:
        raise BadRequestException("engine_id khong duoc rong")
    result = await engine_service.start(
        engine_id=request.engine_id,
        argv=request.argv,
        env=request.env,
        cwd=request.cwd,
    )
    return Response(success=True, message="Engine da khoi chay", data=result)


@router.post("/send", response_model=Response)
async def engine_send(request: EngineSendRequest):
    """Ghi mot dong NDJSON vao stdin cua tien trinh dong co."""
    result = await engine_service.send(request.engine_id, request.line)
    return Response(success=True, message="Da ghi stdin", data=result)


@router.get("/status", response_model=Response)
async def engine_status(engine_id: str):
    result = await engine_service.status(engine_id)
    return Response(success=True, message="Trang thai engine", data=result)


@router.post("/stop", response_model=Response)
async def engine_stop(request: EngineStopRequest):
    result = await engine_service.stop(request.engine_id, request.signal)
    return Response(success=True, message="Da dung engine", data=result)


@router.get("/events")
async def engine_events(engine_id: str, from_seq: int = 0):
    """SSE: phat lai tu `from_seq+1` roi stream tiep. Giu ket noi mo bang
    keepalive ": ping" moi 15s khi khong co dong moi."""

    async def _generate():
        try:
            line_iter = engine_service.events(engine_id, from_seq=from_seq)
            while True:
                try:
                    item = await asyncio.wait_for(line_iter.__anext__(), timeout=_SSE_KEEPALIVE_SECONDS)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                except StopAsyncIteration:
                    break
                payload = {
                    "seq": item.seq,
                    "stream": item.stream,
                    "ts": item.ts,
                    "line": item.line,
                }
                if item.truncated:
                    payload["truncated"] = True
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except Exception:
            logger.exception("engine_events(%s) loi khi stream", engine_id)
            yield f"event: error\ndata: {json.dumps({'message': 'internal error'})}\n\n"

    return StreamingResponse(_generate(), media_type="text/event-stream")
