"""
Adapter `agy` (Antigravity CLI) cho hop dong `Engine` (domain/external/engine.py).
Dich NDJSON thuc te cua agy (da do, docs/spec/01-dong-co-cli.md muc 3) sang
`EngineEvent` chuan hoa.

`_ProcessEngineBase` la "vo" chung cho moi dong co chay nhu tien trinh dai
trong sandbox (agy, Claude Code — xem claude_code_engine.py): logic
start/send/events/stop goi xuong `Sandbox.engine_*` giong nhau, chi khac
cach dung argv/dong stdin/cach dich NDJSON — 3 diem do la 3 hook
`_build_argv` / `_build_user_line` / `_translate` ma lop con phai cai dat.

**So thu tu do backend cap, KHONG dung timestamp** (xem thiet ke muc 3.1):
`seq` cua sandbox (tu /engine/events) la nguon duy nhat quyet dinh thu tu —
khong co nguon thu hai nao can tron theo timestamp o day.
"""
import json
import logging
import re
from collections import deque
from typing import Any, AsyncIterator, Deque, List, Optional, Tuple

from app.domain.external.engine import (
    Engine,
    EngineContext,
    EngineErrorCode,
    EngineEvent,
)
from app.domain.external.sandbox import Sandbox

logger = logging.getLogger(__name__)

# Nhan dien tool MCP cua harness (sandbox/mcp/server.py, FastMCP "gen-agents-sandbox",
# dang ky duoi khoa "sandbox" — spec 02 muc 5). CHUA DO duoc agy dat tien to
# gi thuc su khi hien thi tool_name trong NDJSON cua no ⇒ viet khoan dung,
# do thuc khi nghiem thu (#1b, docs/design/dot-2-cli-engine.md muc 8).
_MCP_PREFIX = re.compile(r"^(?:mcp__)?(?:gen-agents-)?sandbox(?:__|[.:/])")
_PROGRESS_TOOLS = {"plan_update", "message_ask_user", "message_notify_user"}
_STDERR_TAIL_MAXLEN = 50


def strip_mcp_prefix(tool_name: Optional[str]) -> str:
    """Bo tien to MCP cua harness neu co; tra ve ten khong doi neu khong co
    tien to nao khop (cho phep agy in ten "tran" khong tien to)."""
    name = tool_name or ""
    match = _MCP_PREFIX.match(name)
    return name[match.end():] if match else name


def classify_error(text: Optional[str]) -> EngineErrorCode:
    """Phan loai loi theo noi dung (result.error hoac stderr_tail). Mau thuc
    te: docs/evidence/dot-1/agy-p-auth-failed.txt ("authentication failed or
    timed out") phai ra `chua_dang_nhap`, khong phai `timeout` — vi vay kiem
    tra dang nhap TRUOC timeout."""
    t = (text or "").lower()
    if "authentication" in t or "not logged in" in t or "login" in t:
        return "chua_dang_nhap"
    if "quota" in t or "rate limit" in t or "resource_exhausted" in t:
        return "het_quota"
    if "timeout" in t:
        return "timeout"
    return "khac"


def _tool_call_id(step_update: dict, tool_name: str) -> str:
    tool_info = step_update.get("tool_info") or {}
    tool_id = tool_info.get("id")
    if tool_id:
        return str(tool_id)
    return f"{step_update.get('step_index', '?')}:{tool_name}"


