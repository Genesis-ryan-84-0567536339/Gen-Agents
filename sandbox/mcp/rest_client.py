"""
Bọc tool API FastAPI hiện có của sandbox (127.0.0.1:8080) bằng httpx, dùng
cho 10 tool shell + file. Không nhân đôi logic session shell / ghi file —
tool API vẫn là nguồn sự thật (xem docs/spec/02-mcp-trong-sandbox.md mục 4,
phương án B).
"""
import logging
import os
from typing import Any, Optional

import httpx

from config import TOOL_API_BASE, REST_TIMEOUT

logger = logging.getLogger("gen_agents.mcp.rest")

_client: Optional[httpx.AsyncClient] = None

# Chan file/file toolkit cham vao thu muc phien dang nhap CLI hoac file he
# thong nhay cam — luat cung muc 7 cua docs/spec/00-tong-quan.md ("token
# dang nhap CLI chi song trong HOME tam... cam tool file/lenh cua CLI doc
# thu muc phien dang nhap"). Kiem tra don gian theo duong dan (khong duyet
# sau vao glob/symlink phuc tap) — chan truy cap TRUC TIEP, khong phai pham
# vi bao mat day du.
_FORBIDDEN_DIRS = [
    os.path.realpath(os.path.expanduser("~/.gemini")),
    os.path.realpath(os.path.expanduser("~/.claude")),
    os.path.realpath(os.path.expanduser("~/.gen-agents")),
]
_FORBIDDEN_FILES = [os.path.realpath("/etc/shadow")]
_FORBIDDEN_MESSAGE = "Duong dan bi cam boi luat cung §7 (docs/spec/00-tong-quan.md muc 7): khong duoc doc/ghi thu muc phien dang nhap CLI hoac file he thong nhay cam."


def _is_forbidden_path(raw_path: Optional[str]) -> bool:
    if not raw_path:
        return False
    normalized = os.path.realpath(os.path.expanduser(raw_path))
    if normalized in _FORBIDDEN_FILES:
        return True
    for forbidden in _FORBIDDEN_DIRS:
        if normalized == forbidden or normalized.startswith(forbidden + os.sep):
            return True
    return False


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=TOOL_API_BASE, timeout=REST_TIMEOUT)
    return _client


async def aclose() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def _post(path: str, payload: dict, timeout: Optional[float] = None) -> dict:
    """Gọi POST tới tool API, trả về dict dạng {success, message, data}.

    Không log payload đầy đủ (có thể chứa nội dung lệnh/file nhạy cảm) —
    chỉ log path + trạng thái, theo luật bảo mật mục 6 của spec 02.

    `timeout`: ghi đè timeout HTTP mặc định (REST_TIMEOUT) cho MỘT lần gọi —
    cần cho shell_wait vì tool API có thể tự chờ lâu hơn REST_TIMEOUT (xem
    shell_wait bên dưới).
    """
    client = _get_client()
    # QUAN TRONG: httpx coi `timeout=None` tuong minh la "KHONG gioi han
    # thoi gian" (khac voi khong truyen timeout, luc do dung default cua
    # client = REST_TIMEOUT). Chi truyen kwarg timeout khi THAT SU co gia
    # tri ghi de (shell_wait) — tranh vo tinh tat REST_TIMEOUT cho moi tool
    # con lai.
    post_kwargs = {"json": payload}
    if timeout is not None:
        post_kwargs["timeout"] = timeout
    try:
        resp = await client.post(path, **post_kwargs)
    except httpx.HTTPError as exc:
        logger.warning("goi tool API %s loi ket noi", path)
        return {"success": False, "message": f"Khong goi duoc tool API sandbox ({path}): {exc}"}

    try:
        body: Any = resp.json()
    except ValueError:
        logger.warning("tool API %s tra ve %s khong phai JSON", path, resp.status_code)
        return {
            "success": False,
            "message": f"tool API tra ve HTTP {resp.status_code} khong phai JSON",
        }

    if resp.status_code >= 400:
        message = body.get("message") if isinstance(body, dict) else str(body)
        logger.info("tool API %s tra ve HTTP %s", path, resp.status_code)
        return {"success": False, "message": message or f"HTTP {resp.status_code}", "data": body}

    logger.info("tool API %s thanh cong", path)
    if isinstance(body, dict):
        return body
    return {"success": True, "data": body}


