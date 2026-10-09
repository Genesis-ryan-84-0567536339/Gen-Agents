"""
Hop dong `Engine`/`EngineEvent`/`EngineContext` — bo chuyen dong co CLI (agy,
Claude Code) lam "nao" cua agent, chay song song voi `PlanActFlow`
(docs/spec/01-dong-co-cli.md, docs/design/dot-2-cli-engine.md muc 2).

LECH SO VOI SPEC 01 §2 (co chu y, ghi lai o day):
- `events()` nhan `from_seq` va yield `(seq, EngineEvent)` thay vi chi
  `AsyncIterator[EngineEvent]` — can de `CliEngineFlow` noi lai dung cho sau
  khi phien di qua `WAITING` (Task moi, ket noi SSE moi, xem thiet ke muc 3).
- `conversation_ref` va `alive` la property thay vi field co dinh tren
  EngineContext — doc tu trang thai song cua engine, khong phai cau hinh
  tinh.

Dung `@dataclass(slots=True)` cho `EngineEvent`/`EngineContext` chu khong
pydantic: `EngineEvent` KHONG di qua bien serialize (duoc dich sang
`AgentEvent` ngay trong flow) nen khong can validate chay-thoi, tranh phi
pydantic moi dong NDJSON (xem thiet ke muc 2).
"""
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal, Optional, Protocol, Tuple

EngineEventKind = Literal[
    "init",
    "text_delta",
    "tool_call",
    "tool_result",
    "plan",
    "ask_user",
    "notify",
    "usage",
    "done",
    "error",
]

# Ma loi chuan hoa — dung chung cho moi adapter engine, dich sang cau tieng
# Viet o CliEngineFlow (thiet ke muc 3.4).
EngineErrorCode = Literal["chua_dang_nhap", "het_quota", "timeout", "tien_trinh_chet", "khac"]


@dataclass(slots=True)
class EngineEvent:
    """Mot su kien da chuan hoa tu NDJSON cua CLI engine (khong phu thuoc CLI
    cu the nao). `raw` giu dong NDJSON goc (dict) de luu Mongo (muc 5)."""

    kind: EngineEventKind
    raw: dict
    # init
    engine: Optional[str] = None
    model: Optional[str] = None
    tools: list[str] = field(default_factory=list)
    conversation_ref: Optional[str] = None
    # text_delta | notify | ask_user
    text: Optional[str] = None
    # tool_call | tool_result
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    tool_args: dict = field(default_factory=dict)
    tool_output: Any = None
    # plan
    steps: list[dict] = field(default_factory=list)
    reflection: Optional[str] = None
    # usage
    usage: Optional[dict] = None
    # done
    status: Optional[str] = None
    # error
    code: Optional[EngineErrorCode] = None


@dataclass(slots=True)
class EngineContext:
    """Thong tin can de khoi chay mot tien trinh CLI engine trong sandbox."""

    session_id: str
    tenant_id: Optional[str] = None
    cwd: str = "/home/ubuntu"
    home: str = "/home/ubuntu"
    model: Optional[str] = None
    effort: str = "medium"
    conversation_ref: Optional[str] = None
    mcp_endpoint: str = "http://127.0.0.1:8081/mcp"
    rendered_files: dict[str, str] = field(default_factory=dict)  # dot 3


class Engine(Protocol):
    """Giao dien mot dong co CLI (agy, Claude Code...). Moi phuong thuc goi
    xuong sandbox qua `Sandbox.engine_*` (xem domain/external/sandbox.py)."""

    async def start(self, ctx: EngineContext) -> None:
        """Dung HOME tam, khoi chay (hoac noi lai) tien trinh CLI trong sandbox."""
        ...

    async def send(self, text: str, attachments: Optional[list[str]] = None) -> None:
        """Mot luot nguoi dung -> mot dong NDJSON vao stdin cua tien trinh."""
        ...

    def events(self, from_seq: int = 0) -> AsyncIterator[Tuple[int, EngineEvent]]:
        """Luong (seq, EngineEvent) da chuan hoa, phat lai tu `from_seq+1`."""
        ...

    async def stop(self) -> None:
        """Dung tien trinh (terminate/kill), giu HOME de noi lai sau."""
        ...

    async def destroy(self) -> None:
        """Thu hoi du lieu CLI tu ghi, xoa HOME tam (dot 3 — dot 2 la no-op)."""
        ...

    @property
    def conversation_ref(self) -> Optional[str]:
        """Id hoi thoai cua CLI (dung de `--conversation`/`--resume`)."""
        ...

    @property
    def alive(self) -> bool:
        """Tien trinh CLI con song trong sandbox hay khong."""
        ...
