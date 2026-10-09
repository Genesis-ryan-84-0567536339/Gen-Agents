"""
12 tool browser (docs/spec/02-mcp-trong-sandbox.md mục 3.3), viết mới trong
MCP server — nối trực tiếp CDP Chrome (127.0.0.1:9222, đã forward qua socat
trong supervisord.conf) bằng playwright `connect_over_cdp` (không cần
`playwright install`: connect_over_cdp chỉ cần package pip, không cần tự
spawn browser — đã đo thật trên máy dev, xem bằng chứng PR).

Quyết định đã chốt (Claude điều phối, 09/10, sau review Opus, xem câu hỏi mở
số 1 trong spec 02): KHÔNG tái tạo cây phần tử `[index]<tag/>` — dùng
screenshot + toạ độ, cộng trợ giúp DOM tối thiểu (selector/text cho
click/input, selector cho select_option). Vì vậy tham số của
browser_click / browser_input / browser_select_option LỆCH so với bảng
tham số gốc ở mục 3.3 (tham số `index` được thay bằng `selector`/`text`) —
ghi trong mục "Lệch so với spec" cuối file spec 02.

Mỗi tool trả về dict dạng {success, message, data}. `data` của các tool làm
đổi trạng thái trang (navigate/restart/click/input/scroll/select_option/
press_key/move_mouse) gồm {url, title, screenshot} (screenshot: base64 PNG)
để CLI có phản hồi hình ảnh ngay mà không phải gọi thêm browser_view.
"""
import asyncio
import base64
import logging
from collections import deque
from typing import Any, Optional

from playwright.async_api import Page, async_playwright

from config import CDP_URL

logger = logging.getLogger("gen_agents.mcp.browser")

_CONSOLE_MAXLEN = 500


class BrowserSession:
    """Giữ 1 kết nối CDP + 1 tab đang theo dõi, tự kết nối lại khi cần."""

    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._page: Optional[Page] = None
        self._console: deque = deque(maxlen=_CONSOLE_MAXLEN)
        self._lock = asyncio.Lock()

    async def _connect(self) -> None:
        if self._pw is None:
            self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.connect_over_cdp(CDP_URL)
        logger.info("da ket noi CDP Chrome tai %s", CDP_URL)

    def _attach_console(self, page: Page) -> None:
        def _on_console(msg: Any) -> None:
            try:
                self._console.append(f"[{msg.type}] {msg.text}")
            except Exception:  # pragma: no cover - log phu
                pass

        page.on("console", _on_console)

    async def get_page(self) -> Page:
        async with self._lock:
            if self._browser is None or not self._browser.is_connected():
                await self._connect()
            if self._page is not None and not self._page.is_closed():
                return self._page
            contexts = self._browser.contexts
            ctx = contexts[0] if contexts else await self._browser.new_context()
            pages = [p for p in ctx.pages if not p.is_closed()]
            page = pages[0] if pages else await ctx.new_page()
            self._attach_console(page)
            self._page = page
            return page

    async def new_page(self) -> Page:
        """Mở tab mới, thay cho tab đang theo dõi (dùng cho browser_restart).

        LƯU Ý: không huỷ tiến trình Chrome (chrome do supervisord quản lý,
        dùng chung cho noVNC) — chỉ đổi sang một tab trống mới, xoá buffer
        console cũ. Đây là lệch nhẹ so với tên "restart" nhưng giữ đúng ý
        "reset trạng thái trang" mà không phá hạ tầng chung của sandbox.
        """
        async with self._lock:
            if self._browser is None or not self._browser.is_connected():
                await self._connect()
            contexts = self._browser.contexts
            ctx = contexts[0] if contexts else await self._browser.new_context()
            page = await ctx.new_page()
            self._attach_console(page)
            self._page = page
            self._console.clear()
            return page

    def console_lines(self, max_lines: Optional[int] = None):
        lines = list(self._console)
        if max_lines:
            lines = lines[-max_lines:]
        return lines


_session = BrowserSession()


def _err(message: str) -> dict:
    return {"success": False, "message": message}