# ---------------------------------------------------------------------------
# Shell (5 tool) — ánh xạ 1-1 sandbox/app/api/v1/shell.py
# ---------------------------------------------------------------------------

async def shell_exec(id: Optional[str], exec_dir: Optional[str], command: str) -> dict:
    return await _post("/shell/exec", {"id": id, "exec_dir": exec_dir, "command": command})


async def shell_view(id: str) -> dict:
    return await _post("/shell/view", {"id": id})


async def shell_wait(id: str, seconds: Optional[int] = None) -> dict:
    """Timeout HTTP = seconds (hoac 60s mac dinh cua tool API khi khong
    truyen) + 15s de du cho tool API tu cho het thoi gian roi tra loi —
    REST_TIMEOUT chung (30s) qua ngan cho lenh cho lau (vd seconds=35),
    da gay loi httpx.ReadTimeout truoc khi tool API kip tra ve (phat hien
    o review Opus PR #36, xem test_shell_wait_long trong
    sandbox/tests/test_mcp_tools.py)."""
    effective_seconds = seconds if seconds is not None else 60
    return await _post(
        "/shell/wait",
        {"id": id, "seconds": seconds},
        timeout=effective_seconds + 15,
    )


async def shell_write_to_process(id: str, input: str, press_enter: bool) -> dict:
    return await _post("/shell/write", {"id": id, "input": input, "press_enter": press_enter})


async def shell_kill_process(id: str) -> dict:
    return await _post("/shell/kill", {"id": id})


# ---------------------------------------------------------------------------
# File (5 tool) — ánh xạ 1-1 sandbox/app/api/v1/file.py
# ---------------------------------------------------------------------------

async def file_read(
    file: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
    sudo: Optional[bool] = False,
) -> dict:
    if _is_forbidden_path(file):
        return {"success": False, "message": _FORBIDDEN_MESSAGE}
    return await _post(
        "/file/read",
        {"file": file, "start_line": start_line, "end_line": end_line, "sudo": sudo},
    )


async def file_write(
    file: str,
    content: str,
    append: Optional[bool] = False,
    leading_newline: Optional[bool] = False,
    trailing_newline: Optional[bool] = False,
    sudo: Optional[bool] = False,
) -> dict:
    if _is_forbidden_path(file):
        return {"success": False, "message": _FORBIDDEN_MESSAGE}
    return await _post(
        "/file/write",
        {
            "file": file,
            "content": content,
            "append": append,
            "leading_newline": leading_newline,
            "trailing_newline": trailing_newline,
            "sudo": sudo,
        },
    )


async def file_str_replace(file: str, old_str: str, new_str: str, sudo: Optional[bool] = False) -> dict:
    if _is_forbidden_path(file):
        return {"success": False, "message": _FORBIDDEN_MESSAGE}
    return await _post(
        "/file/replace",
        {"file": file, "old_str": old_str, "new_str": new_str, "sudo": sudo},
    )


async def file_find_in_content(file: str, regex: str, sudo: Optional[bool] = False) -> dict:
    if _is_forbidden_path(file):
        return {"success": False, "message": _FORBIDDEN_MESSAGE}
    return await _post("/file/search", {"file": file, "regex": regex, "sudo": sudo})


async def file_find_by_name(path: str, glob: str) -> dict:
    if _is_forbidden_path(path):
        return {"success": False, "message": _FORBIDDEN_MESSAGE}
    return await _post("/file/find", {"path": path, "glob": glob})
