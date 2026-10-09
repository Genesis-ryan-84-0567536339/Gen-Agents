"""Shared offline test harness for the agent framework.

Reusable fakes that satisfy the ``domain/external`` Protocols and the
repository interfaces, so flows and agents can be driven entirely offline
(no MongoDB / Redis / sandbox / LLM). Import these instead of redefining
them per test module:

    from tests.harness import (
        FakeAgentRepository, FakeSandbox, FakeSession, FakeSessionRepository,
        ScriptedLLM, StubAgent, build_agent_loop_flow, build_plan_act_flow,
        collect, create_plan_call,
    )

See ``.cursor/skills/harness/SKILL.md`` for the full harness-coding guide
(file map, invariants, extension recipes, testing pyramid).
"""

from typing import Any, AsyncIterator, Dict, List, Optional, Tuple, Union

from app.domain.external.engine import Engine, EngineContext, EngineEvent
from app.domain.models.memory import Memory
from app.domain.models.message import LLMMessage, ToolCall
from app.domain.models.plan import Plan
from app.domain.models.session import SessionStatus
from app.domain.models.tool_result import ToolResult
from app.domain.services.agents.base import BaseAgent
from app.domain.services.flows.agent_loop import AgentLoopFlow
from app.domain.services.flows.cli_engine import CliEngineFlow
from app.domain.services.flows.plan_act import PlanActFlow
from app.domain.services.tools.message import MessageToolkit


class ScriptedLLM:
    """LLM stub that returns scripted assistant messages in order.

    Records every request so tests can assert on what the model saw:

    - ``asked_tool_names``: comma-joined tool names offered per call
    - ``calls``: message list per call
    - ``requests``: full ``{"messages", "tools", "tool_choice"}`` per call
    """

    def __init__(self, responses: List[LLMMessage]) -> None:
        self.responses = list(responses)
        self.asked_tool_names: list[str] = []
        self.calls: list[list[LLMMessage]] = []
        self.requests: list[dict] = []

    async def ask(self, messages, tools=None, response_format=None, tool_choice=None):
        names: list[str] = []
        for tool in tools or []:
            fn = (tool.get("function") or {}) if isinstance(tool, dict) else {}
            name = fn.get("name") or tool.get("name")
            if name:
                names.append(name)
        self.asked_tool_names.append(",".join(names))
        self.calls.append(list(messages))
        self.requests.append({
            "messages": list(messages),
            "tools": tools,
            "tool_choice": tool_choice,
        })
        return self.responses.pop(0)

    async def parse_json(self, text: str):
        raise AssertionError("parse_json must not be used by the agent loop")


class FakeAgentRepository:
    """In-memory AgentRepository keyed by ``agent_id:name``."""

    def __init__(self) -> None:
        self.memories: dict[str, Memory] = {}

    @staticmethod
    def _key(agent_id: str, name: str) -> str:
        return f"{agent_id}:{name}"

    async def get_memory(self, agent_id: str, name: str) -> Memory:
        return self.memories.setdefault(self._key(agent_id, name), Memory())

    async def save_memory(self, agent_id: str, name: str, memory: Memory) -> None:
        self.memories[self._key(agent_id, name)] = memory


