"""
Test nghiệm thu 25 tool MCP (Issue #29, docs/spec/02-mcp-trong-sandbox.md mục 8).

Giống các test khác trong `sandbox/tests/` (xem conftest.py: `BASE_URL`),
file này cần các dịch vụ THẬT đang chạy — không mock:

- tool API FastAPI của sandbox tại `SANDBOX_API_URL` (mặc định
  http://127.0.0.1:8080) — để test shell/file qua REST thật.
- Chrome có CDP tại `CDP_TEST_URL` (mặc định http://127.0.0.1:19222 khi
  chạy test cục bộ ngoài container; trong container dùng 127.0.0.1:9222).
- MCP server của chính đợt này tại `MCP_TEST_URL` (mặc định
  http://127.0.0.1:8081/mcp). Trong CI (job "E2E", bước "Sandbox API
  tests" — chạy TRỰC TIẾP trên runner, không qua `docker exec`),
  `docker-compose-development.yml` map cổng này ra
  `127.0.0.1:8081` của runner + đặt `GEN_AGENTS_MCP_BIND=0.0.0.0`
  CHỈ cho service `sandbox` ở file dev đó, nên mặc định ở trên vẫn đúng mà
  không cần set thêm biến môi trường. Container nhiệm vụ thật
  (`docker-compose.yml`/`docker_sandbox.py`) không đặt biến này nên MCP
  server vẫn chỉ bind `127.0.0.1` bên trong, đúng luật bảo mật mục 6 của
  `docs/spec/02-mcp-trong-sandbox.md`.

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

LƯU Ý (review Opus PR #36): ảnh chụp màn hình trả về dạng `ImageContent`
thật (không phải base64 nhét trong text JSON) — xem
`TestBrowserTools.test_view_includes_real_image_content`. Mặc định các tool
đổi trạng thái trang (navigate/click/...) KHÔNG kèm ảnh (chỉ `browser_view`
luôn kèm) — truyền `with_screenshot=True` khi cần, xem
`test_with_screenshot_param_adds_image`.
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


def _text_content(call_tool_result):
    """Lấy phần TextContent đầu tiên trong kết quả tool (có thể có thêm ImageContent sau)."""
    for item in call_tool_result.content:
        if item.type == "text":
            return item
    raise AssertionError(f"Tool khong tra ve TextContent nao: {call_tool_result.content}")


def _result_json(call_tool_result):
    """Tool trả về 1 TextContent chứa JSON (dict {success, message, data})."""
    return json.loads(_text_content(call_tool_result).text)


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

    async def test_shell_wait_long_running_past_30s(self):
        """Review Opus PR #36: REST_TIMEOUT chung (30s) < seconds=35 truyen vao
        tung lam shell_wait loi httpx.ReadTimeout truoc khi tool API (tu cho
        toi 35s) kip tra loi. Gia tri test o day CHU Y co that: lenh `sleep 32`
        + `shell_wait(seconds=35)` phai PASS (khong bi cat giua chung o moc
        30s)."""
        async with mcp_session() as session:
            exec_result = await session.call_tool(
                "shell_exec",
                {"id": "pytest-wait-long", "command": "sleep 32 && echo done-long-wait"},
            )
            assert _result_json(exec_result)["data"]["status"] == "running"
            wait_result = await session.call_tool(
                "shell_wait", {"id": "pytest-wait-long", "seconds": 35}
            )
        data = _result_json(wait_result)
        assert data["success"] is True
        assert data["data"]["returncode"] == 0


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


class TestForbiddenPaths:
    """Review Opus PR #36 — luật cứng §7 của docs/spec/00-tong-quan.md: cấm
    tool file đọc/ghi thư mục phiên đăng nhập CLI.

    LƯU Ý: dùng đường dẫn TUYỆT ĐỐI của user `ubuntu` trong container
    (`/home/ubuntu/...`), KHÔNG dùng `os.path.expanduser("~")` ở phía test —
    test có thể chạy trên host/CI runner (HOME khác, vd `/home/runner`) hay
    `docker exec` vào container; `_is_forbidden_path` so khớp phía SERVER
    (HOME của chính MCP server, luôn là `/home/ubuntu` — xem
    sandbox/mcp/rest_client.py), nên test phải gửi đúng path tuyệt đối đó,
    không phụ thuộc HOME của máy đang chạy pytest."""

    async def test_file_read_rejects_gemini_home(self):
        async with mcp_session() as session:
            result = await session.call_tool(
                "file_read", {"file": "/home/ubuntu/.gemini/config/mcp_config.json"}
            )
        data = _result_json(result)
        assert data["success"] is False
        assert "luật cứng" in data["message"].lower() or "§7" in data["message"]


class TestBrowserTools:
    async def test_navigate_default_has_no_image(self):
        """Mac dinh (khong with_screenshot) chi tra text — KHONG co ImageContent,
        tranh ton token cho moi lan goi (review Opus PR #36)."""
        async with mcp_session() as session:
            nav_result = await session.call_tool("browser_navigate", {"url": "https://example.com"})
        types = [c.type for c in nav_result.content]
        assert types == ["text"]
        nav_data = _result_json(nav_result)
        assert nav_data["success"] is True
        assert "example.com" in nav_data["data"]["url"]
        assert nav_data["data"]["title"]
        assert isinstance(nav_data["data"]["width"], int)
        assert isinstance(nav_data["data"]["height"], int)

    async def test_view_includes_real_image_content(self):
        """browser_view LUON kem anh — phai la ImageContent that (mime
        image/jpeg), khong phai base64 nhet trong text JSON, va da duoc thu
        nho ve chieu rong toi da 1024px."""
        async with mcp_session() as session:
            await session.call_tool("browser_navigate", {"url": "https://example.com"})
            view_result = await session.call_tool("browser_view", {})
        types = [c.type for c in view_result.content]
        assert "text" in types and "image" in types

        view_data = _result_json(view_result)
        assert view_data["success"] is True
        assert "example.com" in view_data["data"]["url"]
        # "screenshot" base64 KHONG con nam trong data JSON nua (review Opus)
        assert "screenshot" not in view_data["data"]

        image_items = [c for c in view_result.content if c.type == "image"]
        assert len(image_items) == 1
        image = image_items[0]
        assert image.mimeType == "image/jpeg"

        import base64
        import io

        raw = base64.b64decode(image.data)
        try:
            from PIL import Image as PILImage

            with PILImage.open(io.BytesIO(raw)) as im:
                assert im.width <= 1024
        except ImportError:  # pragma: no cover - Pillow luon co trong deps
            pass

    async def test_with_screenshot_param_adds_image(self):
        """10 tool đổi trạng thái khác chỉ kèm ảnh khi được yêu cầu rõ qua
        with_screenshot=True (review Opus PR #36)."""
        async with mcp_session() as session:
            await session.call_tool("browser_navigate", {"url": "https://example.com"})
            result = await session.call_tool("browser_scroll_down", {"to_bottom": True, "with_screenshot": True})
        types = [c.type for c in result.content]
        assert "text" in types and "image" in types


class TestProgressTools:
    async def test_plan_update_returns_confirmation(self):
        async with mcp_session() as session:
            result = await session.call_tool(
                "plan_update",
                {"steps": [{"id": "1", "status": "completed"}], "reflection": "pytest"},
            )
        text = _text_content(result).text
        assert "plan_update" in text

    async def test_message_notify_user_returns_confirmation(self):
        async with mcp_session() as session:
            result = await session.call_tool("message_notify_user", {"text": "pytest notify"})
        text = _text_content(result).text
        assert "message_notify_user" in text
