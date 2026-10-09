# Bằng chứng đợt 2 — Bộ chuyển động cơ CLI (Issue #30)

Nghiệm thu theo `docs/design/dot-2-cli-engine.md` mục 8 (spec 01 §8 mục 1–3 +
DoD "mở lại phiên cũ thấy lịch sử"). Chạy ngày 2026-10-09 trên dev stack
(`docker-compose-development.yml`), dùng `fake_agy.py` (sandbox/tests/) thay
agy thật — **không đăng nhập được agy thật trong phiên thi công tự động**
(xem `06-home-dev-agy-login.txt`), nên các mục cần agy thật (đo #1b) dời
sang đợt 3 theo đúng điều kiện dừng của thiết kế mục 6.

## Mục 1 — agy nhận lượt qua stdin, trả `result` SUCCESS

- `01-agy-stdin-result-success.txt`: lệnh + kết quả `POST /engine/start` qua
  curl trực tiếp vào sandbox (`fake_agy.py`, `FAKE_AGY_MODE=success`).
- `01-engine-api-sse.txt`: NDJSON thô nhận qua `GET /engine/events` (SSE) —
  đủ `init` → `step_update` (tool ACTIVE/DONE, plan_update) → `result SUCCESS`.

**Mục 1b (đo tiền tố tên tool MCP agy thực sự in ra): CHƯA ĐO ĐƯỢC** — cần
agy thật đã đăng nhập (xem mục "Chưa làm được" bên dưới). `_MCP_PREFIX` trong
`agy_engine.py` vẫn ở dạng khoan dung (regex đoán nhiều biến thể), chưa xác
nhận bằng dữ liệu thật.

## Mục 2 — Nhiệm vụ trình duyệt + ghi file kết quả

`fake_agy.py` (`FAKE_AGY_MODE=demo`) gọi THẬT CDP (`PUT /json/new`, mở tab
Chrome trong chính sandbox) và THẬT REST `/api/v1/file/write` (ghi
`/home/ubuntu/output/tom-tat.md`) — rồi mới phát dòng NDJSON
`browser_navigate`/`file_write` tương ứng, mô phỏng đúng những gì agy thật sẽ
làm (gọi MCP tool trước, báo cáo trong NDJSON sau).

- `02-ui-browser-toolevent.png`: UI thật (`localhost:5174`, chụp bằng
  `google-chrome --headless=new`) — thấy nhóm `run_command`, tool con
  "Writing file output/tom-tat.md" mở ra đúng nội dung thật đã ghi.
- `02-novnc.png`: ảnh chụp màn hình browser tool trả về qua
  `ToolEvent(tool_name=browser)` (tải thật qua `/api/v1/files/...`). **Lưu ý
  trung thực**: ảnh này không cho thấy rõ example.com đã load — do cách mô
  phỏng dùng `/json/new` mở TAB MỚI thay vì điều khiển đúng tab mà
  `BrowserUseBrowser`/`PlaywrightBrowser` của backend đang theo dõi, nên
  chụp lại tab cũ. Cơ chế ToolEvent(browser) → ảnh chụp thật → upload → URL
  ký chữ ký là ĐÚNG và đã kiểm chứng; nội dung ảnh cụ thể lệch do giới hạn
  của fake_agy, không phải lỗi code đợt 2.
- `02-ndjson.txt`: toàn bộ frame WebSocket của lượt chat này (đã che
  `signature=` trong URL file).
- File thật xuất hiện trong sandbox: xác nhận qua FileUpdateEvent trong
  `02-ndjson.txt` (file_id, size=96, filename=tom-tat.md).

## Mục 3 — `message_ask_user` → chờ → trả lời → tiếp tục cùng `conversation_id`

- `03-wait-resume-ui.png`: UI thật cho thấy câu hỏi "Ban muon tiep tuc
  khong?", câu trả lời người dùng "Co, tiep tuc di.", rồi lượt tiếp tục đến
  "Task completed" — đúng trải nghiệm dừng chờ/trả lời/tiếp tục.
- `03-ws-events.txt`: frame WebSocket đầy đủ hai lượt (lượt 1 kết thúc bằng
  `wait` + `status_update agent_status=waiting`; lượt 2 bắt đầu lại từ
  `chat` mới, cùng session, kết thúc `done`).
- `03-conversation-ref.txt`: `db.engine_runs` cho thấy 2 document (turn_index
  1 và 2) — **turn 1 `status=WAITING`**, turn 2 `status=SUCCESS,
  conversation_ref=fake-conv-001`; `sessions` collection xác nhận
  `Session.conversation_ref=fake-conv-001` được ghi lại đúng từ `init`.

**Phát hiện + đã sửa trong lúc nghiệm thu (xem "Lỗi tìm thấy khi chạy thật"
bên dưới)**: lần chạy ĐẦU TIÊN của mục 3 cho thấy `engine_runs` ghi sai
`status=ERROR` cho một lượt thực ra là `WAITING`. Đã sửa `cli_engine.py` và
chạy lại — `03-conversation-ref.txt` là log SAU khi sửa (đúng).

## Mục 4 (DoD) — Mở lại phiên cũ thấy lịch sử

- `04-session-events.txt`: sau `docker compose rm -sf sandbox` (xoá hẳn
  container sandbox, không chỉ dừng), gọi lại `GET /sessions/{id}` qua REST
  — đủ nguyên 17 event (bao gồm `wait`, `tool`, `plan`, `done`) vì lịch sử
  nằm trong Mongo (`sessions.events`), độc lập với vòng đời sandbox.

## Mục 5 — Lỗi chưa đăng nhập hiện tiếng Việt, không treo

- `05-error-vi.png`: UI thật hiện "Phiên đăng nhập của động cơ CLI không
  còn hiệu lực. Cần đăng nhập lại. (mã: chua_dang_nhap)", kèm "Task
  completed" (không treo, stream kết thúc sạch).
- `05-error-ndjson.txt`: frame WebSocket — `FAKE_AGY_MODE=error` trả đúng
  câu lỗi mẫu từ `docs/evidence/dot-1/agy-p-auth-failed.txt`
  ("authentication failed or timed out"), `classify_error()` nhận đúng
  `chua_dang_nhap`.

## Mục 6 — Test tự động

- `06-pytest-backend-offline.txt`: `cd backend && uv run pytest
  --ignore=tests/test_api_file.py --ignore=tests/test_auth_routes.py
  --ignore=tests/test_sandbox_file.py -m "not e2e"` → **244 passed**.
- `06-pytest-sandbox.txt`: `cd sandbox && uv run pytest -q` → **44 passed**
  (chạy TRỰC TIẾP trên host, gọi vào container qua cổng map — đúng cách CI
  job "Sandbox API tests" chạy).
- `06-pytest-e2e.txt`: `cd backend && uv run pytest -m e2e -rs` → **2 passed**
  (`test_e2e_plan_act_smoke`, `test_e2e_plan_act_wait_and_resume` — cả hai
  dùng mockserver đã vá #35).

## Mục 7 — Không hồi quy `plan_act`

- `07-plan-act-khong-hoi-quy.txt` (giống `06-pytest-e2e.txt`): cả hai kịch
  bản e2e PlanAct (`plan_act_e2e.yaml` dạng dict mới, `plan_act_wait_e2e.yaml`
  dạng list cũ) đều xanh — xác nhận vá #35 (mục dưới) không phá hành vi
  `plan_act` hiện có theo cả hai định dạng scenario.

## Lỗi tìm thấy khi chạy thật (không bắt được bằng test offline) — đã sửa

Nghiệm thu bằng dữ liệu thật (không phải mock) đã lộ ra 3 lỗi thật mà bộ
test offline (viết trước khi chạy thật) không bắt được — sửa ngay trong PR
này, không hoãn:

1. **`ToolEvent(CALLED)` mất `function_args`** — `_handle_tool_event`
   (agent_task_runner.py) cần `function_args["file"]`/`["id"]` ở sự kiện
   CALLED để làm tươi `FileToolContent`/`ShellToolContent`, nhưng thiết kế
   mục 3.1 chỉ mô tả `tool_result → ToolEvent(..., function_result=...)`
   không có args. Sửa: `CliEngineFlow` giữ `tool_args_by_call_id` lúc
   CALLING, "trả" lại lúc CALLED. Phát hiện qua `02-ndjson.txt` (file
   content ban đầu ra `"(No Content)"`), sửa xong chạy lại thấy đúng nội
   dung file thật.
2. **`turn_status` ghi sai do thứ tự code sau `yield`** — khi
   `agent_task_runner.py._run_flow` nhận `WaitEvent`/`DoneEvent`/`ErrorEvent`
   và `return` ngay trong `async for`, Python đóng generator của
   `CliEngineFlow.run()` bằng `GeneratorExit` TẠI điểm `yield` cuối — mọi
   dòng code SAU yield trong CÙNG lần lặp đó không chạy. `turn_status` (dùng
   để đóng `engine_runs`) từng được set SAU yield nên luôn giữ giá trị mặc
   định `"ERROR"` bất kể sự kiện thật là gì. Sửa: set state TRƯỚC yield.
   Phát hiện qua `03-conversation-ref.txt` lần chạy đầu (status sai), đã
   thêm test hồi quy mô phỏng đúng cách tiêu thụ generator của runner thật
   (`test_wait_event_closes_turn_correctly_even_when_consumer_stops_right_after_it`,
   xác nhận bắt được lỗi khi revert fix).
3. **Mất tín hiệu SSE do "pulse" `set()`-rồi-`clear()` ngay** — khi nhiều
   dòng NDJSON được ghi gần như đồng thời (agy thường in một loạt dòng rất
   nhanh), một waiter gọi `wait()` SAU khi pulse đã tắt sẽ chờ hết 15 giây
   dù dữ liệu đã có sẵn — dòng cuối (thường là `result`) hay bị trễ 15s và
   rơi ra ngoài timeout phía client. Sửa `sandbox/app/services/engine.py`:
   `clear()` chuyển vào đúng lúc chụp ảnh (snapshot) trong `events()`, không
   còn ở `_append_line()`. Phát hiện khi chạy lại `sandbox/tests/test_engine_api.py`
   nhiều lần liên tục (lặp lại ổn định ở `test_from_seq_replays_only_newer_lines`),
   xác nhận hết lặp sau khi sửa (3 lần chạy liên tiếp xanh).

## Chưa làm được (dừng đúng điều kiện thiết kế, không cố lách)

- **Đăng nhập agy thật trong HOME tạm dev**: không thực hiện được trong
  phiên thi công tự động này — công cụ Bash không cấp TTY thật cho
  `agy` (bubbletea cần `/dev/tty`), và không có kênh để Boss dán mã xác
  thực vào một tiến trình không tương tác. Xem đầy đủ trong
  `06-home-dev-agy-login.txt`. **Cần Boss hoặc một phiên có terminal thật
  chạy**:
  ```
  docker compose -f docker-compose-development.yml exec -u ubuntu \
    -e HOME=/home/ubuntu/.engine-home -it sandbox agy
  ```
  rồi làm tiếp bước 2–5 của thiết kế mục 6 (xác minh không có keyring, token
  nằm ở file, `agy -p` chạy được, bền qua restart).
- **Mục 1b (đo tiền tố tên tool MCP thật)**: phụ thuộc agy đã đăng nhập ở
  trên — dời sang đợt 3.
- **Spec 01 §8 mục 4–5** (đổi sang Claude Code, thu phiên đăng nhập): ngoài
  phạm vi Issue #30 theo đúng thiết kế (thuộc đợt 3).
