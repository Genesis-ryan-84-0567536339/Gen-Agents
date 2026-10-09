"""
Schema cho endpoint /api/v1/engine/* (docs/spec/01-dong-co-cli.md, docs/design/
dot-2-cli-engine.md muc 1.3) — chay CLI engine (agy/claude) nhu tien trinh dai
trong may nhiem vu, giu stdin mo, day stdout qua SSE.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class EngineStartRequest(BaseModel):
    """Khoi chay (hoac noi lai) mot tien trinh CLI engine."""
    engine_id: str = Field(..., description="ID dong co, do backend cap = session.id")
    argv: List[str] = Field(..., description="Lenh + cac co, backend dung san")
    env: Dict[str, str] = Field(default_factory=dict, description="Bien moi truong bo sung (HOME, NO_COLOR, TERM...)")
    cwd: str = Field(default="/home/ubuntu", description="Thu muc lam viec")


class EngineStartResponse(BaseModel):
    engine_id: str
    pid: Optional[int] = None
    alive: bool
    started_at: float
    reused: bool = False


class EngineSendRequest(BaseModel):
    """Ghi mot dong vao stdin cua tien trinh dong co."""
    engine_id: str
    line: str = Field(..., description="Mot dong NDJSON (khong can \\n o cuoi)")


class EngineSendResponse(BaseModel):
    ok: bool
    bytes: int = 0


class EngineStatusResponse(BaseModel):
    alive: bool
    returncode: Optional[int] = None
    last_seq: int = 0
    started_at: Optional[float] = None


class EngineStopRequest(BaseModel):
    engine_id: str
    signal: Optional[str] = Field(default=None, description="'TERM' (mac dinh) hoac 'KILL'")


class EngineStopResponse(BaseModel):
    ok: bool
    returncode: Optional[int] = None


class EngineEventLine(BaseModel):
    """Mot dong trong vong dem phat lai (deque) — khong phai EngineEvent da dich,
    chi la (seq, stream, ts, line) tho de backend tu dich."""
    seq: int
    stream: str  # "stdout" | "stderr"
    ts: float
    line: str
    truncated: bool = False
