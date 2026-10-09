# 01 — Bộ chuyển động cơ: agent CLI làm não (agy, Claude Code)

Trạng thái: bản nháp v0, 09/10/2026. Tác giả: Claude Code (điều phối). Bằng chứng đo thật: `agy` v1.3.2 và `claude` v2.1.295 trên máy Fedora của Boss (NDJSON thô lưu ở máy đo, trích dưới). Liên quan: `00-tong-quan.md`, `02-mcp-trong-sandbox.md`, `03-cau-hinh-thuoc-harness.md`, Issue #26.

## 1. Quyết định kiến trúc

**Bộ chuyển cắm ở tầng Flow, không ở `LLM.ask()`.**
ai-manus có interface `LLM` (`backend/app/domain/external/llm.py`) nhưng vòng lặp planner/executor của nó (`domain/services/agents/base.py`, `_tool_loop`) mới là "não". Nếu chỉ thay LLM, CLI bị hạ xuống vai "model" và mất toàn bộ năng lực tự hành (lập kế hoạch, sub-agent, nén ngữ cảnh, tự sửa lỗi). Vì vậy:

- Thêm flow mới `domain/services/flows/cli_engine.py` chạy song song với `plan_act.py`. Flow này **không gọi LLM**, chỉ: khởi chạy CLI trong máy nhiệm vụ, bơm tin người dùng vào stdin, đọc NDJSON từ stdout, dịch sang `AgentEvent` sẵn có (`domain/models/event.py`) rồi đẩy ra hàng đợi như flow cũ. Frontend và WebSocket **không sửa**.
- `plan_act.py` + LangChain giữ nguyên làm động cơ "API thô" (dự phòng, và để chạy test offline với mockserver).
- Chọn động cơ theo cấu hình phiên (mặc định theo tenant): `agy` | `claude_code` | `api_tho`.

```
Người dùng ──WS──▶ backend (CliEngineFlow) ──exec_command──▶ [máy nhiệm vụ]
                      ▲   │ stdin NDJSON                         agy / claude -p
                      │   ▼ stdout NDJSON                            │ MCP (localhost:8081)
                 AgentEvent ◀── bộ dịch sự kiện                      ▼
                                                       MCP server của harness
                                                       (shell · file · browser · plan · hỏi người dùng)
```

## 2. Giao diện trong mã (Protocol)

`domain/external/engine.py` (mới):

```python
class Engine(Protocol):
    async def start(self, ctx: EngineContext) -> None          # dựng HOME tạm, khởi chạy CLI (tiến trình dài trong sandbox)
    async def send(self, text: str, attachments: list[str]) -> None   # 1 lượt người dùng → 1 dòng NDJSON vào stdin
    def events(self) -> AsyncIterator[EngineEvent]             # luồng sự kiện đã chuẩn hoá
    async def stop(self) -> None                               # dừng tiến trình, giữ HOME để nối lại
    async def destroy(self) -> None                            # thu hồi dữ liệu CLI tự ghi, xoá HOME tạm
```

`EngineContext`: `session_id`, `tenant_id`, `sandbox`, `cwd` (`/home/ubuntu` — thư mục làm việc của sandbox ai-manus, nơi đã có `skills/`, `upload/`, `todo.md`), `home` (HOME tạm trong sandbox), `model`, `effort`, `conversation_ref` (để nối lại), `mcp_endpoint` (`http://127.0.0.1:8081/mcp`), `rendered_files` (AGENTS.md/CLAUDE.md, mcp config, settings, skills — do `03` sinh ra).

`EngineEvent` (chuẩn chung, không phụ thuộc CLI):

| EngineEvent | Ý nghĩa | Ánh xạ sang AgentEvent của ai-manus |
|---|---|---|
| `init{engine, model, tools[]}` | CLI đã lên | `TitleEvent` (nếu chưa có tiêu đề) |
| `text_delta{text}` | mảnh văn bản trả lời | gom thành `MessageEvent(role=assistant)` khi lượt kết thúc |
| `tool_call{id, name, args}` | CLI bắt đầu gọi công cụ | `ToolEvent(status=calling, tool_content theo loại)` |
| `tool_result{id, name, output}` | công cụ xong | `ToolEvent(status=called)` |
| `plan{steps[]}` | kế hoạch/tiến độ (từ MCP tool `plan_update`) | `PlanEvent` + `StepEvent` |
| `ask_user{question}` | CLI cần người trả lời (MCP tool `message_ask_user`) | `WaitEvent`; phiên sang `WAITING`, tiến trình CLI vẫn sống |
| `notify{text}` | thông báo trung gian (MCP tool `message_notify_user`) | `MessageEvent` |
| `usage{input, output, cache_read, total}` | token lượt này | ghi sổ đo dùng theo tenant (SaaS) |
| `done{status}` | lượt kết thúc | `DoneEvent` (status SUCCESS) hoặc `ErrorEvent` |
| `error{code, text}` | lỗi CLI (hết quota, chưa đăng nhập, timeout) | `ErrorEvent` với câu tiếng Việt dễ hiểu + mã |

