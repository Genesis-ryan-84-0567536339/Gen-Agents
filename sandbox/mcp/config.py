"""
Cấu hình cho MCP server chạy trong máy nhiệm vụ (sandbox).

LƯU Ý QUAN TRỌNG VỀ IMPORT: thư mục này tên là `mcp` (theo yêu cầu Issue #29),
trùng tên với package pip `mcp` (MCP SDK chính thức). Để tránh việc Python
coi thư mục này là package `mcp` và che khuất SDK thật, KHÔNG được thêm
`__init__.py` vào đây và KHÔNG được chạy script trong thư mục này với
`/app` nằm trên `sys.path` (ví dụ không dùng `python -m mcp.server` từ
`/app`). Cách chạy đúng: `python mcp/server.py` với cwd=`/app` — CPython chỉ
thêm `/app/mcp` (thư mục chứa script) vào `sys.path[0]`, không thêm `/app`,
nên `import mcp` bên trong vẫn trỏ đúng tới SDK trong site-packages của venv.
Xem thêm phần "Lệch so với spec" trong `docs/spec/02-mcp-trong-sandbox.md`.
"""
import os

# Tool API FastAPI hiện có của sandbox (shell/file) — xem sandbox/app/main.py
TOOL_API_BASE = os.environ.get("TOOL_API_BASE", "http://127.0.0.1:8080/api/v1")

# CDP Chrome, forward qua socat trong supervisord.conf (chrome thật nghe ở
# 8222, socat forward 9222 -> 8222)
CDP_URL = os.environ.get("CDP_URL", "http://127.0.0.1:9222")

# Bind của chính MCP server này — chỉ localhost, không expose ra ngoài container
MCP_HOST = os.environ.get("MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.environ.get("MCP_PORT", "8081"))

# File NDJSON mà 3 tool plan_update/message_ask_user/message_notify_user ghi
# sự kiện vào — backend (đợt 2) sẽ đọc file này để vẽ Plan/WaitEvent. Đợt 1
# chỉ ghi, chưa có backend đọc.
EVENTS_DIR = os.environ.get("GEN_AGENTS_EVENTS_DIR", os.path.expanduser("~/.gen-agents"))
EVENTS_FILE = os.path.join(EVENTS_DIR, "events.ndjson")

# Timeout gọi REST tool API nội bộ (giây)
REST_TIMEOUT = float(os.environ.get("MCP_REST_TIMEOUT", "30"))
