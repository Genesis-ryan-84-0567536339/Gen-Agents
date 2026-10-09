"""
Test nghiem thu /api/v1/engine/* (Issue #30, docs/design/dot-2-cli-engine.md
muc 1.3). Giong cac test khac trong sandbox/tests/ (xem conftest.py: BASE_URL)
— can tool API FastAPI THAT dang chay, khong mock.

Dung `fake_agy.py` (cung thu muc nay) lam "binary" gia lap agy — khong can
agy that/dang nhap. ENGINE_ALLOWED_BINARIES trong docker-compose-development.yml
phai bao gom "fake_agy.py".
"""
import json
import os
import time
import uuid

import pytest
import requests

from tests.conftest import BASE_URL

# QUAN TRONG: /api/v1/engine/start chay TRONG container sandbox (tien trinh
# tool API), con test nay (job "Sandbox API tests" cua CI, xem conftest.py)
# chay TREN RUNNER/HOST, chi goi REST toi container qua BASE_URL. Vi vay
# duong dan phai la duong dan BEN TRONG container (bind-mount "./sandbox:/app",
# xem docker-compose-development.yml), KHONG duoc tu os.path.dirname(__file__)
# (do se ra duong dan host, sai hoan toan trong container).
FAKE_AGY_PATH = os.environ.get("FAKE_AGY_CONTAINER_PATH", "/app/tests/fake_agy.py")


def _argv(extra_env: dict | None = None):
    # argv[0] PHAI la duong dan fake_agy.py (khong boc trong sys.executable)
    # de os.path.basename(argv[0]) == "fake_agy.py" khop ENGINE_ALLOWED_BINARIES
    # ("agy,claude,fake_agy.py" trong docker-compose-development.yml) — file
    # thuc thi duoc nho shebang "#!/usr/bin/env python3" + quyen +x.
    return [FAKE_AGY_PATH]


