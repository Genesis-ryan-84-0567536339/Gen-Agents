"""
Test dich thuan NDJSON cua agy -> EngineEvent (Issue #30).

Du lieu vao la mau NDJSON thuc te cua agy v1.3.2 (docs/spec/01-dong-co-cli.md
muc 3; dong loi dang nhap lay nguyen van tu
docs/evidence/dot-1/agy-p-auth-failed.txt), luu o
backend/tests/fixtures/agy_ndjson_samples.ndjson. Cac truong "…" trong tai
lieu goc duoc dien gia tri hop ly (JSON phai hop le) nhung giu dung cau truc
khoa/gia tri ma spec 01 mo ta.

Khong dung Docker/sandbox thuc: dung FakeSandbox (giong backend/tests/harness.py)
de gia lap `engine_events` phat lai dung cac dong trong fixture.
"""
import json
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List

import pytest

from app.domain.external.engine import EngineContext
from app.domain.models.tool_result import ToolResult
from app.infrastructure.external.engine.agy_engine import (
    AgyEngine,
    classify_error,
    strip_mcp_prefix,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLES_PATH = FIXTURES_DIR / "agy_ndjson_samples.ndjson"


def _load_samples() -> List[str]:
    return [
        line
        for line in SAMPLES_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class FakeEngineSandbox:
    """Sandbox gia lap chi cho engine_* — phat lai cac dong NDJSON da cho
    (dang 'stdout') voi seq tang tu 1."""

    def __init__(self, lines: List[str]):
        self._lines = lines
        self.started: Dict[str, Any] = {}
        self.sent: List[str] = []
        self.stopped = False

    async def engine_start(self, engine_id, argv, env, cwd):
        self.started = {"engine_id": engine_id, "argv": argv, "env": env, "cwd": cwd}
        return ToolResult(success=True, data={"engine_id": engine_id, "pid": 123, "alive": True, "started_at": 0.0, "reused": False})

    async def engine_send(self, engine_id, line):
        self.sent.append(line)
        return ToolResult(success=True, data={"ok": True, "bytes": len(line)})

    async def engine_events(self, engine_id, from_seq: int = 0) -> AsyncIterator[Dict[str, Any]]:
        seq = 0
        for raw_line in self._lines:
            seq += 1
            if seq <= from_seq:
                continue
            yield {"seq": seq, "stream": "stdout", "ts": float(seq), "line": raw_line}

    async def engine_status(self, engine_id):
        return ToolResult(success=True, data={"alive": True, "returncode": None, "last_seq": len(self._lines), "started_at": 0.0})

    async def engine_stop(self, engine_id, signal=None):
        self.stopped = True
        return ToolResult(success=True, data={"ok": True, "returncode": 0})


pytestmark = pytest.mark.asyncio


class TestStripMcpPrefix:
    def test_strips_sandbox_prefix_variants(self):
        assert strip_mcp_prefix("sandbox__plan_update") == "plan_update"
        assert strip_mcp_prefix("mcp__sandbox__plan_update") == "plan_update"
        assert strip_mcp_prefix("mcp__gen-agents-sandbox__message_ask_user") == "message_ask_user"
        assert strip_mcp_prefix("sandbox.message_notify_user") == "message_notify_user"
        assert strip_mcp_prefix("sandbox:message_notify_user") == "message_notify_user"
        assert strip_mcp_prefix("sandbox/message_notify_user") == "message_notify_user"

    def test_passthrough_when_no_prefix(self):
        # Agy co the in ten "tran" khong tien to — van nhan dien duoc.
        assert strip_mcp_prefix("plan_update") == "plan_update"
        # Tool thuong (khong phai 1 trong 3 tool tien do) giu nguyen, khong
        # bi nham la tool MCP.
        assert strip_mcp_prefix("run_command") == "run_command"


class TestClassifyError:
    def test_auth_failed_sample_classified_as_chua_dang_nhap(self):
        # Mau thuc te dung van ban tu docs/evidence/dot-1/agy-p-auth-failed.txt —
        # chua "timed out" NHUNG phai uu tien "chua_dang_nhap" (co "authentication").
        assert classify_error("authentication failed or timed out") == "chua_dang_nhap"

    def test_quota(self):
        assert classify_error("rate limit exceeded, resource_exhausted") == "het_quota"

    def test_timeout_alone(self):
        assert classify_error("request timeout after 60s") == "timeout"

    def test_unknown_falls_back_to_khac(self):
        assert classify_error("some unexpected failure") == "khac"


@pytest.fixture
def engine():
    return AgyEngine(FakeEngineSandbox([]), binary="agy")


class TestAgyTranslateFromFixture:
    async def test_full_fixture_translates_without_crashing(self, engine):
        lines = _load_samples()
        sandbox = FakeEngineSandbox(lines)
        engine = AgyEngine(sandbox, binary="agy")
        ctx = EngineContext(session_id="s1", model="gemini-3.8-flash-low", effort="low")
        await engine.start(ctx)

        kinds: List[str] = []
        async for seq, event in engine.events(from_seq=0):
            kinds.append(event.kind)

        assert "init" in kinds
        assert "text_delta" in kinds
        assert "tool_call" in kinds
        assert "tool_result" in kinds
        assert "plan" in kinds
        assert "ask_user" in kinds
        assert "notify" in kinds
        assert "usage" in kinds
        assert "done" in kinds
        assert "error" in kinds

    async def test_init_sets_conversation_ref(self, engine):
        sandbox = FakeEngineSandbox(_load_samples())
        engine = AgyEngine(sandbox)
        await engine.start(EngineContext(session_id="s1"))
        async for seq, event in engine.events():
            if event.kind == "init":
                assert event.conversation_ref == "conv-abc123"
                break
        assert engine.conversation_ref == "conv-abc123"

    async def test_normal_tool_call_and_result_paired_by_id(self, engine):
        sandbox = FakeEngineSandbox(_load_samples())
        engine = AgyEngine(sandbox)
        await engine.start(EngineContext(session_id="s1"))
        tool_call_ids = set()
        tool_result_ids = set()
        async for seq, event in engine.events():
            if event.kind == "tool_call" and event.tool_name == "run_command":
                tool_call_ids.add(event.tool_call_id)
            if event.kind == "tool_result" and event.tool_name == "run_command":
                tool_result_ids.add(event.tool_call_id)
                assert event.tool_output == "hi\r\n"
        assert tool_call_ids == tool_result_ids
        assert len(tool_call_ids) == 1

    async def test_progress_tools_do_not_emit_tool_result(self, engine):
        """plan_update/message_ask_user/message_notify_user: tool_result cua
        3 tool nay phai bi bo (tranh ToolEvent rac) — chi con tool_call-tuong-duong
        (plan/ask_user/notify) o trang thai ACTIVE."""
        sandbox = FakeEngineSandbox(_load_samples())
        engine = AgyEngine(sandbox)
        await engine.start(EngineContext(session_id="s1"))
        events = []
        async for seq, event in engine.events():
            events.append(event)
        tool_result_names = {
            e.tool_name for e in events if e.kind == "tool_result"
        }
        assert "sandbox__plan_update" not in tool_result_names
        assert "sandbox__message_ask_user" not in tool_result_names
        assert "sandbox__message_notify_user" not in tool_result_names

        plan_events = [e for e in events if e.kind == "plan"]
        assert len(plan_events) == 1
        assert plan_events[0].steps == [{"id": "1", "status": "running"}]
        assert plan_events[0].reflection == "Dang chay buoc 1"

        ask_events = [e for e in events if e.kind == "ask_user"]
        assert len(ask_events) == 1
        assert ask_events[0].text == "Ban muon tiep tuc khong?"

        notify_events = [e for e in events if e.kind == "notify"]
        assert len(notify_events) == 1
        assert notify_events[0].text == "Da hoan thanh buoc 1."

    async def test_result_success_emits_usage_then_done(self, engine):
        sandbox = FakeEngineSandbox(_load_samples())
        engine = AgyEngine(sandbox)
        await engine.start(EngineContext(session_id="s1"))
        events = [event async for _, event in engine.events()]
        # Dong result SUCCESS la dong thu 11 trong fixture — hai event lien
        # tiep usage roi done, theo dung thu tu thiet ke muc 2.1.
        done_index = next(i for i, e in enumerate(events) if e.kind == "done")
        assert events[done_index - 1].kind == "usage"
        assert events[done_index].status == "SUCCESS"

    async def test_result_error_emits_error_event_classified(self, engine):
        sandbox = FakeEngineSandbox(_load_samples())
        engine = AgyEngine(sandbox)
        await engine.start(EngineContext(session_id="s1"))
        events = [event async for _, event in engine.events()]
        error_events = [e for e in events if e.kind == "error"]
        assert len(error_events) == 1
        assert error_events[0].code == "chua_dang_nhap"
        assert error_events[0].text == "authentication failed or timed out"

    async def test_seq_is_monotonically_non_decreasing(self, engine):
        """`seq` la cua DONG NDJSON tho, khong phai cua EngineEvent da dich —
        mot dong co the sinh 0, 1 hoac 2 event (vd result SUCCESS -> usage
        roi done CUNG seq) nen seq khong giam, khong nhat thiet tang nghiem
        ngat moi phan tu."""
        sandbox = FakeEngineSandbox(_load_samples())
        engine = AgyEngine(sandbox)
        await engine.start(EngineContext(session_id="s1"))
        seqs = [seq async for seq, _ in engine.events()]
        assert seqs == sorted(seqs)
        assert seqs, "phai co it nhat 1 event"
        assert seqs[-1] <= len(_load_samples())

    async def test_from_seq_resumes_without_replaying_earlier_lines(self, engine):
        sandbox = FakeEngineSandbox(_load_samples())
        engine = AgyEngine(sandbox)
        await engine.start(EngineContext(session_id="s1"))
        all_seqs = [seq async for seq, _ in engine.events(from_seq=0)]
        resumed_seqs = [seq async for seq, _ in engine.events(from_seq=3)]
        assert resumed_seqs == all_seqs[3:]


class TestAgyBuildArgvAndUserLine:
    def test_build_argv_includes_model_effort_and_conversation(self, engine):
        ctx = EngineContext(session_id="s1", model="gemini-3.8-flash-low", effort="low", conversation_ref="conv-1")
        argv = engine._build_argv(ctx)
        assert argv[0] == "agy"
        assert "--model" in argv and "gemini-3.8-flash-low" in argv
        assert "--effort" in argv and "low" in argv
        assert "--dangerously-skip-permissions" in argv
        assert "--conversation" in argv and "conv-1" in argv

    def test_build_argv_omits_conversation_when_absent(self, engine):
        ctx = EngineContext(session_id="s1", model="m", effort="low")
        argv = engine._build_argv(ctx)
        assert "--conversation" not in argv

    def test_build_user_line_is_valid_ndjson_event_user(self, engine):
        line = engine._build_user_line("hello", None)
        parsed = json.loads(line)
        assert parsed["event"] == "user"
        assert parsed["message"]["content"][0]["text"] == "hello"

    def test_build_user_line_appends_attachment_note(self, engine):
        line = engine._build_user_line("hello", ["/home/ubuntu/upload/report.pdf"])
        parsed = json.loads(line)
        text = parsed["message"]["content"][0]["text"]
        assert "report.pdf" in text
        assert "Tệp đã tải lên" in text
