"""
3 tool "tiến độ & hỏi người dùng" (docs/spec/02-mcp-trong-sandbox.md mục 3.4):
plan_update, message_ask_user, message_notify_user.

Đợt 1: chỉ ghi sự kiện ra file NDJSON cục bộ trong máy nhiệm vụ
(~/.gen-agents/events.ndjson) và trả về một chuỗi xác nhận cho CLI. Backend
đọc file này để vẽ Plan/WaitEvent là việc của đợt 2 (CliEngineFlow) — spec
mục 7 phương án (A) nói Redis stream, nhưng ở đợt 1 chưa có CliEngineFlow nào
subscribe, nên ghi NDJSON cục bộ trước (rẻ, không cần Redis client trong
sandbox), đợt 2 đổi nguồn ghi (hoặc thêm) sang Redis XADD khi cần — xem mục
"Lệch so với spec" trong docs/spec/02-mcp-trong-sandbox.md.
"""
import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from config import EVENTS_DIR, EVENTS_FILE

logger = logging.getLogger("gen_agents.mcp.progress")

_write_lock = asyncio.Lock()


def _ensure_events_dir() -> None:
    os.makedirs(EVENTS_DIR, exist_ok=True)
    try:
        os.chmod(EVENTS_DIR, 0o700)
    except OSError:
        pass


async def _append_event(tool: str, args: Dict[str, Any]) -> None:
    _ensure_events_dir()
    line = json.dumps({"ts": time.time(), "tool": tool, "args": args}, ensure_ascii=False)
    async with _write_lock:
        # ghi đồng bộ (file nhỏ, NDJSON) nhưng giữ lock để không interleave
        with open(EVENTS_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    logger.info("da ghi event %s vao %s", tool, EVENTS_FILE)


async def plan_update(steps: List[Dict[str, Any]], reflection: str = "") -> str:
    """Cập nhật tiến độ Plan cho UI. Xem PlanToolkit.plan_report (plan.py:30).

    Args:
        steps: danh sách đầy đủ các bước {id, status, ...} hiện biết.
        reflection: (tuỳ chọn) nhận xét ngắn tổng thể.
    """
    await _append_event("plan_update", {"steps": steps, "reflection": reflection or ""})
    return f"Da ghi nhan plan_update ({len(steps)} buoc)."


async def message_ask_user(
    text: str,
    attachments: Optional[Any] = None,
    suggest_user_takeover: Optional[str] = None,
) -> str:
    """Hỏi người dùng và chờ trả lời. Xem MessageToolkit.message_ask_user (message.py:39).

    Args:
        text: câu hỏi hiển thị cho người dùng.
        attachments: (tuỳ chọn) file/tài liệu liên quan tới câu hỏi.
        suggest_user_takeover: (tuỳ chọn) "none" hoặc "browser".
    """
    await _append_event(
        "message_ask_user",
        {"text": text, "attachments": attachments, "suggest_user_takeover": suggest_user_takeover},
    )
    return "Da ghi nhan message_ask_user, dang cho nguoi dung tra loi."


async def message_notify_user(text: str) -> str:
    """Gửi thông báo cho người dùng, không cần phản hồi. Xem MessageToolkit.message_notify_user (message.py:25).

    Args:
        text: nội dung thông báo.
    """
    await _append_event("message_notify_user", {"text": text})
    return "Da ghi nhan message_notify_user."