class FakeSandbox:
    """Sandbox stub: file ops succeed, shell ops succeed and are counted."""

    def __init__(self) -> None:
        self.shell_exec_calls = 0
        # CLI engine (agy/Claude Code) stubs — Issue #30
        self.engine_start_calls: List[dict] = []
        self.engine_sent_lines: List[str] = []
        self.engine_status_calls = 0
        self.engine_status_response: dict = {"alive": True, "returncode": None, "last_seq": 0, "started_at": 0.0}
        self.engine_stop_calls: List[str] = []

    async def file_write(self, **kwargs: Any) -> ToolResult:
        return ToolResult(success=True, message="written")

    async def file_read(self, **kwargs: Any) -> ToolResult:
        return ToolResult(success=True, message="ok", data="")

    async def file_str_replace(self, **kwargs: Any) -> ToolResult:
        return ToolResult(success=True, message="replaced")

    async def file_find_in_content(self, **kwargs: Any) -> ToolResult:
        return ToolResult(success=True, data=[])

    async def file_find_by_name(self, **kwargs: Any) -> ToolResult:
        return ToolResult(success=True, data=[])

    async def exec_command(self, id: str, exec_dir: str, command: str) -> ToolResult:
        self.shell_exec_calls += 1
        return ToolResult(success=True, message="Command executed", data={})

    async def view_shell(self, id: str, console: bool = False) -> ToolResult:
        return ToolResult(success=True, data={"console": []})

    async def wait_for_process(self, id: str, seconds: int | None = None) -> ToolResult:
        return ToolResult(success=True, data={})

    async def write_to_process(
        self, id: str, input: str, press_enter: bool = True
    ) -> ToolResult:
        return ToolResult(success=True, data={})

    async def kill_process(self, id: str) -> ToolResult:
        return ToolResult(success=True, data={})

    # -- CLI engine (agy/Claude Code) stubs — Issue #30 --------------------

    async def engine_start(self, engine_id: str, argv: List[str], env: dict, cwd: str) -> ToolResult:
        self.engine_start_calls.append({"engine_id": engine_id, "argv": argv, "env": env, "cwd": cwd})
        return ToolResult(success=True, data={"engine_id": engine_id, "pid": 1, "alive": True, "started_at": 0.0, "reused": False})

    async def engine_send(self, engine_id: str, line: str) -> ToolResult:
        self.engine_sent_lines.append(line)
        return ToolResult(success=True, data={"ok": True, "bytes": len(line)})

    async def engine_events(self, engine_id: str, from_seq: int = 0) -> AsyncIterator[dict]:
        return
        yield {}  # pragma: no cover - makes this an async generator; unused by FakeEngine-based tests

    async def engine_status(self, engine_id: str) -> ToolResult:
        self.engine_status_calls += 1
        return ToolResult(success=True, data=self.engine_status_response)

    async def engine_stop(self, engine_id: str, signal: Optional[str] = None) -> ToolResult:
        self.engine_stop_calls.append(engine_id)
        return ToolResult(success=True, data={"ok": True, "returncode": 0})


class FakeSession:
    def __init__(
        self,
        status: SessionStatus = SessionStatus.PENDING,
        plan: Plan | None = None,
        conversation_ref: Optional[str] = None,
        engine_last_seq: int = 0,
        title: Optional[str] = None,
    ) -> None:
        self.status = status
        self.project_id = None
        self.plan = plan
        # CLI engine (agy/Claude Code) fields — Issue #30 (them vao Session
        # that o commit "truong engine tren Session"; FakeSession di truoc
        # vi CliEngineFlow chi can duck-type, khong phu thuoc pydantic model).
        self.conversation_ref = conversation_ref
        self.engine_last_seq = engine_last_seq
        self.title = title

    def get_last_plan(self):
        return self.plan


class FakeSessionRepository:
    """SessionRepository stub: mutates the session and records every update."""

    def __init__(self, session: FakeSession) -> None:
        self.session = session
        self.status_updates: list[SessionStatus] = []
        self.titles: list[str] = []
        self.engine_cursor_updates: list[int] = []
        self.conversation_ref_updates: list[Optional[str]] = []

    async def find_by_id(self, session_id: str):
        return self.session

    async def update_status(self, session_id: str, status: SessionStatus) -> None:
        self.session.status = status
        self.status_updates.append(status)

    async def update_title(self, session_id: str, title: str) -> None:
        self.session.title = title
        self.titles.append(title)

    async def update_engine_cursor(self, session_id: str, seq: int) -> None:
        self.session.engine_last_seq = seq
        self.engine_cursor_updates.append(seq)

    async def update_conversation_ref(self, session_id: str, conversation_ref: Optional[str]) -> None:
        self.session.conversation_ref = conversation_ref
        self.conversation_ref_updates.append(conversation_ref)


class StubAgent(BaseAgent):
    """Minimal concrete BaseAgent for unit-testing the tool loop directly."""

    name = "test"

    def build_system_prompt(self) -> str:
        return "test system prompt"


