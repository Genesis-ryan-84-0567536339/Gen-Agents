"""
Bọc tool API FastAPI hiện có của sandbox (127.0.0.1:8080) bằng httpx, dùng
cho 10 tool shell + file. Không nhân đôi logic session shell / ghi file —
tool API vẫn là nguồn sự thật (xem docs/spec/02-mcp-trong-sandbox.md mục 4,
phương án B).
"""
import logging
from typing import Any, Optional

import httpx

from config import TOOL_API_BASE, REST_TIMEOUT

logger = logging.getLogger("gen_agents.mcp.rest")

_client: Optional[httpx.AsyncClient] = None


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


async def _post(path: str, payload: dict) -> dict:
    """Gọi POST tới tool API, trả về dict dạng {success, message, data}.

    Không log payload đầy đủ (có thể chứa nội dung lệnh/file nhạy cảm) —
    chỉ log path + trạng thái, theo luật bảo mật mục 6 của spec 02.
    """
    client = _get_client()
    try:
        resp = await client.post(path, json=payload)
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
    return await _post("/shell/wait", {"id": id, "seconds": seconds})


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
    return await _post(
        "/file/replace",
        {"file": file, "old_str": old_str, "new_str": new_str, "sudo": sudo},
    )


async def file_find_in_content(file: str, regex: str, sudo: Optional[bool] = False) -> dict:
    return await _post("/file/search", {"file": file, "regex": regex, "sudo": sudo})


async def file_find_by_name(path: str, glob: str) -> dict:
    return await _post("/file/find", {"path": path, "glob": glob})
