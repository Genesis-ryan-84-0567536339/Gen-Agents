# 02 — MCP server trong sandbox nhiệm vụ

> Thiết kế cách CLI engine (agy / Claude Code) gọi tool trong sandbox qua một
> MCP server chạy ngay trong container nhiệm vụ. Xem `00-tong-quan.md` cho
> bối cảnh kiến trúc 3 lớp.

## 1. Vì sao cần MCP server trong sandbox (không chỉ gọi lại tool Python cũ)

Tool hiện có (`ShellToolkit`, `FileToolkit`, `BrowserToolkit` trong
`backend/app/domain/services/tools/`) được LangChain gọi từ **backend**, qua
REST tới sandbox (`docker_sandbox.py`). CLI engine thì chạy **trong chính
sandbox** (mục 5, `00-tong-quan.md`) — nó cần một giao diện tool theo chuẩn
MCP (cả agy và Claude Code đều nói MCP), và giao diện đó phải sống cạnh nó
trong container, không vòng ra lại backend cho mỗi lần gọi tool (chậm, và làm
backend lại phải biết chi tiết của từng loại CLI).

## 2. Transport

Đề xuất: **streamable-http trên cổng nội bộ `127.0.0.1:8081`** trong
container, cộng thêm **stdio** như lối vào thứ hai cho CLI nào thích tự
spawn subprocess hơn trỏ URL.

- streamable-http là transport mà `MCPClientManager` phía backend đã hỗ trợ
  (`backend/app/domain/services/tools/mcp.py:156`
  `_connect_streamable_http_server`) — dùng lại đúng pattern, không phát
  minh transport mới.
- Cổng `8081` không trùng `8080` (tool API FastAPI hiện có,
  `sandbox/app/main.py`), `8222`/`9222` (CDP Chrome), `5900`/`5901` (VNC).
- stdio phù hợp khi CLI launcher thích chạy `command` trực tiếp
  (`MCPServerConfig.command`,
  `backend/app/domain/models/mcp_config.py:17`) thay vì gọi URL — cả hai lối
  vào gọi chung một implementation Python, không phải viết 2 lần.

## 3. Danh sách tool phơi ra — ánh xạ 1-1 từ tool hiện có

MCP server **không** phơi `skill` (CLI đọc skill từ file hướng dẫn gốc, xem
`03-cau-hinh-thuoc-harness.md` mục 1) và không phơi `mcp` (tool đó chính là cơ
chế MCP, không gọi lồng MCP vào MCP). Phơi 3 nhóm tool chạm tài nguyên thật
trong sandbox — shell, file, browser — cộng nhóm "nói với người dùng"
(`plan_update`, `message_ask_user`, `message_notify_user`) mà `01-dong-co-cli.md`
mục 5 đặt là **bắt buộc**: không có chúng thì UI không vẽ được tiến độ và phiên
không dừng chờ được đúng chỗ.

### 3.1 Shell (từ `backend/app/domain/services/tools/shell.py`)

| Tool MCP | Nguồn | Dòng | Tham số |
| --- | --- | --- | --- |
| `shell_exec` | `ShellToolkit.shell_exec` | `shell.py:35` | `id`, `exec_dir`, `command` |
| `shell_view` | `ShellToolkit.shell_view` | `shell.py:49` | `id` |
| `shell_wait` | `ShellToolkit.shell_wait` | `shell.py:59` | `id`, `seconds` |
| `shell_write_to_process` | `ShellToolkit.shell_write_to_process` | `shell.py:74` | `id`, `input`, `press_enter` |
| `shell_kill_process` | `ShellToolkit.shell_kill_process` | `shell.py:88` | `id` |

### 3.2 File (từ `backend/app/domain/services/tools/file.py`)

| Tool MCP | Nguồn | Dòng | Tham số |
| --- | --- | --- | --- |
| `file_read` | `FileToolkit.file_read` | `file.py:30` | `file`, `start_line`, `end_line`, `sudo` |
| `file_write` | `FileToolkit.file_write` | `file.py:54` | `file`, `content`, `append`, `leading_newline`, `trailing_newline`, `sudo` |
| `file_str_replace` | `FileToolkit.file_str_replace` | `file.py:91` | `file`, `old_str`, `new_str`, `sudo` |
| `file_find_in_content` | `FileToolkit.file_find_in_content` | `file.py:115` | `file`, `regex`, `sudo` |
| `file_find_by_name` | `FileToolkit.file_find_by_name` | `file.py:136` | `path`, `glob` |