def _start(client, engine_id, env=None, cwd="/tmp"):
    payload = {
        "engine_id": engine_id,
        "argv": _argv(),
        "env": env or {},
        "cwd": cwd,
    }
    resp = client.post(f"{BASE_URL}/api/v1/engine/start", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _send(client, engine_id, line):
    resp = client.post(
        f"{BASE_URL}/api/v1/engine/send",
        json={"engine_id": engine_id, "line": line},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _status(client, engine_id):
    resp = client.get(f"{BASE_URL}/api/v1/engine/status", params={"engine_id": engine_id})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _stop(client, engine_id, signal=None):
    payload = {"engine_id": engine_id}
    if signal:
        payload["signal"] = signal
    resp = client.post(f"{BASE_URL}/api/v1/engine/stop", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _read_sse_events(engine_id, from_seq=0, max_events=50, timeout=15):
    """Doc SSE thong qua requests (stream=True), tra ve list dict da parse,
    dung ngay khi gap mot dong co event=='result' hoac het timeout.

    QUAN TRONG: timeout cua requests la "khong co byte nao den trong X giay"
    (tung lan doc), KHONG phai tong thoi gian — endpoint phat keepalive
    ": ping" moi 15s (xem sandbox/app/api/v1/engine.py). Phai dat timeout
    HTTP lon hon 15s, neu khong requests tu nem ReadTimeoutError truoc khi
    kip toi keepalive tiep theo (gap khi cho ask_user, khong co dong moi
    trong khoang 10-15s). deadline ben duoi moi la co che dung dung logic
    cua test.
    """
    url = f"{BASE_URL}/api/v1/engine/events"
    events = []
    deadline = time.monotonic() + timeout
    http_timeout = max(timeout, 20)
    with requests.get(url, params={"engine_id": engine_id, "from_seq": from_seq}, stream=True, timeout=http_timeout) as resp:
        assert resp.status_code == 200
        for raw_line in resp.iter_lines(decode_unicode=True):
            if time.monotonic() > deadline or len(events) >= max_events:
                break
            if not raw_line or raw_line.startswith(":"):
                continue
            if raw_line.startswith("data: "):
                payload = json.loads(raw_line[len("data: "):])
                events.append(payload)
                parsed_line = payload.get("line", "")
                try:
                    parsed = json.loads(parsed_line)
                except (json.JSONDecodeError, TypeError):
                    parsed = {}
                if parsed.get("event") == "result":
                    break
    return events


@pytest.fixture
def client():
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


class TestEngineLifecycle:
    def test_start_send_events_result_success(self, client):
        engine_id = f"test-engine-{uuid.uuid4().hex[:8]}"
        started = _start(client, engine_id)
        assert started["alive"] is True
        assert started["reused"] is False

        _send(client, engine_id, json.dumps({
            "event": "user",
            "message": {"content": [{"type": "text", "text": "hello"}]},
        }))

        events = _read_sse_events(engine_id)
        assert events, "phai nhan duoc it nhat 1 dong SSE"
        kinds = []
        for item in events:
            parsed = json.loads(item["line"])
            kinds.append(parsed.get("event"))
        assert "init" in kinds
        assert "result" in kinds
        result_line = next(json.loads(e["line"]) for e in events if json.loads(e["line"]).get("event") == "result")
        assert result_line["result"]["status"] == "SUCCESS"

        _stop(client, engine_id)
        status = _status(client, engine_id)
        assert status["alive"] is False

    def test_start_twice_is_idempotent_reused(self, client):
        engine_id = f"test-engine-{uuid.uuid4().hex[:8]}"
        first = _start(client, engine_id)
        second = _start(client, engine_id)
        assert first["reused"] is False
        assert second["reused"] is True
        assert first["pid"] == second["pid"]
        _stop(client, engine_id)

    def test_from_seq_replays_only_newer_lines(self, client):
        engine_id = f"test-engine-{uuid.uuid4().hex[:8]}"
        _start(client, engine_id)
        _send(client, engine_id, json.dumps({
            "event": "user",
            "message": {"content": [{"type": "text", "text": "hello"}]},
        }))
        all_events = _read_sse_events(engine_id, from_seq=0)
        assert len(all_events) > 1
        mid_seq = all_events[0]["seq"]
        replay = _read_sse_events(engine_id, from_seq=mid_seq)
        assert all(item["seq"] > mid_seq for item in replay)
        assert len(replay) == len(all_events) - 1
        _stop(client, engine_id)

    def test_stop_then_status_not_alive(self, client):
        engine_id = f"test-engine-{uuid.uuid4().hex[:8]}"
        _start(client, engine_id)
        stopped = _stop(client, engine_id)
        assert stopped["ok"] is True
        status = _status(client, engine_id)
        assert status["alive"] is False

    def test_unknown_binary_rejected_by_allowlist(self, client):
        engine_id = f"test-engine-{uuid.uuid4().hex[:8]}"
        resp = client.post(
            f"{BASE_URL}/api/v1/engine/start",
            json={"engine_id": engine_id, "argv": ["/bin/not-allowed"], "env": {}, "cwd": "/tmp"},
        )
        assert resp.status_code == 400, resp.text

    def test_line_larger_than_64kib_not_truncated_with_limit(self, client):
        """Dong NDJSON > 64 KiB (mac dinh StreamReader) phai van di qua het
        nho `limit=ENGINE_MAX_LINE_BYTES` lon hon nhieu — fake_agy in ra mot
        dong tool_info.output dai 100 KiB qua FAKE_AGY_BIG_LINE_KB."""
        engine_id = f"test-engine-{uuid.uuid4().hex[:8]}"
        big_kb = 100  # > 64 KiB mac dinh cua asyncio.StreamReader
        env = {"FAKE_AGY_BIG_LINE_KB": str(big_kb)}
        _start(client, engine_id, env=env)
        _send(client, engine_id, json.dumps({
            "event": "user",
            "message": {"content": [{"type": "text", "text": "hello"}]},
        }))
        events = _read_sse_events(engine_id, timeout=15)
        assert not any(item.get("truncated") for item in events)
        big_lines = []
        for item in events:
            try:
                parsed = json.loads(item["line"])
            except json.JSONDecodeError:
                continue
            output = (
                (parsed.get("step_update") or {}).get("tool_info", {}).get("output", "")
                if parsed.get("event") == "step_update"
                else ""
            )
            if isinstance(output, str) and len(output) > 64 * 1024:
                big_lines.append(output)
        assert big_lines, "phai nhan duoc dong > 64 KiB nguyen ven"
        assert len(big_lines[0]) == big_kb * 1024
        _stop(client, engine_id)


def _ask_user_mode_env():
    return {"FAKE_AGY_MODE": "ask", "FAKE_AGY_ASK_TURN": "1"}


class TestEngineAskUserResume:
    def test_ask_user_then_resume_same_conversation(self, client):
        engine_id = f"test-engine-{uuid.uuid4().hex[:8]}"
        _start(client, engine_id, env=_ask_user_mode_env())
        _send(client, engine_id, json.dumps({
            "event": "user",
            "message": {"content": [{"type": "text", "text": "cau hoi dau tien"}]},
        }))
        first_events = _read_sse_events(engine_id, timeout=10, max_events=20)
        lines = [json.loads(e["line"]) for e in first_events]
        tool_names = [
            (ln.get("step_update") or {}).get("tool_name")
            for ln in lines
            if ln.get("event") == "step_update"
        ]
        assert "sandbox__message_ask_user" in tool_names
        assert not any(ln.get("event") == "result" for ln in lines)

        status = _status(client, engine_id)
        assert status["alive"] is True, "tien trinh CLI phai con song sau khi hoi"

        last_seq = first_events[-1]["seq"]
        _send(client, engine_id, json.dumps({
            "event": "user",
            "message": {"content": [{"type": "text", "text": "co, tiep tuc"}]},
        }))
        second_events = _read_sse_events(engine_id, from_seq=last_seq, timeout=10)
        second_lines = [json.loads(e["line"]) for e in second_events]
        assert any(ln.get("event") == "result" and ln["result"]["status"] == "SUCCESS" for ln in second_lines)
        _stop(client, engine_id)
