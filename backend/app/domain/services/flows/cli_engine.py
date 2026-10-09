"""
`CliEngineFlow` — chay mot CLI engine (agy, Claude Code) nhu "nao" cua agent,
chay song song voi `PlanActFlow` (khong thay the). Khong goi LLM: chi khoi
chay tien trinh CLI trong sandbox, bom tin nguoi dung vao stdin, doc NDJSON
tu stdout (qua `Engine.events()`), dich sang `AgentEvent` da co va day ra
hang doi giong flow cu — xem docs/design/dot-2-cli-engine.md muc 3 va
docs/spec/01-dong-co-cli.md.

**So thu tu**: `seq` do SANDBOX cap (tang don dieu theo DONG NDJSON tho, xem
`Engine.events()`) la nguon DUY NHAT quyet dinh thu tu doc lai/noi lai.
Khong co nguon su kien thu hai nao can tron theo timestamp o flow nay (khac
voi phuong an (A) cua spec 02 muc 7 — xem docs/design muc 1.5: ca 3 tool
tien do/hoi nguoi dung deu da nam san trong chinh NDJSON cua CLI). Thu tu
`AgentEvent` tren Redis stream dau ra la mot bo dem KHAC, do
`agent_task_runner.py` gan sau khi flow yield — khong lien quan den `seq`
noi tren.

May trang thai: IDLE -start+send-> RUNNING -ask_user-> WAITING
-(luot sau: send)-> RUNNING; RUNNING -done-> COMPLETED;
RUNNING|WAITING -error/chet-> ERROR.
"""
import logging
import time
from asyncio import TimeoutError as AsyncTimeoutError
from asyncio import wait_for
from typing import AsyncGenerator, List, Optional

from app.domain.external.engine import Engine, EngineContext, EngineErrorCode, EngineEvent, strip_mcp_prefix
from app.domain.external.sandbox import Sandbox
from app.domain.models.event import (
    BaseEvent,
    DoneEvent,
    ErrorEvent,
    MessageEvent,
    PlanEvent,
    PlanStatus,
    StepEvent,
    StepStatus,
    TitleEvent,
    ToolEvent,
    ToolStatus,
    WaitEvent,
)
from app.domain.models.message import Message
from app.domain.models.plan import ExecutionStatus, Plan, Step
from app.domain.models.session import SessionStatus
from app.domain.models.tool_result import ToolResult
from app.domain.repositories.session_repository import SessionRepository
from app.domain.services.flows.base import BaseFlow

logger = logging.getLogger(__name__)

# Gom text_delta thanh 1 MessageEvent; flush som neu buf vuot nguong nay
# (tranh giu mot MessageEvent khong lo trong bo nho — thiet ke muc 3.1).
_TEXT_BUF_FLUSH_BYTES = 32 * 1024

_STEP_STATUS_MAP = {
    "pending": ExecutionStatus.PENDING,
    "running": ExecutionStatus.RUNNING,
    "in_progress": ExecutionStatus.RUNNING,
    "completed": ExecutionStatus.COMPLETED,
    "failed": ExecutionStatus.FAILED,
}

# Cau tieng Viet de hieu cho tung ma loi (thiet ke muc 3.4). KHONG tu xoay
# sang tai khoan khac — luat cung 00-tong-quan.md §7.3.
_ERROR_MESSAGES = {
    "chua_dang_nhap": "Phiên đăng nhập của động cơ CLI không còn hiệu lực. Cần đăng nhập lại.",
    "het_quota": "Tài khoản động cơ CLI đã hết hạn mức. Đổi model hoặc chờ reset.",
    "timeout": "Động cơ CLI quá thời gian cho phép của lượt này.",
    "tien_trinh_chet": "Tiến trình động cơ CLI đã chết trước khi báo kết quả.",
}