### 3.3 Browser (từ `backend/app/domain/services/tools/browser.py`)

| Tool MCP | Nguồn | Dòng | Tham số |
| --- | --- | --- | --- |
| `browser_view` | `BrowserToolkit.browser_view` | `browser.py:30` | — |
| `browser_navigate` | `BrowserToolkit.browser_navigate` | `browser.py:36` | `url` |
| `browser_restart` | `BrowserToolkit.browser_restart` | `browser.py:45` | `url` |
| `browser_click` | `BrowserToolkit.browser_click` | `browser.py:54` | `index`, `coordinate_x`, `coordinate_y` |
| `browser_input` | `BrowserToolkit.browser_input` | `browser.py:70` | `text`, `press_enter`, `index`, `coordinate_x`, `coordinate_y` |
| `browser_move_mouse` | `BrowserToolkit.browser_move_mouse` | `browser.py:90` | `coordinate_x`, `coordinate_y` |
| `browser_press_key` | `BrowserToolkit.browser_press_key` | `browser.py:104` | `key` |
| `browser_select_option` | `BrowserToolkit.browser_select_option` | `browser.py:116` | `index`, `option` |
| `browser_scroll_up` | `BrowserToolkit.browser_scroll_up` | `browser.py:130` | `to_top` |
| `browser_scroll_down` | `BrowserToolkit.browser_scroll_down` | `browser.py:142` | `to_bottom` |
| `browser_console_exec` | `BrowserToolkit.browser_console_exec` | `browser.py:154` | `javascript` |
| `browser_console_view` | `BrowserToolkit.browser_console_view` | `browser.py:166` | `max_lines` |

### 3.4 Tiến độ & hỏi người dùng (tool mới, ngữ nghĩa lấy từ backend)

| Tool MCP | Nguồn ngữ nghĩa | Dòng | Tham số |
| --- | --- | --- | --- |
| `plan_update` | `PlanToolkit.plan_report` (đổi tên cho CLI) | `plan.py:30` | `steps[]`, `reflection` |
| `message_ask_user` | `MessageToolkit.message_ask_user` | `message.py:39` | theo nguyên bản |
| `message_notify_user` | `MessageToolkit.message_notify_user` | `message.py:25` | theo nguyên bản |

Ba tool này không gọi lại REST :8080 (sandbox không biết `session_id` phía
harness) — chúng là lối duy nhất MCP server phải báo về backend, nên dùng
phương án (A) của mục 7 (Redis stream theo `session_id`) *chỉ cho nhóm này*.

Tổng 25 tool (5 shell + 5 file + 12 browser + 3 tiến độ/hỏi người dùng); 22
tool đầu không đổi tên, không đổi tham số — CLI học đúng ngữ nghĩa đã có
tài liệu (`instructions` trong mỗi `Toolkit`, ví dụ `shell.py:10-16`,
`file.py:10-18`, `browser.py:10-18`), tránh phải viết lại prompt hướng dẫn.

## 4. Cách bọc — gọi lại REST :8080 nội bộ, không import module sandbox

Hai phương án:

- **(A) Import trực tiếp `app.services.shell`/`app.services.file`** của
  sandbox (`sandbox/app/services/`) — tránh một vòng HTTP, nhưng MCP server
  và tool API FastAPI hiện có phải chạy *cùng process* hoặc chia sẻ state
  (session id shell, v.v.), kéo theo đổi kiến trúc sandbox hiện tại.
- **(B) Gọi lại REST `http://127.0.0.1:8080/api/v1/{shell,file}/...`** —
  đúng route đã có (`sandbox/app/api/v1/shell.py`, `sandbox/app/api/v1/file.py`,
  router gắn prefix tại `sandbox/app/api/router.py:6-8`), MCP server là một
  process Python độc lập, chỉ cần `httpx` gọi localhost.

**Đề xuất (B).** Lý do: tool API hiện tại đã là nguồn sự thật cho shell/file
(giữ session shell, ghi log), không nhân đôi logic; MCP server đổi/triển
khai lại không ảnh hưởng process FastAPI chính đang chạy ổn. Browser không có
REST tương ứng trong sandbox hiện tại (browser tool của ai-manus chạy ở
**backend** qua `BrowserUseBrowser`/`PlaywrightBrowser`, không qua tool API
8080) — MCP server nối CDP Chrome (`http://127.0.0.1:9222`, đã mở sẵn qua
`socat` trong `supervisord.conf`) trực tiếp bằng một thư viện CDP (ví dụ
`playwright` connect qua `cdp_url`), implement lại 12 tool browser ở mục
3.3 là code mới trong MCP server — không tái dùng được
`infrastructure/external/browser/*` của backend (nó chạy ngoài container).