class _ProcessEngineBase(Engine):
    """Vo chung: khoi chay/ghi/doc tien trinh CLI engine qua Sandbox.engine_*.
    Lop con cai dat `_build_argv`, `_build_user_line`, `_translate`."""

    #: Ten dong co dung trong EngineEvent(kind="init", engine=...)
    engine_name: str = "process"

    def __init__(self, sandbox: Sandbox, binary: str = ""):
        self._sandbox = sandbox
        self._binary = binary
        self._engine_id: Optional[str] = None
        self._ctx: Optional[EngineContext] = None
        self._conversation_ref: Optional[str] = None
        self._alive = False
        self._stderr_tail: Deque[str] = deque(maxlen=_STDERR_TAIL_MAXLEN)

    # -- hooks lop con phai cai dat --------------------------------------
    def _build_argv(self, ctx: EngineContext) -> List[str]:
        raise NotImplementedError

    def _build_user_line(self, text: str, attachments: Optional[List[str]]) -> str:
        raise NotImplementedError

    def _translate(self, parsed: dict) -> List[EngineEvent]:
        raise NotImplementedError

    # -- Engine protocol --------------------------------------------------
    async def start(self, ctx: EngineContext) -> None:
        self._ctx = ctx
        self._engine_id = ctx.session_id
        self._conversation_ref = ctx.conversation_ref
        argv = self._build_argv(ctx)
        env = {"HOME": ctx.home, "NO_COLOR": "1", "TERM": "dumb"}
        result = await self._sandbox.engine_start(
            engine_id=self._engine_id, argv=argv, env=env, cwd=ctx.cwd
        )
        if not result.success:
            raise RuntimeError(f"Khong khoi chay duoc engine: {result.message}")
        data = result.data or {}
        self._alive = bool(data.get("alive", True))
        logger.info(
            "engine %s khoi chay (reused=%s, pid=%s)",
            self._engine_id, data.get("reused"), data.get("pid"),
        )

    async def send(self, text: str, attachments: Optional[List[str]] = None) -> None:
        if not self._engine_id:
            raise RuntimeError("Engine chua start()")
        line = self._build_user_line(text, attachments)
        result = await self._sandbox.engine_send(self._engine_id, line)
        if not result.success:
            raise RuntimeError(f"Khong ghi duoc stdin engine: {result.message}")

    async def events(self, from_seq: int = 0) -> AsyncIterator[Tuple[int, EngineEvent]]:
        if not self._engine_id:
            raise RuntimeError("Engine chua start()")
        async for item in self._sandbox.engine_events(self._engine_id, from_seq=from_seq):
            seq = item.get("seq", 0)
            stream = item.get("stream", "stdout")
            raw_line = item.get("line", "")
            if stream == "stderr":
                self._stderr_tail.append(raw_line)
                continue
            try:
                parsed = json.loads(raw_line)
            except (ValueError, TypeError):
                self._stderr_tail.append(raw_line)
                continue
            for event in self._translate(parsed):
                if event.kind == "init" and event.conversation_ref:
                    self._conversation_ref = event.conversation_ref
                if event.kind == "done":
                    self._alive = True  # luot xong, tien trinh van song (co the hoi tiep)
                if event.kind == "error":
                    # Khong tu suy ra alive=False o day — /engine/status moi
                    # la nguon su thuc, CliEngineFlow tu goi khi can.
                    pass
                yield seq, event

    async def stop(self) -> None:
        if not self._engine_id:
            return
        await self._sandbox.engine_stop(self._engine_id)
        self._alive = False

    async def destroy(self) -> None:
        # Dot 2: khong thu hoi/xoa HOME tam (HOME dev song qua restart theo
        # thiet ke muc 6) — dot 3 moi lam day du vong doi destroy().
        pass

    @property
    def conversation_ref(self) -> Optional[str]:
        return self._conversation_ref

    @property
    def alive(self) -> bool:
        return self._alive

    @property
    def stderr_tail(self) -> List[str]:
        """Vai dong stderr/khong-parse-duoc gan nhat — dung de phan loai loi
        khi CLI chet ma khong kip in `result` (vd watchdog tien_trinh_chet)."""
        return list(self._stderr_tail)


