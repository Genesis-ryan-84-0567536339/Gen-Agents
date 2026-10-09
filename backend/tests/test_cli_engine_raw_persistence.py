"""
Test luu NDJSON tho + usage vao Mongo qua EngineRunRepository (Issue #30,
docs/design/dot-2-cli-engine.md muc 5). Dung FakeEngineRunRepository (bo nho,
khong can Mongo thuc) — xem harness.py.
"""
import pytest

from app.domain.external.engine import EngineEvent
from app.domain.models.session import SessionStatus

from tests.harness import (
    FakeEngine,
    FakeEngineRunRepository,
    FakeSession,
    FakeSessionRepository,
    build_cli_engine_flow,
)
from tests.test_cli_engine_flow import _init_ev, collect
from app.domain.models.message import Message


@pytest.mark.asyncio
class TestRawLinePersistence:
    async def test_one_turn_opens_one_engine_run_with_all_lines(self):
        repo = FakeEngineRunRepository()
        engine = FakeEngine([
            _init_ev("conv-1"),
            EngineEvent(kind="tool_call", raw={"event": "step_update", "step_update": {"tool_name": "run_command"}}, tool_call_id="k1", tool_name="run_command"),
            EngineEvent(kind="done", raw={"event": "result", "result": {"status": "SUCCESS"}}, status="SUCCESS", text="ok"),
        ])
        flow = build_cli_engine_flow(engine, engine_run_repository=repo)
        await collect(flow, Message(message="hi"))

        runs = await repo.find_by_session("session-1")
        assert len(runs) == 1
        assert runs[0]["turn_index"] == 1
        assert runs[0]["status"] == "SUCCESS"
        assert len(runs[0]["lines"]) == 3
        # engine_run duoc mo TRUOC khi gui tin (tu session.conversation_ref,
        # von con None o luot dau tien cua mot phien moi) — conversation_ref
        # thuc su (biet qua "init") chi duoc Session ghi lai (commit "truong
        # engine tren Session"), khong phai EngineRunDocument cua luot dau.
        assert runs[0]["conversation_ref"] is None

    async def test_two_turns_in_separate_sessions_open_two_runs_with_turn_index_1_and_2(self):
        repo = FakeEngineRunRepository()
        session = FakeSession(status=SessionStatus.PENDING)
        session_repo = FakeSessionRepository(session)

        engine1 = FakeEngine([_init_ev(), EngineEvent(kind="done", raw={}, status="SUCCESS", text="xong 1")])
        flow1 = build_cli_engine_flow(engine1, session_repository=session_repo, engine_run_repository=repo)
        await collect(flow1, Message(message="luot 1"))

        session.status = SessionStatus.PENDING
        engine2 = FakeEngine([_init_ev(), EngineEvent(kind="done", raw={}, status="SUCCESS", text="xong 2")])
        flow2 = build_cli_engine_flow(engine2, session_repository=session_repo, engine_run_repository=repo)
        await collect(flow2, Message(message="luot 2"))

        runs = await repo.find_by_session("session-1")
        assert [r["turn_index"] for r in runs] == [1, 2]

    async def test_wait_event_closes_turn_with_waiting_status(self):
        repo = FakeEngineRunRepository()
        engine = FakeEngine([_init_ev(), EngineEvent(kind="ask_user", raw={"event": "ask"}, text="tiep tuc khong?")])
        flow = build_cli_engine_flow(engine, engine_run_repository=repo)
        await collect(flow, Message(message="hi"))
        runs = await repo.find_by_session("session-1")
        assert runs[0]["status"] == "WAITING"

    async def test_error_event_closes_turn_with_error_status(self):
        repo = FakeEngineRunRepository()
        engine = FakeEngine([_init_ev(), EngineEvent(kind="error", raw={}, code="khac", text="loi la")])
        flow = build_cli_engine_flow(engine, engine_run_repository=repo)
        await collect(flow, Message(message="hi"))
        runs = await repo.find_by_session("session-1")
        assert runs[0]["status"] == "ERROR"

    async def test_raw_keep_false_disables_recording_but_repository_still_opens_turn(self):
        repo = FakeEngineRunRepository()
        engine = FakeEngine([_init_ev(), EngineEvent(kind="done", raw={}, status="SUCCESS", text="ok")])
        flow = build_cli_engine_flow(engine, engine_run_repository=repo, raw_keep=False)
        await collect(flow, Message(message="hi"))
        runs = await repo.find_by_session("session-1")
        assert len(runs) == 1
        assert runs[0]["lines"] == []

    async def test_no_repository_configured_does_not_crash(self):
        engine = FakeEngine([_init_ev(), EngineEvent(kind="done", raw={}, status="SUCCESS", text="ok")])
        flow = build_cli_engine_flow(engine, engine_run_repository=None)
        events = await collect(flow, Message(message="hi"))
        assert events  # chay binh thuong, khong nem loi vi thieu repository


@pytest.mark.asyncio
class TestConversationRefPersistence:
    async def test_init_conversation_ref_is_written_to_session_repository(self):
        session = FakeSession()
        repo = FakeSessionRepository(session)
        engine = FakeEngine([_init_ev("conv-abc"), EngineEvent(kind="done", raw={}, status="SUCCESS", text="ok")])
        flow = build_cli_engine_flow(engine, session_repository=repo)
        await collect(flow, Message(message="hi"))
        assert repo.conversation_ref_updates == ["conv-abc"]
        assert session.conversation_ref == "conv-abc"


@pytest.mark.asyncio
class TestUsagePersistence:
    async def test_usage_event_persists_to_session_repository_once_at_turn_end(self):
        session = FakeSession()
        repo = FakeSessionRepository(session)
        engine = FakeEngine([
            _init_ev(),
            EngineEvent(kind="usage", raw={}, usage={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110}),
            EngineEvent(kind="usage", raw={}, usage={"input_tokens": 150, "output_tokens": 20, "total_tokens": 170}),
            EngineEvent(kind="done", raw={}, status="SUCCESS", text="ok"),
        ])
        flow = build_cli_engine_flow(engine, session_repository=repo)
        await collect(flow, Message(message="hi"))
        # Chi 1 lan goi add_engine_usage, voi gia tri CUOI CUNG (khong cong
        # don 2 dong usage lai — tranh dem trung token luy ke).
        assert len(repo.engine_usage_calls) == 1
        assert repo.engine_usage_calls[0] == {"input_tokens": 150, "output_tokens": 20, "total_tokens": 170}

    async def test_no_usage_event_means_no_usage_call(self):
        session = FakeSession()
        repo = FakeSessionRepository(session)
        engine = FakeEngine([_init_ev(), EngineEvent(kind="done", raw={}, status="SUCCESS", text="ok")])
        flow = build_cli_engine_flow(engine, session_repository=repo)
        await collect(flow, Message(message="hi"))
        assert repo.engine_usage_calls == []
