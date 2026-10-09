# Bằng chứng đợt 1 (Issue #29)

## (a) Test 25 tool qua client MCP thật — PASS

- `pytest-local-pre-docker.txt`: `pytest tests/test_mcp_tools.py -v` chạy
  cục bộ (ngoài container) trước khi build Docker, nối MCP server tới tool
  API thật (`uv run uvicorn app.main:app`) + Chrome CDP thật
  (`google-chrome --headless=new --remote-debugging-port=19222`, cổng tách
  riêng khỏi `9222` thật của máy dev để không đụng trình duyệt khác đang mở).
  8/8 PASS.
- `pytest-in-container.txt`: **cùng bộ test, chạy THẬT bên trong container
  `sandbox` đã build** (`docker exec -u ubuntu ... .venv/bin/python -m
  pytest tests/test_mcp_tools.py -v`), dùng đúng Chrome/CDP `:9222` và tool
  API `:8080` do chính `supervisord` của image quản lý — không mock. 8/8
  PASS.
- `smoke-shell-file-browser-plan-local.txt`,
  `smoke-shell-wait-write-kill-browser-nav-local.txt`,
  `smoke-browser-form-input-select-local.txt`: log client MCP Python gọi
  tay cả 25 tool (bao gồm các tool không có trong bộ pytest ngắn ở trên:
  `shell_wait`, `shell_write_to_process`, `shell_kill_process`,
  `file_str_replace`, `file_find_in_content`, `browser_move_mouse`,
  `browser_press_key`, `browser_select_option`, `browser_scroll_up/down`,
  `browser_console_exec/view`, `browser_restart`, `message_ask_user`) —
  chạy cục bộ trước Docker, mọi tool trả `success: true` đúng dữ liệu mong
  đợi (vd `document.getElementById(...).value` sau `browser_input`/
  `browser_select_option` ra đúng `"xin chao|blue"`).
- `mcp-client-in-container.txt`: lặp lại bài gọi 25 tool cốt lõi **bên
  trong container thật**, xác nhận `shell_exec`/`file_write`+`file_read`/
  `browser_navigate`+`browser_view`/`plan_update`/`message_notify_user`
  hoạt động đúng qua MCP thật trong môi trường build cuối cùng.
- `browser_view-example-com.png`: ảnh chụp màn hình thật (giải mã base64 từ
  kết quả `browser_view`) — Chrome thật trong container đã điều hướng tới
  `https://example.com` qua `browser_navigate` gọi từ client MCP.

## (b) `agy -p` gọi tool MCP trong container — KHÔNG thành công, lý do đã xác định

