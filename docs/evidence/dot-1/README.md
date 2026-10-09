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