def tool_group(tool_name: Optional[str]) -> str:
    """Nhom tool theo tien to (sau khi bo tien to MCP neu co) — khop dung 6
    gia tri `_handle_tool_event` (agent_task_runner.py) biet xu ly:
    shell|file|browser|skill|search|mcp. CLI engine khong dung skill/search
    nen chi con 4 gia tri; moi tool KHONG khop (ke ca tool goc cua CLI nhu
    `run_command`, `view_file`) roi vao `mcp` vi `McpToolContent` la viewer
    tong quat (thiet ke muc 3.2)."""
    stripped = strip_mcp_prefix(tool_name)
    if stripped.startswith("shell_"):
        return "shell"
    if stripped.startswith("file_"):
        return "file"
    if stripped.startswith("browser_"):
        return "browser"
    return "mcp"


def format_error_message(code: Optional[EngineErrorCode], text: Optional[str]) -> str:
    """`ErrorEvent(error="<câu tiếng Việt> (mã: <code>)")` — thiet ke muc 3.1."""
    code = code or "khac"
    if code == "khac":
        trimmed = (text or "").strip()[:300]
        base = f"Động cơ CLI báo lỗi: {trimmed}." if trimmed else "Động cơ CLI báo lỗi không rõ nguyên nhân."
    else:
        base = _ERROR_MESSAGES.get(code, "Động cơ CLI báo lỗi không rõ nguyên nhân.")
    return f"{base} (mã: {code})"


def map_step_status(raw_status: Optional[str]) -> ExecutionStatus:
    return _STEP_STATUS_MAP.get(str(raw_status or "").lower(), ExecutionStatus.PENDING)