class AgyEngine(_ProcessEngineBase):
    """Adapter agy — lenh va bang dich NDJSON theo docs/spec/01-dong-co-cli.md
    muc 3 (da do thuc voi agy v1.3.2)."""

    engine_name = "agy"

    def __init__(self, sandbox: Sandbox, binary: str = "agy"):
        super().__init__(sandbox, binary=binary or "agy")

    def _build_argv(self, ctx: EngineContext) -> List[str]:
        argv = [
            self._binary,
            "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--model", ctx.model or "",
            "--effort", ctx.effort or "medium",
            "--dangerously-skip-permissions",
            "--print-timeout", "0",
        ]
        if ctx.conversation_ref:
            argv += ["--conversation", ctx.conversation_ref]
        return argv

    def _build_user_line(self, text: str, attachments: Optional[List[str]]) -> str:
        content_text = text
        for path in attachments or []:
            name = path.rsplit("/", 1)[-1]
            content_text += f"\n\nTệp đã tải lên: /home/ubuntu/upload/{name}"
        payload = {
            "event": "user",
            "message": {"content": [{"type": "text", "text": content_text}]},
        }
        return json.dumps(payload, ensure_ascii=False)

    def _translate(self, parsed: dict) -> List[EngineEvent]:
        kind = parsed.get("event")
        if kind == "init":
            init = parsed.get("init") or {}
            return [
                EngineEvent(
                    kind="init",
                    raw=parsed,
                    engine="agy",
                    model=init.get("model"),
                    tools=list(init.get("tools") or []),
                    conversation_ref=parsed.get("conversation_id") or None,
                )
            ]

        if kind == "step_update":
            return self._translate_step_update(parsed)

        if kind == "result":
            return self._translate_result(parsed)

        return []

    def _translate_step_update(self, parsed: dict) -> List[EngineEvent]:
        su = parsed.get("step_update") or {}
        step_type = su.get("step_type")
        state = su.get("state")
        events: List[EngineEvent] = []

        if step_type == "agent_response" and su.get("text_delta"):
            events.append(EngineEvent(kind="text_delta", raw=parsed, text=su["text_delta"]))

        if step_type == "tool":
            tool_info = su.get("tool_info") or {}
            tool_name = su.get("tool_name") or tool_info.get("name") or ""
            progress_name = strip_mcp_prefix(tool_name)
            tool_call_id = _tool_call_id(su, tool_name)

            if progress_name in _PROGRESS_TOOLS:
                if state == "ACTIVE":
                    params = tool_info.get("parameters") or {}
                    if progress_name == "plan_update":
                        events.append(EngineEvent(
                            kind="plan", raw=parsed,
                            steps=list(params.get("steps") or []),
                            reflection=params.get("reflection") or "",
                        ))
                    elif progress_name == "message_ask_user":
                        events.append(EngineEvent(kind="ask_user", raw=parsed, text=params.get("text") or ""))
                    elif progress_name == "message_notify_user":
                        events.append(EngineEvent(kind="notify", raw=parsed, text=params.get("text") or ""))
                # DONE cua 3 tool nay: bo (khong phat tool_result), tranh
                # ToolEvent rac tren UI — xem docs/design muc 2.1.
            else:
                if state == "ACTIVE":
                    events.append(EngineEvent(
                        kind="tool_call", raw=parsed,
                        tool_call_id=tool_call_id, tool_name=tool_name,
                        tool_args=tool_info.get("parameters") or {},
                    ))
                elif state == "DONE":
                    events.append(EngineEvent(
                        kind="tool_result", raw=parsed,
                        tool_call_id=tool_call_id, tool_name=tool_name,
                        tool_output=tool_info.get("output"),
                    ))

        if state == "DONE" and su.get("usage"):
            events.append(EngineEvent(kind="usage", raw=parsed, usage=su["usage"]))

        return events

    def _translate_result(self, parsed: dict) -> List[EngineEvent]:
        result = parsed.get("result") or {}
        status = result.get("status")
        if status == "SUCCESS":
            events = []
            if result.get("usage"):
                events.append(EngineEvent(kind="usage", raw=parsed, usage=result["usage"]))
            events.append(EngineEvent(kind="done", raw=parsed, status="SUCCESS", text=result.get("response")))
            return events
        error_text = result.get("error") or "Unknown error"
        return [EngineEvent(kind="error", raw=parsed, code=classify_error(error_text), text=error_text)]