async def _state_with_screenshot(page: Page) -> dict:
    try:
        screenshot_bytes = await page.screenshot(type="png")
        screenshot_b64 = base64.b64encode(screenshot_bytes).decode("ascii")
    except Exception as exc:  # pragma: no cover
        logger.warning("chup screenshot loi: %s", exc)
        screenshot_b64 = ""
    return {
        "url": page.url,
        "title": await _safe_title(page),
        "screenshot": screenshot_b64,
    }


async def _safe_title(page: Page) -> str:
    try:
        return await page.title()
    except Exception:
        return ""


async def _ok(page: Page, message: str) -> dict:
    data = await _state_with_screenshot(page)
    return {"success": True, "message": message, "data": data}


# ---------------------------------------------------------------------------
# 12 tool
# ---------------------------------------------------------------------------

async def browser_view() -> dict:
    """Xem nội dung trang hiện tại: trả về url, title, screenshot (base64 PNG)."""
    try:
        page = await _session.get_page()
        return await _ok(page, "Da chup man hinh trang hien tai")
    except Exception as exc:
        return _err(f"Khong xem duoc trang: {exc}")


async def browser_navigate(url: str) -> dict:
    """Điều hướng tới URL.

    Args:
        url: URL đầy đủ, có protocol (http/https).
    """
    try:
        page = await _session.get_page()
        await page.goto(url, wait_until="load", timeout=30000)
        return await _ok(page, f"Da dieu huong toi {url}")
    except Exception as exc:
        return _err(f"Dieu huong loi: {exc}")


async def browser_restart(url: str) -> dict:
    """Mở một tab mới (thay cho tab cũ) và điều hướng tới URL.

    Xem BrowserSession.new_page: không huỷ tiến trình Chrome của sandbox.

    Args:
        url: URL đầy đủ để mở sau khi reset.
    """
    try:
        page = await _session.new_page()
        await page.goto(url, wait_until="load", timeout=30000)
        return await _ok(page, f"Da mo tab moi va dieu huong toi {url}")
    except Exception as exc:
        return _err(f"Restart loi: {exc}")


async def browser_click(
    selector: Optional[str] = None,
    text: Optional[str] = None,
    coordinate_x: Optional[float] = None,
    coordinate_y: Optional[float] = None,
) -> dict:
    """Click vào phần tử trên trang.

    Vì v0.1 không tái tạo cây `[index]`, truyền MỘT trong ba cách:

    Args:
        selector: (Tuỳ chọn) CSS selector của phần tử cần click.
        text: (Tuỳ chọn) văn bản hiển thị của phần tử (khớp gần đúng, lấy phần tử đầu tiên).
        coordinate_x: (Tuỳ chọn) toạ độ X để click trực tiếp.
        coordinate_y: (Tuỳ chọn) toạ độ Y để click trực tiếp.
    """
    try:
        page = await _session.get_page()
        if selector:
            await page.click(selector, timeout=10000)
        elif text:
            await page.get_by_text(text, exact=False).first.click(timeout=10000)
        elif coordinate_x is not None and coordinate_y is not None:
            await page.mouse.click(coordinate_x, coordinate_y)
        else:
            return _err("Can truyen selector, text, hoac ca coordinate_x va coordinate_y")
        return await _ok(page, "Da click")
    except Exception as exc:
        return _err(f"Click loi: {exc}")


async def browser_input(
    text: str,
    press_enter: bool,
    selector: Optional[str] = None,
    coordinate_x: Optional[float] = None,
    coordinate_y: Optional[float] = None,
) -> dict:
    """Ghi đè nội dung văn bản vào phần tử có thể nhập trên trang.

    Args:
        text: Nội dung văn bản đầy đủ cần ghi đè.
        press_enter: Có nhấn Enter sau khi nhập hay không.
        selector: (Tuỳ chọn) CSS selector của ô nhập (ưu tiên nếu có).
        coordinate_x: (Tuỳ chọn) toạ độ X của ô nhập, dùng khi không có selector.
        coordinate_y: (Tuỳ chọn) toạ độ Y của ô nhập, dùng khi không có selector.
    """
    try:
        page = await _session.get_page()
        if selector:
            await page.fill(selector, text, timeout=10000)
        elif coordinate_x is not None and coordinate_y is not None:
            await page.mouse.click(coordinate_x, coordinate_y)
            await page.keyboard.press("Control+A")
            await page.keyboard.type(text)
        else:
            return _err("Can truyen selector hoac ca coordinate_x va coordinate_y")
        if press_enter:
            await page.keyboard.press("Enter")
        return await _ok(page, "Da nhap text")
    except Exception as exc:
        return _err(f"Input loi: {exc}")