class CliEngineFlow(BaseFlow):
    """Flow chay mot CLI engine (agy/Claude Code) thay cho vong lap LLM cua
    `PlanActFlow`. Chu ky `run(message) -> AsyncGenerator[BaseEvent]` +
    `is_done()` giong `PlanActFlow` de `AgentTaskRunner` goi y nguyen."""

    def __init__(
        self,
        agent_id: str,
        session_id: str,
        session_repository: SessionRepository,
        sandbox: Sandbox,
        engine: Engine,
        model: Optional[str] = None,
        effort: str = "medium",
        home: str = "/home/ubuntu",
        cwd: str = "/home/ubuntu",
        idle_timeout: int = 600,
        max_turn_seconds: int = 3600,
        status_ping_interval: int = 60,
    ):
        self._agent_id = agent_id
        self._session_id = session_id
        self._session_repository = session_repository
        self._sandbox = sandbox
        self._engine = engine
        self._model = model
        self._effort = effort
        self._home = home
        self._cwd = cwd
        self._idle_timeout = idle_timeout
        self._max_turn_seconds = max_turn_seconds
        self._status_ping_interval = status_ping_interval

        self._done = False
        self._text_buf = ""
        self._plan: Optional[Plan] = None
        self._pending_title: Optional[str] = None

    def is_done(self) -> bool:
        return self._done

    # ------------------------------------------------------------------
    # Vong doi mot luot
    # ------------------------------------------------------------------

    async def run(self, message: Message) -> AsyncGenerator[BaseEvent, None]:
        self._done = False
        session = await self._session_repository.find_by_id(self._session_id)
        if not session:
            raise ValueError(f"Session {self._session_id} not found")

        resume = session.status == SessionStatus.WAITING
        self._plan = session.get_last_plan() if resume else None

        ctx = EngineContext(
            session_id=self._session_id,
            cwd=self._cwd,
            home=self._home,
            model=self._model,
            effort=self._effort,
            conversation_ref=getattr(session, "conversation_ref", None),
        )
        await self._engine.start(ctx)

        # Tien trinh da chet VA khong co conversation_ref de noi lai: chi can
        # bao khi day la mot luot NOI LAI thuc su (resume=True) — luot dau
        # tien cua mot phien moi cung "chua reused + chua conversation_ref"
        # nhung khong phai mat lich su gi ca, khong nen bao.
        reused = getattr(self._engine, "last_start_reused", True)
        if resume and not reused and not ctx.conversation_ref:
            yield MessageEvent(
                role="assistant",
                message="Động cơ đã khởi chạy lại, lịch sử trước đó không nối được.",
            )

        await self._engine.send(message.message, message.attachments or None)

        last_seq = getattr(session, "engine_last_seq", 0) or 0
        if not getattr(session, "title", None):
            self._pending_title = (message.message or "")[:50]
        else:
            self._pending_title = None

        events_iter = self._engine.events(from_seq=last_seq)
        turn_deadline = time.monotonic() + self._max_turn_seconds
        last_event_at = time.monotonic()
        last_status_ping = time.monotonic()

        try:
            while True:
                now = time.monotonic()
                if now >= turn_deadline:
                    await self._engine.stop()
                    self._done = True
                    yield ErrorEvent(error=format_error_message("timeout", None))
                    return

                if now - last_status_ping >= self._status_ping_interval:
                    await self._ping_sandbox_keepalive()
                    last_status_ping = now

                wait_budget = min(
                    self._status_ping_interval,
                    max(0.05, self._idle_timeout - (now - last_event_at)),
                    max(0.05, turn_deadline - now),
                )
                try:
                    seq, engine_event = await wait_for(events_iter.__anext__(), timeout=wait_budget)
                except AsyncTimeoutError:
                    idle_for = time.monotonic() - last_event_at
                    if idle_for >= self._idle_timeout and not await self._engine_still_alive():
                        self._done = True
                        yield ErrorEvent(error=format_error_message("tien_trinh_chet", None))
                        return
                    continue
                except StopAsyncIteration:
                    self._done = True
                    yield ErrorEvent(error=format_error_message("tien_trinh_chet", None))
                    return

                last_event_at = time.monotonic()
                await self._update_engine_cursor(seq)

                stop_after = False
                for agent_event in await self._translate_engine_event(engine_event):
                    yield agent_event
                    if isinstance(agent_event, TitleEvent):
                        await self._session_repository.update_title(self._session_id, agent_event.title)
                    if isinstance(agent_event, WaitEvent):
                        self._done = False
                        stop_after = True
                        break
                    if isinstance(agent_event, DoneEvent):
                        self._done = True
                        stop_after = True
                        break
                    if isinstance(agent_event, ErrorEvent):
                        self._done = True
                        stop_after = True
                        break
                if stop_after:
                    return
        finally:
            pass

    async def _engine_still_alive(self) -> bool:
        """Kiem tra song/chet THUC SU qua `/engine/status` — khong dung
        `Engine.alive` (gia tri cache cuc bo, chi doi khi chinh engine tu cap
        nhat tu su kien `done`/`start`, khong tu phat hien tien trinh da
        chet neu khong co su kien moi nao den — xem watchdog thiet ke muc 3)."""
        try:
            status = await self._sandbox.engine_status(self._session_id)
            if status.success and status.data:
                return bool(status.data.get("alive", True))
        except Exception:
            logger.warning("Khong kiem tra duoc /engine/status cho session %s", self._session_id, exc_info=True)
        return self._engine.alive

    async def _ping_sandbox_keepalive(self) -> None:
        """Goi /engine/status moi `status_ping_interval` giay — mot ket noi
        SSE dai KHONG tu gia han `SERVICE_TIMEOUT_MINUTES` cua sandbox (chi
        middleware gia han luc NHAN request), nen phai tu goi REST dinh ky de
        container khong tu chet giua nhiem vu (thiet ke muc 1.3)."""
        try:
            await self._sandbox.engine_status(self._session_id)
        except Exception:
            logger.warning("Khong ping duoc /engine/status cho session %s", self._session_id, exc_info=True)

    async def _update_engine_cursor(self, seq: int) -> None:
        try:
            await self._session_repository.update_engine_cursor(self._session_id, seq)
        except AttributeError:
            # Session/SessionRepository thuc chua co truong nay (truoc commit
            # noi day o AgentTaskRunnerFactory) — bo qua, chi anh huong kha
            # nang noi lai chinh xac tuyet doi tung dong, khong anh huong
            # dich su kien cua luot hien tai.
            logger.debug("SessionRepository chua ho tro update_engine_cursor")

    # ------------------------------------------------------------------
    # Dich EngineEvent -> AgentEvent (thiet ke muc 3.1)
    # ------------------------------------------------------------------

    def _flush_text(self, fallback: Optional[str] = None) -> Optional[MessageEvent]:
        text = self._text_buf
        self._text_buf = ""
        if not text:
            text = fallback or ""
        if not text:
            return None
        return MessageEvent(role="assistant", message=text)

    async def _translate_engine_event(self, ev: EngineEvent) -> List[BaseEvent]:
        out: List[BaseEvent] = []

        if ev.kind == "init":
            if self._pending_title:
                out.append(TitleEvent(title=self._pending_title))
                self._pending_title = None
            return out

        if ev.kind == "text_delta":
            self._text_buf += ev.text or ""
            if len(self._text_buf.encode("utf-8", errors="ignore")) > _TEXT_BUF_FLUSH_BYTES:
                flushed = self._flush_text()
                if flushed:
                    out.append(flushed)
            return out

        if ev.kind == "tool_call":
            flushed = self._flush_text()
            if flushed:
                out.append(flushed)
            out.append(ToolEvent(
                tool_call_id=ev.tool_call_id or "",
                tool_name=tool_group(ev.tool_name),
                function_name=ev.tool_name or "",
                function_args=dict(ev.tool_args or {}),
                status=ToolStatus.CALLING,
            ))
            return out

        if ev.kind == "tool_result":
            out.append(ToolEvent(
                tool_call_id=ev.tool_call_id or "",
                tool_name=tool_group(ev.tool_name),
                function_name=ev.tool_name or "",
                function_args={},
                status=ToolStatus.CALLED,
                function_result=ToolResult(success=True, data=ev.tool_output),
            ))
            return out

        if ev.kind == "plan":
            out.extend(self._apply_plan_update(ev.steps, ev.reflection))
            return out

        if ev.kind == "ask_user":
            flushed = self._flush_text()
            if flushed:
                out.append(flushed)
            out.append(MessageEvent(role="assistant", message=ev.text or ""))
            out.append(WaitEvent())
            return out

        if ev.kind == "notify":
            flushed = self._flush_text()
            if flushed:
                out.append(flushed)
            out.append(MessageEvent(role="assistant", message=ev.text or ""))
            return out

        if ev.kind == "usage":
            # Ghi usage vao Mongo la viec cua repo engine_run (thiet ke muc 5);
            # khong phat AgentEvent nao cho nguoi dung thay.
            return out

        if ev.kind == "done":
            flushed = self._flush_text(fallback=ev.text)
            if flushed:
                out.append(flushed)
            if self._plan is not None:
                self._plan.status = ExecutionStatus.COMPLETED
                out.append(PlanEvent(plan=self._plan, status=PlanStatus.COMPLETED))
            out.append(DoneEvent())
            return out

        if ev.kind == "error":
            out.append(ErrorEvent(error=format_error_message(ev.code, ev.text)))
            return out

        logger.warning("CliEngineFlow: khong biet dich EngineEvent.kind=%s", ev.kind)
        return out

    def _apply_plan_update(self, steps_raw: List[dict], reflection: Optional[str]) -> List[BaseEvent]:
        out: List[BaseEvent] = []
        old_by_id = {step.id: step for step in (self._plan.steps if self._plan else [])}
        new_steps: List[Step] = []
        for raw in steps_raw or []:
            step_id = str(raw.get("id"))
            status = map_step_status(raw.get("status"))
            old = old_by_id.get(step_id)
            description = raw.get("description") or (old.description if old else "")
            new_steps.append(Step(id=step_id, description=description, status=status))

        is_first_plan = self._plan is None
        if self._plan is None:
            self._plan = Plan(steps=new_steps)
        else:
            self._plan.steps = new_steps

        for step in new_steps:
            old = old_by_id.get(step.id)
            if old is not None and old.status == step.status:
                continue
            if step.status == ExecutionStatus.RUNNING:
                out.append(StepEvent(step=step, status=StepStatus.STARTED))
            elif step.status == ExecutionStatus.COMPLETED:
                out.append(StepEvent(step=step, status=StepStatus.COMPLETED))
            elif step.status == ExecutionStatus.FAILED:
                out.append(StepEvent(step=step, status=StepStatus.FAILED))

        plan_status = PlanStatus.CREATED if is_first_plan else PlanStatus.UPDATED
        out.insert(0, PlanEvent(plan=self._plan, status=plan_status))
        return out