## 5. Cách CLI trỏ tới MCP server

- **agy (Antigravity CLI)** — đã đo trên agy v1.3.2: harness ghi file
  `<HOME tạm>/.gemini/config/mcp_config.json`, khoá gốc `mcpServers`:
  ```json
  { "mcpServers": { "sandbox": { "url": "http://127.0.0.1:8081/mcp" } } }
  ```
- **Claude Code CLI** — đã đo trên claude v2.1.295: harness ghi
  `<HOME tạm>/mcp.json` (cùng schema trên) và truyền
  `--mcp-config <HOME tạm>/mcp.json --strict-mcp-config` lúc chạy, để CLI
  không nạp thêm cấu hình MCP nào khác. Không dùng `.mcp.json` ở thư mục làm
  việc (dễ bị cấu hình khác chồng lên).

Cả hai file do harness render ra sandbox trước khi chạy CLI — xem
`03-cau-hinh-thuoc-harness.md` mục "cấu hình MCP".

Một bản cấu hình MCP **gốc** duy nhất (chứa đúng 1 server "sandbox" ở đây),
harness render ra đúng định dạng từng CLI cần — không phải 2 nguồn sự thật.

## 6. Bảo mật

- MCP server **chỉ bind `127.0.0.1`** trong container — không map port
  `8081` ra ngoài container (so với `9222`/`8080`/`5900`/`5901` hiện có là
  cổng `EXPOSE` trong `sandbox/Dockerfile:103`, không thêm `8081` vào danh
  sách đó).
- Vì CLI process và MCP server cùng nằm trong một container (cùng network
  namespace), bind `127.0.0.1` vẫn truy cập được giữa chúng — không cần expose
  ra host, không cần ra ngoài Docker network.
- MCP server chạy bằng user `ubuntu` (giống `program:app` trong
  `supervisord.conf`), không chạy bằng root — không mở thêm bề mặt sudo.
- Không log nội dung file/lệnh nhạy cảm ra `stdout_logfile=/dev/stdout` của
  supervisord mặc định (log đó đi vào log Docker container, có thể bị đọc
  bởi ai truy cập host) — chỉ log tên tool + trạng thái thành công/thất bại,
  không log `content`/`command` đầy đủ ở mức info.

## 7. Cách harness vẫn nhận được sự kiện tool

Flow (`CliEngineFlow`, mục 5 của `00-tong-quan.md`) cần biết *đang* có tool
nào chạy để phát `ToolEvent`/`TerminalUpdateEvent`/`FileUpdateEvent` cho
frontend thời gian thực — không chỉ đợi tới khi CLI in ra NDJSON cuối. Hai
phương án:

- **(A) MCP server tự phát sự kiện về backend qua Redis stream.** Mỗi lần
  tool được gọi, MCP server `XADD` vào một Redis stream theo `session_id`
  (Redis đã có sẵn trong hạ tầng — `infrastructure/storage/redis.py`,
  backend đã dùng để pub/sub cho `ws_routes.py`). Backend subscribe stream đó
  song song với việc đọc NDJSON của CLI, hợp nhất 2 nguồn sự kiện theo
  timestamp.
- **(B) Backend chỉ đọc NDJSON của chính CLI, không cần Redis thêm.** Cả agy
  và Claude Code CLI với cờ `--output-format stream-json` đều tự in ra dòng
  JSON mỗi khi gọi tool (tool_use/tool_result) — vì MCP server và CLI nằm
  trong cùng tiến trình luồng lệnh mà backend đang `exec_command` + đọc
  stdout, backend ánh xạ trực tiếp dòng NDJSON đó sang `ToolEvent` mà không
  cần kênh phụ.

**Đề xuất: (B) cho shell/file/browser, (A) cho 3 tool tiến độ/hỏi người dùng
(mục 3.4).** Lý do: NDJSON của CLI *đã* chứa đủ thông tin tool_use/tool_result
để tái tạo `ToolEvent` (đã đo với cả hai CLI — xem `01-dong-co-cli.md` mục
3–4), nên không cần kênh phụ cho 22 tool kia; còn `plan_update` /
`message_ask_user` / `message_notify_user` phải *tác động* vào trạng thái phiên
ở harness (vẽ Plan, chuyển sang `WAITING`), nên chúng `XADD` vào Redis stream
theo `session_id` (`infrastructure/storage/redis.py`, đường pub/sub mà
`ws_routes.py` đã dùng). Backend hợp nhất 2 nguồn theo timestamp; vì nhóm (A)
chỉ có 3 tool nên chỗ có thể lệch thứ tự rất nhỏ.

