"""
Test CliEngineFlow (Issue #30): dich EngineEvent -> AgentEvent + may trang
thai, doc lap voi adapter CLI cu the nao (dung FakeEngine — xem harness.py).
Dich NDJSON thuc te cua agy da duoc kiem rieng o test_agy_adapter.py.
"""
from typing import List

import pytest

from app.domain.external.engine import EngineContext, EngineEvent
from app.domain.models.event import (
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
from app.domain.models.session import SessionStatus
from app.domain.services.flows.cli_engine import CliEngineFlow, format_error_message, tool_group

from tests.harness import FakeEngine, FakeSandbox, FakeSession, FakeSessionRepository, build_cli_engine_flow


def _init_ev(conversation_ref: str = "conv-1") -> EngineEvent:
    return EngineEvent(kind="init", raw={}, engine="agy", model="m", conversation_ref=conversation_ref)


async def collect(flow: CliEngineFlow, message: Message) -> List:
    return [event async for event in flow.run(message)]


class TestToolGroupAndErrorFormatting:
    def test_tool_group_shell_file_browser_mcp(self):
        assert tool_group("shell_exec") == "shell"
        assert tool_group("file_write") == "file"
        assert tool_group("browser_navigate") == "browser"
        assert tool_group("run_command") == "mcp"
        assert tool_group("mcp__sandbox__shell_exec") == "shell"

    def test_format_error_message_known_codes(self):
        assert "đăng nhập" in format_error_message("chua_dang_nhap", None)
        assert "(mã: chua_dang_nhap)" in format_error_message("chua_dang_nhap", None)
        assert "hạn mức" in format_error_message("het_quota", None)
        assert "thời gian" in format_error_message("timeout", None)
        assert "đã chết" in format_error_message("tien_trinh_chet", None)

    def test_format_error_message_unknown_code_includes_trimmed_text(self):
        msg = format_error_message("khac", "some raw provider error")
        assert "some raw provider error" in msg
        assert "(mã: khac)" in msg


@pytest.mark.asyncio
class TestInitAndTitle:
    async def test_init_emits_title_when_session_has_no_title(self):
        session = FakeSession(title=None)
        engine = FakeEngine([_init_ev(), EngineEvent(kind="done", raw={}, status="SUCCESS", text="ok")])
        flow = build_cli_engine_flow(engine, session=session)
        events = await collect(flow, Message(message="lam viec X"))
        titles = [e for e in events if isinstance(e, TitleEvent)]
        assert len(titles) == 1
        assert titles[0].title == "lam viec X"
        assert session.title == "lam viec X"

    async def test_init_does_not_emit_title_when_session_already_has_one(self):
        session = FakeSession(title="Da co tieu de")
        engine = FakeEngine([_init_ev(), EngineEvent(kind="done", raw={}, status="SUCCESS", text="ok")])
        flow = build_cli_engine_flow(engine, session=session)
        events = await collect(flow, Message(message="tiep tuc"))
        assert not any(isinstance(e, TitleEvent) for e in events)


@pytest.mark.asyncio
class TestTextDeltaBuffering:
    async def test_text_deltas_are_gommed_into_one_message_event(self):
        engine = FakeEngine([
            _init_ev(),
            EngineEvent(kind="text_delta", raw={}, text="Xin "),
            EngineEvent(kind="text_delta", raw={}, text="chao "),
            EngineEvent(kind="text_delta", raw={}, text="ban."),
            EngineEvent(kind="done", raw={}, status="SUCCESS", text=""),
        ])
        flow = build_cli_engine_flow(engine)
        events = await collect(flow, Message(message="hi"))
        messages = [e for e in events if isinstance(e, MessageEvent)]
        assert len(messages) == 1
        assert messages[0].message == "Xin chao ban."

    async def test_done_with_empty_buffer_uses_result_response_fallback(self):
        engine = FakeEngine([
            _init_ev(),
            EngineEvent(kind="done", raw={}, status="SUCCESS", text="Ket qua cuoi cung"),
        ])
        flow = build_cli_engine_flow(engine)
        events = await collect(flow, Message(message="hi"))
        messages = [e for e in events if isinstance(e, MessageEvent)]
        assert len(messages) == 1
        assert messages[0].message == "Ket qua cuoi cung"


@pytest.mark.asyncio
class TestToolEvents:
    async def test_tool_call_and_result_map_to_tool_event_pair(self):
        engine = FakeEngine([
            _init_ev(),
            EngineEvent(kind="tool_call", raw={}, tool_call_id="k1", tool_name="run_command", tool_args={"CommandLine": "echo hi"}),
            EngineEvent(kind="tool_result", raw={}, tool_call_id="k1", tool_name="run_command", tool_output="hi\n"),
            EngineEvent(kind="done", raw={}, status="SUCCESS", text="ok"),
        ])
        flow = build_cli_engine_flow(engine)
        events = await collect(flow, Message(message="hi"))
        tool_events = [e for e in events if isinstance(e, ToolEvent)]
        assert len(tool_events) == 2
        assert tool_events[0].status == ToolStatus.CALLING
        assert tool_events[0].tool_name == "mcp"
        assert tool_events[0].function_name == "run_command"
        assert tool_events[0].function_args == {"CommandLine": "echo hi"}
        assert tool_events[1].status == ToolStatus.CALLED
        assert tool_events[1].function_result.data == "hi\n"

    async def test_tool_result_carries_forward_call_args_for_file_and_shell(self):
        """_handle_tool_event (agent_task_runner.py) doc function_args cua
        CA CALLED de biet file/shell nao can doc lai (FileToolContent/
        ShellToolContent) — NDJSON cua CLI chi co parameters o dong ACTIVE.
        Phat hien khi chay demo thuc voi fake_agy (bang chung dot 2, #2)."""
        engine = FakeEngine([
            _init_ev(),
            EngineEvent(kind="tool_call", raw={}, tool_call_id="k1", tool_name="file_write", tool_args={"file": "/home/ubuntu/out.md"}),
            EngineEvent(kind="tool_result", raw={}, tool_call_id="k1", tool_name="file_write", tool_output="done"),
            EngineEvent(kind="done", raw={}, status="SUCCESS", text="ok"),
        ])
        flow = build_cli_engine_flow(engine)
        events = await collect(flow, Message(message="hi"))
        tool_events = [e for e in events if isinstance(e, ToolEvent)]
        called = next(e for e in tool_events if e.status == ToolStatus.CALLED)
        assert called.function_args == {"file": "/home/ubuntu/out.md"}

    async def test_shell_tool_mapped_to_shell_group(self):
        engine = FakeEngine([
            _init_ev(),
            EngineEvent(kind="tool_call", raw={}, tool_call_id="k1", tool_name="shell_exec", tool_args={"id": "s1", "command": "ls"}),
            EngineEvent(kind="done", raw={}, status="SUCCESS", text="ok"),
        ])
        flow = build_cli_engine_flow(engine)
        events = await collect(flow, Message(message="hi"))
        tool_events = [e for e in events if isinstance(e, ToolEvent)]
        assert tool_events[0].tool_name == "shell"


@pytest.mark.asyncio
class TestPlanEvents:
    async def test_first_plan_update_emits_created_then_step_started(self):
        engine = FakeEngine([
            _init_ev(),
            EngineEvent(kind="plan", raw={}, steps=[{"id": "1", "status": "running", "description": "Buoc 1"}], reflection=""),
            EngineEvent(kind="done", raw={}, status="SUCCESS", text="ok"),
        ])
        flow = build_cli_engine_flow(engine)
        events = await collect(flow, Message(message="hi"))
        plan_events = [e for e in events if isinstance(e, PlanEvent)]
        step_events = [e for e in events if isinstance(e, StepEvent)]
        assert any(p.status == PlanStatus.CREATED for p in plan_events)
        assert any(s.status == StepStatus.STARTED for s in step_events)

    async def test_second_plan_update_emits_updated_and_completed_step(self):
        engine = FakeEngine([
            _init_ev(),
            EngineEvent(kind="plan", raw={}, steps=[{"id": "1", "status": "running", "description": "Buoc 1"}], reflection=""),
            EngineEvent(kind="plan", raw={}, steps=[{"id": "1", "status": "completed", "description": "Buoc 1"}], reflection=""),
            EngineEvent(kind="done", raw={}, status="SUCCESS", text="ok"),
        ])
        flow = build_cli_engine_flow(engine)
        events = await collect(flow, Message(message="hi"))
        plan_events = [e for e in events if isinstance(e, PlanEvent)]
        step_events = [e for e in events if isinstance(e, StepEvent)]
        assert plan_events[-2].status == PlanStatus.UPDATED or any(p.status == PlanStatus.UPDATED for p in plan_events)
        assert any(s.status == StepStatus.COMPLETED for s in step_events)

    async def test_done_emits_plan_completed_when_plan_exists(self):
        engine = FakeEngine([
            _init_ev(),
            EngineEvent(kind="plan", raw={}, steps=[{"id": "1", "status": "completed"}], reflection=""),
            EngineEvent(kind="done", raw={}, status="SUCCESS", text="ok"),
        ])
        flow = build_cli_engine_flow(engine)
        events = await collect(flow, Message(message="hi"))
        plan_events = [e for e in events if isinstance(e, PlanEvent)]
        assert plan_events[-1].status == PlanStatus.COMPLETED


@pytest.mark.asyncio
class TestAskUserWaitAndResume:
    async def test_ask_user_emits_message_then_wait_and_is_done_false(self):
        session = FakeSession(status=SessionStatus.RUNNING)
        engine = FakeEngine([
            _init_ev(),
            EngineEvent(kind="ask_user", raw={}, text="Ban co muon tiep tuc khong?"),
        ])
        flow = build_cli_engine_flow(engine, session=session)
        events = await collect(flow, Message(message="hi"))
        assert isinstance(events[-1], WaitEvent)
        ask_message = [e for e in events if isinstance(e, MessageEvent)]
        assert ask_message[-1].message == "Ban co muon tiep tuc khong?"
        assert flow.is_done() is False

    async def test_resume_from_waiting_continues_with_same_conversation_ref(self):
        session = FakeSession(status=SessionStatus.WAITING, conversation_ref="conv-xyz", engine_last_seq=0)
        engine = FakeEngine(
            [EngineEvent(kind="done", raw={}, status="SUCCESS", text="Da tiep tuc")],
            conversation_ref="conv-xyz",
        )
        flow = build_cli_engine_flow(engine, session=session)
        events = await collect(flow, Message(message="co, tiep tuc"))
        assert engine.started_ctx.conversation_ref == "conv-xyz"
        assert any(isinstance(e, DoneEvent) for e in events)
        assert flow.is_done() is True

    async def test_resume_replays_only_events_after_engine_last_seq(self):
        session = FakeSession(status=SessionStatus.WAITING, conversation_ref="conv-xyz", engine_last_seq=2)
        engine = FakeEngine(
            [
                (1, _init_ev("conv-xyz")),
                (2, EngineEvent(kind="ask_user", raw={}, text="cau hoi 1")),
                (3, EngineEvent(kind="done", raw={}, status="SUCCESS", text="xong")),
            ],
            conversation_ref="conv-xyz",
        )
        flow = build_cli_engine_flow(engine, session=session)
        events = await collect(flow, Message(message="co"))
        # engine_last_seq=2 nen chi con dong seq=3 (done) duoc dich — khong
        # thay lai TitleEvent/ask_user cua lan truoc.
        assert not any(isinstance(e, TitleEvent) for e in events)
        assert any(isinstance(e, DoneEvent) for e in events)


@pytest.mark.asyncio
class TestErrorHandling:
    async def test_result_error_emits_vietnamese_error_event(self):
        engine = FakeEngine([
            _init_ev(),
            EngineEvent(kind="error", raw={}, code="chua_dang_nhap", text="authentication failed or timed out"),
        ])
        flow = build_cli_engine_flow(engine)
        events = await collect(flow, Message(message="hi"))
        error_events = [e for e in events if isinstance(e, ErrorEvent)]
        assert len(error_events) == 1
        assert "đăng nhập" in error_events[0].error
        assert flow.is_done() is True


@pytest.mark.asyncio
class TestEngineCursorPersistence:
    async def test_engine_last_seq_updated_after_each_event(self):
        session = FakeSession()
        repo = FakeSessionRepository(session)
        engine = FakeEngine([
            (5, _init_ev()),
            (6, EngineEvent(kind="done", raw={}, status="SUCCESS", text="ok")),
        ])
        flow = build_cli_engine_flow(engine, session_repository=repo)
        await collect(flow, Message(message="hi"))
        assert repo.engine_cursor_updates == [5, 6]
        assert session.engine_last_seq == 6


@pytest.mark.asyncio
class TestRestartAfterProcessDeath:
    async def test_resume_with_dead_process_and_no_conversation_ref_warns_user(self):
        session = FakeSession(status=SessionStatus.WAITING, conversation_ref=None, engine_last_seq=3)
        engine = FakeEngine([EngineEvent(kind="done", raw={}, status="SUCCESS", text="ok")])
        engine.last_start_reused = False
        flow = build_cli_engine_flow(engine, session=session)
        events = await collect(flow, Message(message="tiep tuc"))
        warnings = [
            e for e in events
            if isinstance(e, MessageEvent) and "khởi chạy lại" in e.message
        ]
        assert len(warnings) == 1

    async def test_fresh_session_first_turn_does_not_warn_even_if_not_reused(self):
        session = FakeSession(status=SessionStatus.PENDING, conversation_ref=None, engine_last_seq=0)
        engine = FakeEngine([_init_ev(), EngineEvent(kind="done", raw={}, status="SUCCESS", text="ok")])
        engine.last_start_reused = False
        flow = build_cli_engine_flow(engine, session=session)
        events = await collect(flow, Message(message="lan dau"))
        warnings = [
            e for e in events
            if isinstance(e, MessageEvent) and "khởi chạy lại" in e.message
        ]
        assert len(warnings) == 0


@pytest.mark.asyncio
class TestIdleWatchdog:
    async def test_idle_timeout_with_dead_process_emits_tien_trinh_chet_error(self):
        """Khong co event nao den va sandbox bao alive=False -> ErrorEvent
        tien_trinh_chet sau idle_timeout (set rat nho de test nhanh)."""
        sandbox = FakeSandbox()
        sandbox.engine_status_response = {"alive": False, "returncode": 1, "last_seq": 0, "started_at": 0.0}
        engine = FakeEngine([_init_ev()], alive_after_events=False)
        flow = build_cli_engine_flow(
            engine, sandbox=sandbox, idle_timeout=0.05, status_ping_interval=1000, max_turn_seconds=1000,
        )
        events = await collect(flow, Message(message="hi"))
        error_events = [e for e in events if isinstance(e, ErrorEvent)]
        assert len(error_events) == 1
        assert "đã chết" in error_events[0].error
        assert flow.is_done() is True