## 3. Bộ chuyển `agy` (đã đo thật)

**Lệnh khởi chạy** (trong máy nhiệm vụ, `HOME=<home tạm>`, `cwd=/home/ubuntu`):
```
agy -p --input-format stream-json --output-format stream-json \
    --model <model> --effort <low|medium|high> \
    --dangerously-skip-permissions [--conversation <id>] [--print-timeout 0]
```
- Tắt hỏi quyền là bắt buộc ở chế độ không giao diện; **ranh giới an toàn nằm ở container + `settings.json` do harness sinh** (`permissions.deny` cho lệnh nguy hiểm, ví dụ `command(regex:rm -rf /)`), không phải ở prompt. Đã xác nhận headless tôn trọng `settings.json`.
- `--sandbox` của agy: đã thử, không thấy khác biệt quan sát được; **không dựa vào nó**, cách ly do container đảm nhiệm.

**Đầu vào** (mỗi dòng = 1 lượt, cùng `conversation_id`, `num_turns` tăng; đã kiểm 2 lượt):
```json
{"event":"user","message":{"content":[{"type":"text","text":"..."}]}}
```
Định dạng kiểu Claude Code (`{"type":"user",...}`) bị từ chối: `stream input message is missing the "event" field`.

**Đầu ra**: khoá `event` ∈ `init | step_update | result`, nội dung lồng dưới khoá cùng tên.
```json
{"event":"init","conversation_id":"…","init":{"model":"…","cwd":"…","tools":[…60 tool…],"permission_mode":"request-review"}}
{"event":"step_update","step_update":{"step_index":1,"state":"ACTIVE","step_type":"agent_response","text_delta":"OK"}}
{"event":"step_update","step_update":{"step_type":"tool","state":"ACTIVE","tool_name":"run_command","tool_info":{"name":"run_command","parameters":{"CommandLine":"echo hi"}}}}
{"event":"step_update","step_update":{"step_type":"tool","state":"DONE","tool_info":{"…","output":"hi\r\n"}}}
{"event":"result","result":{"status":"SUCCESS","response":"OK\n","num_turns":1,"usage":{"input_tokens":13441,"output_tokens":1,…}}}
```
Bảng dịch:

| agy | EngineEvent |
|---|---|
| `init` | `init` (lưu `conversation_id` làm `conversation_ref`) |
| `step_update.step_type=agent_response` có `text_delta` | `text_delta` |
| `step_update.step_type=tool`, `state=ACTIVE` | `tool_call` (name = `tool_name`, args = `tool_info.parameters`) |
| `step_update.step_type=tool`, `state=DONE` | `tool_result` (output = `tool_info.output`) |
| `step_update.state=DONE` có `usage` | `usage` |
| `result.status=SUCCESS` | `done` |
| `result.status=ERROR` hoặc stderr có lỗi đăng nhập/quota | `error` |
| tool_call tới MCP `plan_update` / `message_ask_user` / `message_notify_user` | `plan` / `ask_user` / `notify` (bộ dịch nhận diện theo tên tool MCP) |

**Nối lại hội thoại**: `--conversation <id>`; dữ liệu ở `<HOME>/.gemini/antigravity-cli/conversations/<id>.db`. HOME tạm sống **theo phiên** (không theo lượt) để `ask_user` → người trả lời → bơm tiếp vào stdin cùng tiến trình; nếu tiến trình đã chết thì khởi chạy lại với `--conversation`.

**Cấu hình harness sinh vào HOME tạm** (chi tiết ở `03`): `~/.gemini/antigravity-cli/settings.json` (model, permissions), `~/.gemini/config/mcp_config.json` (`mcpServers` → MCP của harness), `~/.gemini/config/skills/<tên>/SKILL.md`, `/home/ubuntu/AGENTS.md` (agy đọc `GEMINI.md` và `AGENTS.md`, **không đọc `CLAUDE.md`** — đã đo), skills workspace `/home/ubuntu/.agents/skills/<tên>/SKILL.md` nếu muốn skill chỉ áp cho một phiên, phiên đăng nhập của **tenant**.

## 4. Bộ chuyển Claude Code (đã đo thật, có cảnh báo)