## 8. Test nghiệm thu

- [ ] Từ trong container sandbox, `curl -X POST http://127.0.0.1:8081/mcp
      -d '{"method":"tools/list"}'` (hoặc lệnh MCP tương đương) trả về đúng
      25 tool ở mục 3, đúng tên/tham số khớp bảng.
- [ ] Gọi `shell_exec` qua MCP với `command="echo hello"` → nhận kết quả
      đúng với gọi trực tiếp REST `/api/v1/shell/exec` cùng tham số (đối
      chiếu `ToolResult`).
- [ ] Gọi `browser_navigate` qua MCP tới một URL thật → Chrome trong noVNC
      (cổng 5901) đổi trang thấy bằng mắt.
- [ ] Từ máy host, `curl http://<ip-container>:8081` KHÔNG kết nối được
      (xác nhận chỉ bind localhost trong container).
- [ ] Claude Code CLI chạy trong sandbox với `--mcp-config <HOME tạm>/mcp.json
      --strict-mcp-config` trỏ server này, gọi
      `load_skill`-tương-đương hoặc một tool bất kỳ, backend nhận đúng
      `ToolEvent` tương ứng trên WebSocket `/api/v1/ws/chat`.
- [ ] agy chạy trong sandbox, cấu hình MCP qua
      `~/.gemini/config/mcp_config.json`, gọi `file_write` → file xuất hiện đúng path trong container,
      đọc lại bằng `file_read` qua MCP thấy đúng nội dung.

## Câu hỏi mở

1. ~~Browser tool giữ ngữ nghĩa `[index]<tag/>` hay screenshot + toạ độ?~~
   **Đã chốt (Claude điều phối, 09/10, sau review Opus):** v0.1 MCP browser
   **không** tái tạo cây phần tử `[index]`; dùng **screenshot + toạ độ** cộng
   bộ trợ giúp DOM tối thiểu qua CDP (`click` theo selector/văn bản hiển
   thị, `input` theo selector, `scroll`, `console_exec`, `view` trả
   screenshot + URL + tiêu đề). Lý do: CLI đã có cách nhìn trang riêng, tránh
   nuôi hai bản `browser_use`. UI chấp nhận hai dạng `BrowserToolContent`
   (dạng cũ của `plan_act` và dạng mới screenshot-first); ghi rõ trong
   `frontend/src/components/toolViews/` khi thi công đợt 1.
2. Khi hai tool `shell_exec` chạy đồng thời trong cùng sandbox (một từ CLI
   qua MCP, một tool nội bộ khác nếu có) có cần một `exec_dir`/session-id
   namespace riêng để tránh đụng session shell không?
3. ~~Liệu NDJSON của CLI có đủ chi tiết tool_use/tool_result?~~ **Đã đo:**
   agy v1.3.2 in `step_update{step_type:"tool"}` với `tool_name` +
   `tool_info.parameters` (ACTIVE) và `tool_info.output` (DONE); Claude Code
   v2.1.295 in `assistant.content[].tool_use` + `user.tool_result`. Đủ cho (B)
   với cả hai — xem `01-dong-co-cli.md` mục 3–4.

## Lệch so với spec và lý do (thi công đợt 1, Issue #29)

Ghi lại đúng chỗ thực tế thi công buộc khác với mô tả ở các mục trên, theo
yêu cầu mục cuối Issue #29. Không có mục nào đổi *ý định* của spec, chỉ đổi
chi tiết triển khai.

1. **Tham số `browser_click` / `browser_input` / `browser_select_option`
   thay `index` bằng `selector`/`text`.** Hệ quả trực tiếp của quyết định đã
   chốt ở "Câu hỏi mở" #1 (không tái tạo cây `[index]`) — ghi lại ở đây vì
   bảng tham số gốc mục 3.3 vẫn còn liệt kê `index` cho 3 tool này.
   `browser_click(selector?, text?, coordinate_x?, coordinate_y?)`,
   `browser_input(text, press_enter, selector?, coordinate_x?, coordinate_y?)`,
   `browser_select_option(selector, option)`. Xem `sandbox/mcp/browser_tools.py`.
