from pydantic import BaseModel, Field
from datetime import datetime, UTC
from typing import List, Optional
from enum import Enum
import uuid
from app.domain.models.event import PlanEvent, AgentEvent
from app.domain.models.plan import Plan
from app.domain.models.file import FileInfo


class SessionStatus(str, Enum):
    """Session status enum"""
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"


class TaskMode(str, Enum):
    """Manus-style task mode: agent (plan-act) vs chat (lightweight Q&A)"""
    AGENT = "agent"
    CHAT = "chat"


class EngineKind(str, Enum):
    """Dong co chay phien: `plan_act` (LangChain, mac dinh — khong doi hanh
    vi cu) hoac mot CLI engine lam "nao" (`agy`, `claude_code`) — xem
    docs/design/dot-2-cli-engine.md muc 4."""
    PLAN_ACT = "plan_act"
    AGY = "agy"
    CLAUDE_CODE = "claude_code"


class SessionSummary(BaseModel):
    """Lightweight session model for list views (excludes heavy events/files)"""
    id: str
    user_id: str
    title: Optional[str] = None
    unread_message_count: int = 0
    latest_message: Optional[str] = None
    latest_message_at: Optional[datetime] = None
    status: SessionStatus = SessionStatus.PENDING
    is_shared: bool = False
    is_favorite: bool = False
    is_pinned: bool = False
    project_id: Optional[str] = None
    task_mode: TaskMode = TaskMode.AGENT
    engine: EngineKind = EngineKind.PLAN_ACT


class Session(BaseModel):
    """Session model"""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    user_id: str  # User ID that owns this session
    sandbox_id: Optional[str] = Field(default=None)  # Identifier for the sandbox environment
    agent_id: str
    task_id: Optional[str] = None
    title: Optional[str] = None
    unread_message_count: int = 0
    latest_message: Optional[str] = None
    latest_message_at: Optional[datetime] = Field(default_factory=lambda: datetime.now(UTC))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    events: List[AgentEvent] = []
    files: List[FileInfo] = []
    status: SessionStatus = SessionStatus.PENDING
    is_shared: bool = False  # Whether this session is shared publicly
    is_favorite: bool = False
    is_pinned: bool = False
    project_id: Optional[str] = None
    task_mode: TaskMode = TaskMode.AGENT
    # CLI engine (agy/Claude Code) — docs/design/dot-2-cli-engine.md muc 4.
    engine: EngineKind = EngineKind.PLAN_ACT
    conversation_ref: Optional[str] = None  # id hoi thoai CLI (de --conversation/--resume)
    engine_last_seq: int = 0  # con tro phat lai /engine/events (sandbox)

    def get_last_plan(self) -> Optional[Plan]:
        """Get the last plan from the events"""
        for event in reversed(self.events):
            if isinstance(event, PlanEvent):
                return event.plan
        return None
