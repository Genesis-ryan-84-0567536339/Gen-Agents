"""
Test nghiệm thu 25 tool MCP (Issue #29, docs/spec/02-mcp-trong-sandbox.md mục 8).

Giống các test khác trong `sandbox/tests/` (xem conftest.py: `BASE_URL`),
file này cần các dịch vụ THẬT đang chạy — không mock:

- tool API FastAPI của sandbox tại `SANDBOX_API_URL` (mặc định
  http://127.0.0.1:8080) — để test shell/file qua REST thật.
- Chrome có CDP tại `CDP_TEST_URL` (mặc định http://127.0.0.1:19222 khi
  chạy test cục bộ ngoài container; trong container dùng 127.0.0.1:9222).
- MCP server của chính đợt này tại `MCP_TEST_URL` (mặc định
  http://127.0.0.1:8081/mcp).

Chạy cục bộ (ngoài container, dùng để phát triển nhanh):
    uv run uvicorn app.main:app --port 8080 &            # tool API thật
    google-chrome --headless=new --no-sandbox \\
        --remote-debugging-port=19222 \\
        --user-data-dir=/tmp/chrome-mcp-test-profile &   # CDP test rieng
    CDP_URL=http://127.0.0.1:19222 uv run python mcp/server.py &
    uv run pytest tests/test_mcp_tools.py -v

Chạy trong container (CDP thật ở :9222, program mcp đã chạy qua supervisord):
    docker exec <container> bash -lc \\
        "cd /app && uv run pytest sandbox/tests/test_mcp_tools.py -v"

LƯU Ý KỸ THUẬT: mỗi test tự mở/đóng 1 `ClientSession` MCP trong CHÍNH coroutine
của nó (qua `mcp_session()` dưới đây) thay vì dùng fixture async dùng chung —
`streamablehttp_client`/`ClientSession` dùng `anyio.create_task_group()` nội
bộ, và việc mở ở fixture rồi đóng ở teardown (task khác trong một số phiên
bản pytest-asyncio) gây lỗi "Attempted to exit cancel scope in a different
task" (đã gặp khi thử nghiệm). Mở/đóng trong cùng một test tránh lỗi này.
"""
import json
import os
from contextlib import asynccontextmanager

import pytest

mcp_client_mod = pytest.importorskip("mcp.client.streamable_http")
from mcp import ClientSession  # noqa: E402
from mcp.client.streamable_http import streamablehttp_client  # noqa: E402

MCP_URL = os.environ.get("MCP_TEST_URL", "http://127.0.0.1:8081/mcp")

pytestmark = pytest.mark.asyncio


@asynccontextmanager
async def mcp_session():
    async with streamablehttp_client(MCP_URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def _result_json(call_tool_result):
    """Tool trả về 1 TextContent chứa JSON (dict {success, message, data})."""
    assert call_tool_result.content, "Tool khong tra ve content nao"
    text = call_tool_result.content[0].text
    return json.loads(text)


class TestToolsList:
    async def test_exactly_25_tools(self):
        async with mcp_session() as session:
            tools = await session.list_tools()
        names = sorted(t.name for t in tools.tools)
        assert len(names) == 25
        expected = {
            "shell_exec", "shell_view", "shell_wait", "shell_write_to_process", "shell_kill_process",
            "file_read", "file_write", "file_str_replace", "file_find_in_content", "file_find_by_name",
            "browser_view", "browser_navigate", "browser_restart", "browser_click", "browser_input",
            "browser_move_mouse", "browser_press_key", "browser_select_option", "browser_scroll_up",
            "browser_scroll_down", "browser_console_exec", "browser_console_view",
            "plan_update", "message_ask_user", "message_notify_user",
        }
        assert set(names) == expected


class TestShellTools:
    async def test_shell_exec_echo(self):
        async with mcp_session() as session:
            result = await session.call_tool("shell_exec", {"command": "echo hello-from-mcp-test"})
        data = _result_json(result)
        assert data["success"] is True
        assert "hello-from-mcp-test" in data["data"]["output"]

    async def test_shell_view_after_exec(self):
        async with mcp_session() as session:
            exec_result = await session.call_tool("shell_exec", {"command": "echo view-me"})
            session_id = _result_json(exec_result)["data"]["session_id"]
            view_result = await session.call_tool("shell_view", {"id": session_id})
        data = _result_json(view_result)
        assert data["success"] is True


class TestFileTools:
    async def test_write_then_read(self):
        path = "/tmp/mcp_pytest_file.txt"
        content = "noi dung test MCP file_write/file_read"
        async with mcp_session() as session:
            write_result = await session.call_tool("file_write", {"file": path, "content": content})
            read_result = await session.call_tool("file_read", {"file": path})
        write_data = _result_json(write_result)
        assert write_data["success"] is True
        read_data = _result_json(read_result)
        assert read_data["success"] is True
        assert read_data["data"]["content"] == content

    async def test_find_by_name(self):
        async with mcp_session() as session:
            # bao dam file ton tai truoc khi tim
            await session.call_tool(
                "file_write", {"file": "/tmp/mcp_pytest_file.txt", "content": "x"}
            )
            result = await session.call_tool(
                "file_find_by_name", {"path": "/tmp", "glob": "mcp_pytest_file.txt"}
            )
        data = _result_json(result)
        assert data["success"] is True
        assert any("mcp_pytest_file.txt" in f for f in data["data"]["files"])


class TestBrowserTools:
    async def test_navigate_then_view(self):
        async with mcp_session() as session:
            nav_result = await session.call_tool("browser_navigate", {"url": "https://example.com"})
            view_result = await session.call_tool("browser_view", {})
        nav_data = _result_json(nav_result)
        assert nav_data["success"] is True
        assert "example.com" in nav_data["data"]["url"]
        assert nav_data["data"]["title"]
        assert len(nav_data["data"]["screenshot"]) > 1000  # base64 PNG hop le

        view_data = _result_json(view_result)
        assert view_data["success"] is True
        assert "example.com" in view_data["data"]["url"]


class TestProgressTools:
    async def test_plan_update_returns_confirmation(self):
        async with mcp_session() as session:
            result = await session.call_tool(
                "plan_update",
                {"steps": [{"id": "1", "status": "completed"}], "reflection": "pytest"},
            )
        assert result.content
        assert "plan_update" in result.content[0].text

    async def test_message_notify_user_returns_confirmation(self):
        async with mcp_session() as session:
            result = await session.call_tool("message_notify_user", {"text": "pytest notify"})
        assert result.content
        assert "message_notify_user" in result.content[0].text