async def browser_move_mouse(coordinate_x: float, coordinate_y: float) -> dict:
    """Di chuyển con trỏ chuột tới vị trí chỉ định.

    Args:
        coordinate_x: Toạ độ X.
        coordinate_y: Toạ độ Y.
    """
    try:
        page = await _session.get_page()
        await page.mouse.move(coordinate_x, coordinate_y)
        return await _ok(page, "Da di chuyen chuot")
    except Exception as exc:
        return _err(f"Move mouse loi: {exc}")


async def browser_press_key(key: str) -> dict:
    """Giả lập nhấn phím trên trang hiện tại.

    Args:
        key: Tên phím (vd Enter, Tab, ArrowUp), hỗ trợ tổ hợp (vd Control+Enter).
    """
    try:
        page = await _session.get_page()
        await page.keyboard.press(key)
        return await _ok(page, f"Da nhan phim {key}")
    except Exception as exc:
        return _err(f"Press key loi: {exc}")


async def browser_select_option(selector: str, option: int) -> dict:
    """Chọn option trong phần tử dropdown (<select>).

    LỆCH so với bảng tham số gốc: thay `index` (của cây [index]) bằng
    `selector` (CSS selector của phần tử <select>) vì v0.1 không tái tạo cây
    phần tử.

    Args:
        selector: CSS selector của phần tử <select>.
        option: Số thứ tự option cần chọn, bắt đầu từ 0.
    """
    try:
        page = await _session.get_page()
        await page.locator(selector).select_option(index=option, timeout=10000)
        return await _ok(page, f"Da chon option {option}")
    except Exception as exc:
        return _err(f"Select option loi: {exc}")


async def browser_scroll_up(to_top: Optional[bool] = None) -> dict:
    """Cuộn trang lên.

    Args:
        to_top: (Tuỳ chọn) cuộn thẳng lên đầu trang thay vì 1 viewport.
    """
    try:
        page = await _session.get_page()
        if to_top:
            await page.evaluate("window.scrollTo(0, 0)")
        else:
            await page.evaluate("window.scrollBy(0, -window.innerHeight)")
        return await _ok(page, "Da cuon len")
    except Exception as exc:
        return _err(f"Scroll up loi: {exc}")


async def browser_scroll_down(to_bottom: Optional[bool] = None) -> dict:
    """Cuộn trang xuống.

    Args:
        to_bottom: (Tuỳ chọn) cuộn thẳng xuống cuối trang thay vì 1 viewport.
    """
    try:
        page = await _session.get_page()
        if to_bottom:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        else:
            await page.evaluate("window.scrollBy(0, window.innerHeight)")
        return await _ok(page, "Da cuon xuong")
    except Exception as exc:
        return _err(f"Scroll down loi: {exc}")


async def browser_console_exec(javascript: str) -> dict:
    """Chạy JavaScript trong console của trang hiện tại.

    Args:
        javascript: Mã JavaScript cần chạy (chạy trong ngữ cảnh console trang).
    """
    try:
        page = await _session.get_page()
        result = await page.evaluate(javascript)
        try:
            import json

            json.dumps(result)
        except TypeError:
            result = str(result)
        return {"success": True, "message": "Da chay javascript", "data": {"result": result}}
    except Exception as exc:
        return _err(f"Console exec loi: {exc}")


async def browser_console_view(max_lines: Optional[int] = None) -> dict:
    """Xem log console của trang hiện tại.

    Args:
        max_lines: (Tuỳ chọn) số dòng log tối đa cần trả về (lấy mới nhất).
    """
    try:
        await _session.get_page()  # bảo đảm session còn sống
        logs = _session.console_lines(max_lines)
        return {"success": True, "message": f"Co {len(logs)} dong log", "data": {"logs": logs}}
    except Exception as exc:
        return _err(f"Console view loi: {exc}")