2. **`browser_restart` không khởi động lại tiến trình Chrome** — Chrome do
   supervisord quản lý chung cho noVNC, huỷ tiến trình sẽ ảnh hưởng phiên
   VNC đang xem. Thay vào đó mở một tab mới (xoá buffer console, đổi trang
   đang theo dõi) rồi điều hướng tới URL — đủ ngữ nghĩa "reset trạng thái
   trang" mà tool này cần, không phá hạ tầng chung.
3. **`plan_update`/`message_ask_user`/`message_notify_user` ghi NDJSON cục
   bộ (`~/.gen-agents/events.ndjson`) ở đợt 1, chưa dùng Redis stream như
   phương án (A) mục 7.** Lý do: CliEngineFlow (đợt 2) — bên duy nhất cần
   đọc sự kiện này — chưa tồn tại; thêm Redis client vào sandbox ngay bây
   giờ là build cho một người đọc chưa có. Đợt 2 đổi nguồn ghi (hoặc thêm
   XADD song song) khi CliEngineFlow sẵn sàng subscribe theo `session_id`.
4. **Program `mcp` trong supervisord chạy bằng
   `/app/.venv/bin/python mcp/server.py` thay vì `uv run ...`.** Tool API
   (`program:app`) dùng `uv run uvicorn ...`; MCP server gọi trực tiếp
   Python của venv đã có sẵn (do `uv sync` dựng ở bước build image) để
   tránh `uv` phải resolve lại project mỗi lần start với `directory` khác
   — và quan trọng hơn: giữ đúng quy ước sys.path ở mục "Bảo mật" (chạy
   bằng đường dẫn script tương đối `mcp/server.py` từ `directory=/app` để
   `sys.path[0]` là `/app/mcp`, không phải `/app` — tránh thư mục `mcp/` này
   che khuất gói pip `mcp`, xem `sandbox/mcp/config.py`).
5. **Bỏ gói `sudo` khỏi image, không chỉ bỏ NOPASSWD.** Luật cứng mục 6 của
   `00-tong-quan.md` chỉ nói "bỏ sudo NOPASSWD"; đợt 1 đi xa hơn một chút —
   không cài gói `sudo` cho image nữa (không chỉ bỏ quyền). Hệ quả: tham số
   `sudo=true` của `file_read`/`file_write` (`FileToolkit`, kế thừa từ
   `backend/app/domain/services/tools/file.py`) sẽ thất bại với lỗi
   "command not found" thay vì chạy được — chấp nhận được vì luật cứng đã
   chủ ý loại bỏ đường leo thang quyền này; CLI/agent không nên trông cậy
   `sudo=true` trong sandbox v0.1.
6. **User `browser` chạy Chrome (khác `ubuntu`) — đã kiểm chạy thật trong
   container, xem bằng chứng (c) trong PR**: `supervisorctl status` các
   program `chrome`/`x11vnc`/`socat` đều RUNNING, và `browser_navigate` qua
   MCP vẫn điều khiển được đúng Chrome đó (CDP không cần xác thực vì Xvfb
   không chạy `-auth`). Nếu bằng chứng cho thấy ngược lại, mục này sẽ được
   sửa lại và ghi rõ lý do giữ nguyên `chrome` chạy root như trước.
7. **Mở thêm một ngoại lệ CHỈ cho dev/CI vào luật "chỉ bind 127.0.0.1,
   không expose 8081" của mục 6.** `.github/workflows/tests.yml` (bước
   "Sandbox API tests") chạy `cd sandbox && uv run pytest -q` **trực tiếp
   trên runner**, không qua `docker exec` vào container — runner không thể
   với tới cổng chỉ bind `127.0.0.1` BÊN TRONG container. Vì vậy
   `docker-compose-development.yml` (CHỈ file dev, không đụng
   `docker-compose.yml` production) map thêm `"127.0.0.1:8081:8081"` cho
   service `sandbox` và đặt `GEN_AGENTS_MCP_BIND=0.0.0.0` — biến môi
   trường mới, MCP server đọc trong `sandbox/mcp/config.py` để quyết định
   địa chỉ bind, mặc định vẫn `127.0.0.1` khi KHÔNG đặt biến này. Container
   nhiệm vụ thật (`docker-compose.yml`/`docker_sandbox.py`) không đặt biến
   này nên không đổi hành vi — MCP server ở đó vẫn chỉ bind `127.0.0.1`
   trong container, và host-side mapping trong `docker-compose-development.yml`
   cũng chỉ mở ra `127.0.0.1` của máy dev/runner (không phải `0.0.0.0`),
   không lộ ra mạng ngoài.