class FakeEngine:
    """Engine gia lap (Issue #30): phat lai mot danh sach `EngineEvent` da
    soan san qua `events()`, khong goi sandbox/CLI thuc nao. Dich NDJSON cua
    tung CLI cu the (agy) -> EngineEvent da duoc kiem rieng trong
    `test_agy_adapter.py`; FakeEngine cho phep `test_cli_engine_flow.py` kiem
    CliEngineFlow (dich EngineEvent -> AgentEvent + may trang thai) doc lap
    voi adapter CLI nao.

    `scripted` nhan mot trong hai dang:
    - `list[EngineEvent]` — seq tu dong danh tu 1.
    - `list[tuple[int, EngineEvent]]` — tu chon seq (dung khi can mo phong
      nhieu event chia seq, vd usage+done cung mot dong NDJSON goc).
    """

    def __init__(
        self,
        scripted: Union[List[EngineEvent], List[Tuple[int, EngineEvent]]],
        conversation_ref: Optional[str] = None,
        alive_after_events: bool = True,
    ) -> None:
        if scripted and isinstance(scripted[0], tuple):
            self._scripted: List[Tuple[int, EngineEvent]] = list(scripted)  # type: ignore[arg-type]
        else:
            self._scripted = [(i + 1, ev) for i, ev in enumerate(scripted)]  # type: ignore[arg-type]
        self._conversation_ref = conversation_ref
        self._alive = True
        self._alive_after_events = alive_after_events
        self.last_start_reused = True
        self.started_ctx: Optional[EngineContext] = None
        self.sent: List[Tuple[str, Optional[List[str]]]] = []
        self.stopped = False

    async def start(self, ctx: EngineContext) -> None:
        self.started_ctx = ctx
        if ctx.conversation_ref:
            self._conversation_ref = ctx.conversation_ref

    async def send(self, text: str, attachments: Optional[List[str]] = None) -> None:
        self.sent.append((text, attachments))

    async def events(self, from_seq: int = 0) -> AsyncIterator[Tuple[int, EngineEvent]]:
        for seq, ev in self._scripted:
            if seq <= from_seq:
                continue
            if ev.kind == "init" and ev.conversation_ref:
                self._conversation_ref = ev.conversation_ref
            yield seq, ev
        self._alive = self._alive_after_events

    async def stop(self) -> None:
        self.stopped = True
        self._alive = False

    async def destroy(self) -> None:
        pass

    @property
    def conversation_ref(self) -> Optional[str]:
        return self._conversation_ref

    @property
    def alive(self) -> bool:
        return self._alive


def build_cli_engine_flow(
    engine: Engine,
    *,
    session: Optional[FakeSession] = None,
    sandbox: Optional[FakeSandbox] = None,
    session_repository: Optional[FakeSessionRepository] = None,
    model: str = "gemini-3.8-flash-low",
    effort: str = "low",
    idle_timeout: int = 600,
    max_turn_seconds: int = 3600,
    status_ping_interval: int = 60,
) -> CliEngineFlow:
    return CliEngineFlow(
        agent_id="agent-1",
        session_id="session-1",
        session_repository=session_repository or FakeSessionRepository(session or FakeSession()),
        sandbox=sandbox or FakeSandbox(),
        engine=engine,
        model=model,
        effort=effort,
        idle_timeout=idle_timeout,
        max_turn_seconds=max_turn_seconds,
        status_ping_interval=status_ping_interval,
    )


def build_plan_act_flow(
    llm: ScriptedLLM,
    *,
    session: Optional[FakeSession] = None,
    agent_repository: Optional[FakeAgentRepository] = None,
    sandbox: Optional[FakeSandbox] = None,
) -> PlanActFlow:
    return PlanActFlow(
        agent_id="agent-1",
        agent_repository=agent_repository or FakeAgentRepository(),
        session_id="session-1",
        session_repository=FakeSessionRepository(session or FakeSession()),
        sandbox=sandbox or FakeSandbox(),
        browser=object(),
        mcp_tool=MessageToolkit(),
        llm=llm,
    )


def build_agent_loop_flow(
    llm: ScriptedLLM,
    *,
    session: Optional[FakeSession] = None,
    agent_repository: Optional[FakeAgentRepository] = None,
    sandbox: Optional[FakeSandbox] = None,
) -> AgentLoopFlow:
    return AgentLoopFlow(
        agent_id="agent-1",
        agent_repository=agent_repository or FakeAgentRepository(),
        session_id="session-1",
        session_repository=FakeSessionRepository(session or FakeSession()),
        sandbox=sandbox or FakeSandbox(),
        browser=object(),
        mcp_tool=MessageToolkit(),
        llm=llm,
    )


def create_plan_call(
    *,
    call_id: str = "plan-1",
    message: str = "I will do the work.",
    title: str = "Do the work",
    goal: str = "Finish",
    steps: Optional[List[dict]] = None,
) -> ToolCall:
    """Factory for the ``create_plan`` output-tool call Planner scripts start with."""
    return ToolCall(
        id=call_id,
        name="create_plan",
        args={
            "message": message,
            "language": "en",
            "title": title,
            "goal": goal,
            "steps": [{"id": "1", "description": "Do the work"}]
            if steps is None
            else steps,
        },
    )


async def collect(gen) -> list:
    """Drain an async event generator into a list."""
    return [event async for event in gen]