**Lệnh**:
```
claude -p --input-format stream-json --output-format stream-json --verbose \
       --model <model> --settings <home>/.claude/settings.json \
       --mcp-config <home>/mcp.json --strict-mcp-config \
       --permission-mode bypassPermissions [--resume <session_id>]
```
- **Không dùng `--bare`**: `--bare` chỉ nhận `ANTHROPIC_API_KEY`, không nhận phiên OAuth (đã thử: "Not logged in"). Tenant đăng nhập bằng gói Claude của họ nên phải chạy không `--bare` và **kiểm soát ngữ cảnh bằng `--settings` + `--strict-mcp-config`** để không nạp hook/cấu hình lạ. Trong máy nhiệm vụ HOME tạm sạch nên không có hook ngoài ý muốn.
- Đầu vào: `{"type":"user","message":{"role":"user","content":"..."}}` (đã kiểm).
- Đầu ra: khoá `type` ∈ `system | assistant | user | result | tool_progress | rate_limit_event`, kèm `subtype` (`init`, `post_turn_summary`…). Bảng dịch: `system/init` → `init`; `assistant` có `content[].type=text` → `text_delta`; `content[].type=tool_use` → `tool_call`; `user` có `tool_result` → `tool_result`; `result` → `usage` + `done`/`error`; `rate_limit_event` → `error(code=quota)` nếu chặn.
- Nối lại: `--resume <session_id>` (lấy từ `system/init`).
- Cấu hình sinh: `<home>/.claude/.credentials.json` + `<home>/.claude.json` (phiên tenant — phiên nằm ở cả hai, gói cả hai vào blob), `<home>/.claude/settings.json`, `<home>/mcp.json`, `/home/ubuntu/CLAUDE.md`, skills theo plugin/skill dir của Claude Code (xác minh đường dẫn ở đợt thi công).

## 5. Ai sở hữu công cụ

| Công cụ | Cho CLI dùng tool gốc của nó? | Qua MCP của harness? | Lý do |
|---|---|---|---|
| Shell, file trong `/home/ubuntu` | Có (chạy trong container nên an toàn tương đương) | Có song song | Tận dụng chất lượng tool gốc; harness vẫn thấy sự kiện qua NDJSON |
| **Trình duyệt** | **Không** (tắt/không khai) | **Bắt buộc** | Để có màn hình noVNC, giành quyền, sự kiện `BrowserToolContent`, giới hạn tốc độ, luật không lách chống bot |
| Kế hoạch, hỏi/thông báo người dùng | Không có tool gốc | Bắt buộc (`plan_update`, `message_ask_user`, `message_notify_user`) | Để UI vẽ tiến độ và dừng chờ đúng chỗ |
| Tìm web | Cho phép `search_web` gốc của agy | Tuỳ chọn (Tavily… của ai-manus) | Chi phí thấp, kết quả tốt |
| MCP ngoài (Gen-hub, Kho, Drive) | Qua cấu hình MCP tenant chọn | — | Tenant tự bật/tắt; harness là nguồn cấu hình |

Instruction sinh vào `AGENTS.md`/`CLAUDE.md` nói rõ: dùng trình duyệt chỉ qua tool MCP `browser_*`; báo tiến độ bằng `plan_update`; cần người thì `message_ask_user`; kết quả để trong `/home/ubuntu/output/`.

## 6. Vòng đời một nhiệm vụ

1. Tạo container nhiệm vụ (như ai-manus `docker_sandbox.py`), MCP server của harness lên (`02`).
2. Harness sinh HOME tạm + file cấu hình theo động cơ và tenant (`03`), gắn phiên đăng nhập của tenant.
3. `Engine.start()` → `exec_command` chạy CLI (tiến trình dài), đọc `init`.
4. Mỗi tin người dùng → `Engine.send()`; bộ dịch phát `EngineEvent` → `AgentEvent` → Redis stream → WebSocket (đường cũ).
5. `ask_user` → `WaitEvent`, phiên `WAITING`; người trả lời → `send()` tiếp.
6. `done` → `DoneEvent`; `usage` ghi sổ tenant; NDJSON thô lưu Mongo (xem lại).
7. Kết thúc phiên hoặc hết hạn rảnh → `destroy()`: thu hồi `todo.md`, `/home/ubuntu/output/`, bộ nhớ CLI tự ghi (nếu tenant bật), xoá HOME tạm, huỷ container.

## 7. Xử lý lỗi và giới hạn

- Chưa đăng nhập / hết quota: nhận diện từ `result.status=ERROR` hoặc stderr → `ErrorEvent` tiếng Việt kèm nút "Đăng nhập lại" / "Đổi model". Không tự xoay sang tài khoản khác.
- Giới hạn mỗi nhiệm vụ (cấu hình tenant): số lượt, phút chạy, token; vượt → dừng êm và báo.
- Timeout lượt: `--print-timeout` (agy) hoặc watchdog của harness; tiến trình treo → kill, cho phép nối lại.
- Không bao giờ đưa token OAuth ra ngoài tiến trình CLI; không proxy API.