- `agy-p-auth-failed.txt`: chạy đúng lệnh trong Issue (`agy -p "..."
  --output-format stream-json --model gemini-3.8-flash-low --effort low
  --dangerously-skip-permissions --print-timeout 180s`) sau khi
  `docker cp ~/.gemini <container>:/home/ubuntu/.gemini` và ghi
  `~/.gemini/config/mcp_config.json` trỏ đúng `http://127.0.0.1:8081/mcp`
  (đúng mục 5 của `docs/spec/02-mcp-trong-sandbox.md`).
  **Kết quả: `agy` yêu cầu đăng nhập OAuth lại** (`authentication failed or
  timed out`) — đã xác định nguyên nhân: phiên đăng nhập thật của `agy`
  trên máy Boss **không nằm trong `~/.gemini`** dạng file thường (đã
  `grep -rl "refresh_token\|access_token" ~/.gemini` — không tìm thấy token
  nào ngoài 1 dòng không liên quan trong CHANGELOG cache), nhiều khả năng
  nằm trong keyring hệ thống (Secret Service/libsecret) — thứ không copy
  được qua `docker cp` vì gắn với session/keyring của máy chủ, không phải
  file. Đây là lệch so với giả định "chỉ cần copy `~/.gemini`" ghi trong
  spec — ghi lại để đợt sau (thiết kế "đăng nhập CLI lần đầu qua
  pseudo-terminal" ở `03-cau-hinh-thuoc-harness.md`, đợt 3) biết trước.
  Đã xoá `/home/ubuntu/.gemini` khỏi container test ngay sau khi xác nhận
  lỗi (không giữ lại phiên thật của Boss trong container).
  Theo đúng hướng dẫn Issue khi agy không chạy được: nộp (a)+(c) + bằng
  chứng gọi tool qua client MCP Python (mục (a) ở trên, có cả bản chạy
  trong container) thay thế.

## (c) `supervisorctl status` — toàn bộ RUNNING

- `supervisorctl-status.txt`: 7 program (`xvfb`, `chrome`, `socat`,
  `x11vnc`, `websockify`, `app`, `mcp`) đều RUNNING trong container build
  từ Dockerfile/supervisord.conf của PR này. Đã kiểm lặp lại 3 lần
  (`restart`, `restart` lần 2, `down && up` — cold start xoá cả volume
  `.venv` cũ) — luôn RUNNING ổn định sau khi thêm `sleep 2` vào lệnh khởi
  động `program:mcp` (xem ghi chú trong `supervisord.conf`: ở chế độ dev
  (`docker-compose-development.yml`), `program:app` chạy `uv run` không có
  `--no-dev` nên lần đầu container lên, `uv` tự cài thêm nhóm dev vào venv
  dùng chung với `program:mcp`; nếu `mcp` khởi động đúng lúc đó có thể gặp
  `ModuleNotFoundError: No module named 'mcp'` thoáng qua — đã quan sát 1
  lần trước khi thêm `sleep 2`, tự phục hồi nhờ `autorestart`. Container
  nhiệm vụ thật do `docker_sandbox.py` tạo không bind-mount nên không gặp
  race này).
- Đã kiểm thêm, không có file riêng: Chrome chạy bằng user `browser` (khác
  `ubuntu` đang chạy `mcp`/CLI) — `ps -eo pid,user,cmd` trong container cho
  thấy tiến trình `chromium` thuộc user `browser`, còn
  `mcp/server.py`/`uv run uvicorn` thuộc user `ubuntu`; `sudo` không còn
  tồn tại trong image (`which sudo` → không có); từ HOST, `curl
  127.0.0.1:8081/mcp` không kết nối được (cổng không nằm trong
  `docker port`/`EXPOSE`), trong khi từ bên trong container cổng này trả
  lời bình thường; sinh `.docx` thật bằng `python-docx` vào
  `/home/ubuntu/output/` thành công.

## Lệch so với spec

Xem mục mới "Lệch so với spec và lý do (thi công đợt 1, Issue #29)" ở cuối
`docs/spec/02-mcp-trong-sandbox.md` — tổng hợp 6 điểm (tham số browser
click/input/select_option, browser_restart không kill Chrome, plan/message
ghi NDJSON cục bộ thay Redis, cách chạy `program:mcp`, bỏ hẳn gói `sudo`,
user `browser` cho Chrome).

## Vòng sửa theo review Opus (comment 6077403049 trên PR #36)

2 điểm chặn + 3 điểm "rẻ, làm luôn" — tất cả đã kiểm chạy thật trong
container (không chỉ đọc code):

- **Screenshot → ImageContent thật.** Trước: `browser_view` nhét base64 PNG
  (~76KB, ~100k ký tự) vào field `screenshot` của text JSON — CLI không
  "nhìn" được, chỉ tốn token. Sau: mọi tool trả `ImageContent` thật (mime
  `image/jpeg`), JPEG quality 60, thu nhỏ chiều rộng về tối đa 1024px bằng
  Pillow. `browser_view-imagecontent-example-com.jpg` là ảnh thật giải mã
  từ kết quả — 1024×753, 37KB (so với PNG 76KB trước đó, dù chụp cùng
  trang). CHỈ `browser_view` kèm ảnh mặc định; 10 tool đổi trạng thái khác
  nhận thêm tham số `with_screenshot: bool = False` — mặc định KHÔNG kèm
  ảnh (`data` chỉ còn `url/title/width/height`, bỏ hẳn field `screenshot`).
  Có 1 lỗi phát sinh khi sửa: khai kiểu trả về `Union[dict, List[Any]]`
  khiến FastMCP tự bật "structured output" rồi crash khi serialize object
  `Image` (`PydanticSerializationError`) — sửa bằng cách khai
  `structured_output=False` cho cả 25 tool khi đăng ký trong `server.py`
  (không chỉ 12 tool browser, để tránh tái phạm lỗi này ở các tool khác).
- **`shell_wait` timeout khi chờ ≥ 30s.** `REST_TIMEOUT=30` (chung cho mọi
  tool) nhỏ hơn mặc định 60s mà tool API tự chờ — gọi `shell_wait(seconds=35)`
  với lệnh `sleep 32` trước đây sẽ bị `httpx.ReadTimeout` cắt ngang ở giây
  thứ 30. Sửa: `shell_wait` dùng timeout HTTP riêng = `seconds` (hoặc 60 mặc
  định) + 15 giây đệm; các tool khác giữ nguyên `REST_TIMEOUT`. Phát hiện
  thêm 1 lỗi liên quan khi sửa: truyền `timeout=None` tường minh cho httpx
  per-request bị hiểu là "KHÔNG giới hạn thời gian" (khác hẳn không truyền
  — lúc đó mới dùng default của client) — sửa bằng cách chỉ đưa kwarg
  `timeout` vào request khi thật sự có giá trị ghi đè.
- **Chặn đường dẫn nhạy cảm.** `file_read`/`file_write`/`file_str_replace`/
  `file_find_in_content`/`file_find_by_name` từ chối (trả
  `{"success": false, "message": "Duong dan bi cam boi luat cung §7 ..."}`)
  khi đường dẫn trùng hoặc nằm trong `~/.gemini`, `~/.claude`,
  `~/.gen-agents`, hoặc là `/etc/shadow` — luật cứng mục 7 của
  `docs/spec/00-tong-quan.md`. Kiểm tra theo đường dẫn trực tiếp (không
  duyệt sâu qua glob/symlink lồng nhau) — đủ chặn truy cập trực tiếp, không
  phải phòng thủ toàn diện.
- **Ghim version Claude Code CLI.** `npm install -g
  @anthropic-ai/claude-code@2.1.295` (bản mới nhất trên npm lúc viết,
  09/10/2026, kiểm bằng `npm view @anthropic-ai/claude-code version`) thay
  vì cài "latest" trôi — build lặp lại được. Xác nhận `claude --version`
  trong container build lại từ đầu ra đúng `2.1.295`
  (`tool-versions-pinned.txt`).
- **Ghi rõ `message_ask_user` chưa dừng chờ ở đợt 1** — thêm vào mục "Lệch
  so với spec" của `docs/spec/02-mcp-trong-sandbox.md`: tool này đợt 1 chỉ
  ghi NDJSON rồi trả ngay, KHÔNG thực sự treo CLI chờ trả lời — việc đó
  thuộc `CliEngineFlow` (đợt 2).

Bằng chứng: `pytest-review-fixes-in-container.txt` (12 test
`test_mcp_tools.py` PASS trong container đã build lại — gồm 3 test mới:
`test_shell_wait_long_running_past_30s` — sleep 32 + wait 35s, mất đúng
~32s, PASS thật chứ không phải mock; `test_file_read_rejects_gemini_home`;
`test_view_includes_real_image_content`/`test_with_screenshot_param_adds_image`/
`test_navigate_default_has_no_image`), `supervisorctl-status.txt` (build
lại từ Dockerfile đã ghim version, cả 7 program vẫn RUNNING),
`tool-versions-pinned.txt` (`claude --version` → 2.1.295).