## 8. Nghiệm thu đợt động cơ (bằng chứng bắt buộc)

1. Trong máy nhiệm vụ, `agy` nhận lượt qua stdin, trả `result` SUCCESS; log NDJSON thô đính kèm PR.
2. Nhiệm vụ "mở trang web X, chụp màn hình, ghi tóm tắt vào output/tom-tat.md": UI hiện `ToolEvent(browser)` và màn noVNC chuyển động; file xuất hiện trong thư viện kết quả.
3. `message_ask_user` → UI dừng chờ, trả lời → nhiệm vụ tiếp tục cùng `conversation_id`.
4. Đổi động cơ sang Claude Code cùng nhiệm vụ 2 → cùng trải nghiệm, khác model.
5. Rút phiên đăng nhập → lỗi hiển thị bằng tiếng Việt, không treo.

## 9. Câu hỏi mở
- agy có tool trình duyệt gốc nào trong CLI không (danh sách 60 tool ở `init`)? Nếu có, tắt bằng `permissions.deny` trong `settings.json`.
- Đường dẫn skills của Claude Code trong HOME tạm (xác minh khi thi công).

## Lệch so với spec và lý do (thi công đợt 2, Issue #30)

Ghi lại đúng chỗ thực tế thi công buộc khác với mô tả ở các mục trên —
chi tiết đầy đủ ở `docs/design/dot-2-cli-engine.md` (bản thiết kế Opus đã
chốt) và `docs/evidence/dot-2/README.md` (bằng chứng + lỗi tìm thấy khi
chạy thật). Không có mục nào đổi *ý định* của spec.

1. **`Engine.events()` nhận `from_seq` và yield `(seq, EngineEvent)`**, không
   phải `AsyncIterator[EngineEvent]` trơn như mục 2 mô tả — cần để
   `CliEngineFlow` nối lại đúng chỗ sau khi phiên đi qua `WAITING` (Task mới,
   kết nối SSE mới ở tầng sandbox). `conversation_ref`/`alive` là property
   đọc trạng thái sống của Engine, không phải field tĩnh trên `EngineContext`.
2. **`EngineContext` không có field `sandbox`** — adapter (`AgyEngine`,
   `ClaudeCodeEngine`) nhận `Sandbox` qua constructor (`AgyEngine(sandbox,
   binary=...)`), không qua context, để tránh một Protocol phải tự chứa một
   Protocol khác.
3. **`message_ask_user` dừng ở BIÊN LƯỢT** (CLI hỏi xong thì
   `CliEngineFlow` phát `WaitEvent` và kết thúc generator của lượt đó ngay —
   không đợi/giữ tiến trình chờ một kênh trả lời liên tiến trình). Tiến
   trình CLI thật sự vẫn sống (process không bị kill), chỉ là backend không
   đọc tiếp NDJSON của nó cho tới lượt kế. Bản "treo tool thật" (CLI tự
   block trong tool call chờ `/engine/answer`) để đợt 3 — xem "Chốt của
   Claude điều phối" cuối `docs/design/dot-2-cli-engine.md`.
4. **Mục 1b (tiền tố tên tool MCP agy thực sự in ra) CHƯA ĐO ĐƯỢC** — không
   đăng nhập được agy thật trong phiên thi công tự động (xem
   `docs/evidence/dot-2/06-home-dev-agy-login.txt`). `_MCP_PREFIX` trong
   `backend/app/domain/external/engine.py` vẫn ở dạng khoan dung (regex
   đoán nhiều biến thể tiền tố), chưa xác nhận bằng NDJSON thật — việc đo +
   khoá chính xác dời sang đợt 3.
5. **`ToolEvent(CALLED)` mang lại `function_args` của chính `tool_call`
   tương ứng** (qua một map `tool_call_id -> args` tạm thời trong
   `CliEngineFlow`), không phải rỗng như gợi ý ở bảng "EngineEvent → AgentEvent"
   — `_handle_tool_event` (agent_task_runner.py) cần `function_args["file"]`/
   `["id"]` ở sự kiện CALLED để làm tươi `FileToolContent`/`ShellToolContent`.
   Lỗi này chỉ lộ ra khi chạy thật (file content hiện "(No Content)"), test
   offline viết trước không bắt được — xem mục "Lỗi tìm thấy khi chạy thật"
   trong `docs/evidence/dot-2/README.md`.
