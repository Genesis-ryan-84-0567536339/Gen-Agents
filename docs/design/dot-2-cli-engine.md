# Thiết kế thi công đợt 2 — Bộ chuyển động cơ CLI (`CliEngineFlow` + adapter agy)

> Opus thiết kế · **Sonnet thi công theo đúng tài liệu này** · Opus review trước merge.
> Issue #30 · Spec `docs/spec/01-dong-co-cli.md` (đã đo thật), `02-mcp-trong-sandbox.md`,
> `00-tong-quan.md` · Nền: PR #36 (`origin/dot-1/mcp-sandbox`) · Nhánh `dot-2/cli-engine`.
> Mọi `gh` kèm `-R Genesis-ryan-84-0567536339/Gen-Agents`; không đụng remote `upstream`.

Nguyên tắc xuyên suốt: **frontend và WebSocket không sửa một dòng.** Mọi thứ mới phải ra ngoài
dưới dạng `AgentEvent` đã có (`backend/app/domain/models/event.py:142`). `PlanActFlow`
(`backend/app/domain/services/flows/plan_act.py:58`) giữ nguyên, không di cư.

## 1. Khởi chạy CLI như tiến trình dài có stdin/stdout stream

### 1.1 `exec_command` hiện tại KHÔNG stream 2 chiều được

`DockerSandbox.exec_command` (`docker_sandbox.py:188`) chỉ `POST /api/v1/shell/exec` rồi trả
`ToolResult` một lần. Phía sandbox `ShellService.exec_command` (`sandbox/app/services/shell.py:345`)
gõ lệnh vào **một pane tmux** (`pane.send_keys(..., literal=True)`, `shell.py:390`), chờ mềm 5
giây (`shell.py:405`), chưa xong thì trả `status="running"` và đóng HTTP request. Bốn lý do chí tử:

1. **Không push** — phải poll `/shell/view` → `_capture_sync` (`shell.py:125-132`) chụp lại cả pane
   (history 100000 dòng, `shell.py:68`) ⇒ O(n²) và trễ.
2. **Output bị terminal làm biến dạng** — ANSI bị bóc (`shell.py:90-93`), wrap theo bề rộng pane
   1000 cột (`shell.py:155-157`), mỗi dòng bị `rstrip()` (`shell.py:132`). Dòng NDJSON có
   `tool_info.output` thường vượt 1000 ký tự ⇒ JSON vỡ hoặc mất khoảng trắng trong chuỗi.
3. **stdin là tổ hợp phím, không phải byte stream** — `write_to_process` (`shell.py:507`) gửi keys;
   bash **echo lại** dòng JSON vào chính output đang parse.
4. **Sentinel PS1 trộn vào dòng** (`shell.py:41`) — tiến trình chạy mãi không trả prompt làm cơ
   chế done/returncode vô nghĩa.

### 1.2 Hai phương án → chọn (a)

**(a)** thêm `/api/v1/engine/*` trong sandbox: asyncio subprocess, giữ stdin mở, SSE đẩy từng dòng
stdout. **(b)** `docker exec -i` attach socket qua Docker SDK từ backend. **Chọn (a):**

1. **(b) không chạy được trong dev stack lẫn CI.** Khi `SANDBOX_ADDRESS` được đặt
   (`docker-compose-development.yml:59`), `DockerSandbox.create` trả `DockerSandbox(ip=...)` **không
   có container name** (`docker_sandbox.py:561-564`), `id` trả hằng `"dev-sandbox"`
   (`docker_sandbox.py:36-38`). Không có container để `docker exec`; job `e2e` của CI dùng đúng
   compose đó ⇒ (b) không có đường test tự động.
2. **Tiến trình phải sống lâu hơn một `Task` của backend.** `WaitEvent` → runner lật phiên `WAITING`
   rồi `return` (`agent_task_runner.py:335-340`); lượt sau `AgentDomainService.chat` thấy
   `status != RUNNING` nên `_create_task` (`agent_domain_service.py:120-123`) ⇒ Task mới ⇒ **runner
   mới** dựng qua factory (`redis_task.py:66-69`, `agent_task_runner.py:549`). Mọi handle subprocess
   giữ trong tiến trình backend đều mất. Giữ tiến trình trong sandbox và gọi lại bằng `engine_id`
   biến "nối lại" thành một request HTTP.
3. **(b) buộc backend tự tháo khung multiplexed của docker.sock** (8-byte header) và giữ socket thô
   — vỡ khi `TASK_BACKEND=celery` (`backend/app/core/config.py:131`).
4. **(a) đúng hình dạng đang có**: sandbox đã giữ trạng thái tiến trình dài
   (`ShellService.active_shells`, `shell.py:81`), backend chỉ nói REST.

### 1.3 Đặc tả endpoint mới

Mới: `sandbox/app/services/engine.py`, `sandbox/app/api/v1/engine.py`, `sandbox/app/schemas/engine.py`;
gắn router ở `sandbox/app/api/router.py:3,6-8`.

| Method | Path | Body / Query | Trả về |
| --- | --- | --- | --- |
| POST | `/engine/start` | `{engine_id, argv[], env{}, cwd}` | `{engine_id, pid, alive, started_at, reused}` |
| POST | `/engine/send` | `{engine_id, line}` | `{ok, bytes}` |
| GET | `/engine/events` | `?engine_id=&from_seq=0` | SSE `{"seq","stream","ts","line"}` |
| GET | `/engine/status` | `?engine_id=` | `{alive, returncode, last_seq, started_at}` |
| POST | `/engine/stop` | `{engine_id, signal}` | `{ok, returncode}` |

- `engine_id` **do backend cấp = `session.id`**; `start` **idempotent** — đã có và còn sống thì trả
  `reused: true`, không spawn thêm.
- `asyncio.create_subprocess_exec(*argv, stdin=PIPE, stdout=PIPE, stderr=PIPE, cwd=cwd,
  env={**os.environ, **env}, limit=ENGINE_MAX_LINE)`. **Phải truyền `limit`** (mặc định
  `StreamReader` chỉ 64 KiB, dòng NDJSON có `tool_info.output` vượt ngay và nổ `LimitOverrunError`);
  mặc định `8*1024*1024`. Đọc bằng `readuntil(b"\n")`; bắt `LimitOverrunError`/`ValueError` → phát
  dòng `{"truncated": true, ...}` rồi đọc tiếp, **không kill**.
- **Vòng đệm phát lại**: `deque(maxlen=ENGINE_BUFFER_LINES)` (20000) theo `engine_id`, `seq` tăng
  đơn điệu từ 1; `?from_seq=N` phát lại từ `N+1` rồi stream tiếp — đây là thứ giữ cho đợt 2 không
  mất sự kiện khi phiên đi qua `WAITING` (1.2.2). stdout/stderr ghi **cùng** một deque, khác
  `stream` ⇒ thứ tự tương đối giữ nguyên, backend không phải trộn theo timestamp.
- SSE: `StreamingResponse(media_type="text/event-stream")`, keepalive `: ping\n\n` mỗi 15 giây.
- **Chống sandbox tự hết hạn**: `auto_extend_timeout_middleware` (`sandbox/app/core/middleware.py:11-29`)
  chỉ gia hạn **lúc nhận request**, nên một kết nối SSE dài **không** gia hạn
  `SERVICE_TIMEOUT_MINUTES` (`docker_sandbox.py:107`) ⇒ container có thể tự chết giữa nhiệm vụ.
  Backend phải gọi `GET /engine/status` mỗi 60 giây. Ghi lý do vào comment, dễ bị xoá oan.
- **Allowlist**: env `ENGINE_ALLOWED_BINARIES` (mặc định `"agy,claude"`), so theo
  `os.path.basename(argv[0])`; lệch → `400`. `argv` do backend dựng (một nguồn sự thật cho cờ CLI,
  spec 01 §3/§4), allowlist chỉ là chốt an toàn. `env` backend truyền: `HOME`, `NO_COLOR=1`,
  `TERM=dumb` (giữ `PATH` có `/home/ubuntu/.local/bin` do `sandbox/Dockerfile` đặt `ENV PATH`).
- `stop`: `terminate()` → chờ 5s → `kill()`; xoá registry sau khi deque đọc hết hoặc sau
  `ENGINE_KEEP_AFTER_EXIT=300` giây.

### 1.4 Mở rộng `Sandbox` Protocol

`backend/app/domain/external/sandbox.py` (sau `exec_command`, `:12-28`) thêm `engine_start /
engine_send / engine_events(from_seq) / engine_status / engine_stop`; hiện thực trong
`DockerSandbox` cạnh `:188`. `engine_events` dùng `client.stream("GET", ...)` + `aiter_lines()`;
**lưu ý** `httpx.AsyncClient(timeout=600)` (`docker_sandbox.py:26`) cắt SSE sau 10 phút ⇒ dùng
client riêng với `httpx.Timeout(connect=10, read=None, write=10, pool=10)`.

### 1.5 Nguồn sự kiện: chỉ NDJSON của CLI (lệch có chủ ý so với spec 02 §7)

Spec 02 §7 đề xuất (A) Redis XADD cho 3 tool tiến độ, trộn 2 nguồn **theo timestamp**. Đợt 2
**không** làm vậy: khi CLI gọi `plan_update`/`message_ask_user`/`message_notify_user`, chính NDJSON
của CLI đã in `step_update{step_type:"tool", tool_name, tool_info.parameters}` (đã đo, spec 01 §3)
⇒ **đủ dữ liệu**. Một nguồn ⇒ một thứ tự, không lệch đồng hồ, bỏ hẳn phần trộn theo timestamp mà
review Opus đã gạch; không thêm Redis client vào sandbox. File `~/.gen-agents/events.ndjson` của
đợt 1 (`sandbox/mcp/config.py:37-38`, `sandbox/mcp/progress.py:35-42`) **giữ làm vết gỡ lỗi**, đợt
2 không đọc.

**`message_ask_user` dừng chờ ở biên lượt.** Đợt 1 tool trả ngay (`progress.py:72`). Đợt 2 **không**
sửa tool để block (cần kênh liên tiến trình giữa `program:mcp` và tool API — đợt 3). Thay vào đó:
flow thấy `tool_call message_ask_user` → `WaitEvent` → phiên `WAITING`, **tiến trình CLI vẫn sống**;
instruction trong `/home/ubuntu/AGENTS.md` nói rõ *"gọi `message_ask_user` xong thì kết thúc lượt,
không tự đoán câu trả lời"*. Nếu CLI phớt lờ và chạy tiếp thì **không mất sự kiện** nhờ deque +
`from_seq` (1.3).

## 2. Hợp đồng `Engine` và `EngineEvent`

`backend/app/domain/external/engine.py` (mới). Dùng `@dataclass(slots=True)` chứ không pydantic:
`EngineEvent` **không đi qua biên serialize** (được dịch sang `AgentEvent` ngay trong flow) nên
không cần validate chạy-thời, tránh phí pydantic mỗi dòng NDJSON.

```python
EngineEventKind = Literal["init","text_delta","tool_call","tool_result","plan",
                          "ask_user","notify","usage","done","error"]
@dataclass(slots=True)
class EngineEvent:
    kind: EngineEventKind
    raw: dict                                            # dòng NDJSON gốc (lưu Mongo, mục 5)
    engine: str | None = None; model: str | None = None   # init
    tools: list[str] = field(default_factory=list); conversation_ref: str | None = None   # init
    text: str | None = None                              # text_delta | notify | ask_user
    tool_call_id: str | None = None; tool_name: str | None = None
    tool_args: dict = field(default_factory=dict); tool_output: Any = None
    steps: list[dict] = field(default_factory=list); reflection: str | None = None   # plan
    usage: dict | None = None; status: str | None = None
    code: str | None = None   # chua_dang_nhap|het_quota|timeout|tien_trinh_chet|khac
@dataclass(slots=True)
class EngineContext:
    session_id: str; tenant_id: str | None = None
    cwd: str = "/home/ubuntu"; home: str = "/home/ubuntu"
    model: str | None = None; effort: str = "medium"; conversation_ref: str | None = None
    mcp_endpoint: str = "http://127.0.0.1:8081/mcp"
    rendered_files: dict[str, str] = field(default_factory=dict)        # đợt 3
class Engine(Protocol):
    async def start(self, ctx: EngineContext) -> None: ...
    async def send(self, text: str, attachments: list[str] | None = None) -> None: ...
    def events(self, from_seq: int = 0) -> AsyncIterator[tuple[int, EngineEvent]]: ...
    async def stop(self) -> None: ...
    async def destroy(self) -> None: ...
    @property
    def conversation_ref(self) -> str | None: ...
    @property
    def alive(self) -> bool: ...
```

**Lệch spec 01 §2 (có chủ ý, ghi vào PR):** `events()` nhận `from_seq` và yield `(seq, EngineEvent)`
— cần cho nối lại sau `WAITING`; `conversation_ref`/`alive` thành property.

### 2.1 Adapter agy — `backend/app/infrastructure/external/engine/agy_engine.py`

Lệnh dựng (spec 01 §3): `agy -p --input-format stream-json --output-format stream-json --model
<ctx.model> --effort <ctx.effort> --dangerously-skip-permissions --print-timeout 0
[--conversation <ctx.conversation_ref>]`. Đầu vào mỗi lượt đúng 1 dòng (định dạng kiểu Claude Code
bị từ chối — spec 01 §3): `{"event":"user","message":{"content":[{"type":"text","text":"<text>"}]}}`.
Attachment: nối thêm `"\n\nTệp đã tải lên: /home/ubuntu/upload/<tên>"` (runner đã upload sẵn,
`agent_task_runner.py:154-164`); không có kênh file riêng.

| Dòng NDJSON agy | Điều kiện | EngineEvent |
| --- | --- | --- |
| `event=="init"` | — | `init(engine="agy", model=d.init.model, tools=[...], conversation_ref=d.conversation_id)` |
| `event=="step_update"` | `step_type=="agent_response"`, có `text_delta` | `text_delta(text=su.text_delta)` |
| `event=="step_update"` | `step_type=="tool"`, `state=="ACTIVE"` | `tool_call(tool_name=N, tool_args=su.tool_info.parameters or {}, tool_call_id=K)` |
| `event=="step_update"` | `step_type=="tool"`, `state=="DONE"` | `tool_result(tool_name=N, tool_output=su.tool_info.output, tool_call_id=K)` |
| `event=="step_update"` | `state=="DONE"`, có `usage` | `usage(usage=su.usage)` |
| `event=="result"` | `status=="SUCCESS"` | `usage(r.usage)` **rồi** `done(status="SUCCESS")` |
| `event=="result"` | `status=="ERROR"` | `error(code=classify(r.error), text=r.error)` |
| dòng không parse được | — | gom `stderr_tail` (deque 50), chỉ dùng để phân loại lỗi |

- `N = su.tool_name or su.tool_info.name`. `K = su.tool_info.id` nếu có; mẫu đo thật không có id ⇒
  fallback `K = f"{su.step_index}:{N}"`. Ghép ACTIVE↔DONE theo `K`; DONE không khớp thì vẫn phát
  với `K` mới (UI chịu được).
- `classify(text)`: `authentication|Not logged in|login` → `chua_dang_nhap` (mẫu thật
  `docs/evidence/dot-1/agy-p-auth-failed.txt`: `"authentication failed or timed out"`);
  `quota|rate limit|resource_exhausted` → `het_quota`; `timeout` → `timeout`; còn lại → `khac`.
- `conversation_id` từ `init` → `self._conversation_ref` → flow ghi vào `Session.conversation_ref`.
- **Nhận diện tool MCP.** Server đăng ký dưới khoá `"sandbox"` (spec 02 §5), tên FastMCP
  `"gen-agents-sandbox"` (`sandbox/mcp/server.py:36-37`). **Chưa đo được agy đặt tiền tố gì** ⇒ viết
  khoan dung và **đo thật khi nghiệm thu (#1b)**:
  `_MCP_PREFIX = re.compile(r"^(?:mcp__)?(?:gen-agents-)?sandbox(?:__|[.:/])")`. Sau khi bóc:
  `plan_update` → `plan(steps, reflection)`, `message_ask_user` → `ask_user(text)`,
  `message_notify_user` → `notify(text)`; `tool_result` của 3 tool này **bỏ** (tránh ToolEvent rác).

### 2.2 Adapter Claude Code

Đợt 2 **chỉ dựng khung** `claude_code_engine.py` (dùng chung vỏ start/send/events), `_translate`
raise `NotImplementedError`, test `xfail`. Spec 01 §8 mục 4 **thuộc đợt 3** (Issue #30 chỉ yêu cầu
§8 mục 1–3).

## 3. `CliEngineFlow` — `backend/app/domain/services/flows/cli_engine.py`

Implement `BaseFlow` (`flows/base.py:7`), chữ ký `run(message) -> AsyncGenerator[BaseEvent]` +
`is_done()` giống `PlanActFlow` (`plan_act.py:167`, `:299`) — runner gọi y nguyên
(`agent_task_runner.py:440`). Máy trạng thái: `IDLE ─start+send→ RUNNING ─ask_user→ WAITING
─(lượt sau: send)→ RUNNING`; `RUNNING ─done→ COMPLETED`; `RUNNING|WAITING ─error/chết→ ERROR`.

`run()`: (1) đọc Session, `resume = status == WAITING` (mẫu `plan_act.py:169-181`);
(2) `engine.start(ctx)` với `conversation_ref = session.conversation_ref`,
`home = settings.gen_engine_dev_home or "/home/ubuntu"`; (3) nếu tiến trình đã chết: có
`conversation_ref` → chạy lại kèm `--conversation`, không có → chạy mới +
`MessageEvent("Động cơ đã khởi chạy lại, lịch sử trước đó không nối được.")`;
(4) `engine.send(message.message, message.attachments)`;
(5) `async for seq, ev in engine.events(from_seq=session.engine_last_seq)` → dịch → `yield` → cập
nhật `engine_last_seq` **sau mỗi sự kiện đã yield**; (6) `WaitEvent` → `self._done = False; return`;
(7) `done` → `self._done = True; yield DoneEvent()`; (8) task keepalive `engine_status()` mỗi 60s
(1.3) + watchdog: không sự kiện trong `GEN_ENGINE_IDLE_TIMEOUT` (600s) **và** `alive == False` →
`ErrorEvent(tien_trinh_chet)`; trần một lượt `GEN_ENGINE_MAX_TURN_SECONDS` (3600s) → `stop()` +
`ErrorEvent`.

### 3.1 Ánh xạ `EngineEvent` → `AgentEvent`

| EngineEvent | AgentEvent | Ghi chú |
| --- | --- | --- |
| `init` | `TitleEvent(title=message.message[:50])` chỉ khi `session.title` rỗng | agy không cho tiêu đề; mẫu `agent_task_runner.py:412-415`. Đồng thời ghi `conversation_ref` |
| `text_delta` | (đệm) | `event.py:142` **không có** loại sự kiện delta ⇒ phải gom |
| gom text | `MessageEvent(role="assistant", message=buf)` | flush khi có `tool_call`/`ask_user`/`done`, hoặc buf > 32 KiB; buf rỗng lúc `done` → dùng `result.response` |
| `notify` | `MessageEvent(assistant, text)` | flush buf trước |
| `tool_call` | `ToolEvent(status=CALLING, tool_call_id=K, tool_name=<nhóm>, function_name=<tên thật>, function_args=args)` | **không tự đặt `tool_content`** — xem 3.2 |
| `tool_result` | `ToolEvent(status=CALLED, cùng K, function_result=ToolResult(success=True, data=output))` | `function_result` phải có `.data` cho nhánh `mcp` của runner (`agent_task_runner.py:265-277`) |
| `plan` | `PlanEvent(CREATED` lần đầu `/UPDATED)` + `StepEvent` cho bước đổi trạng thái | xem 3.3 |
| `ask_user` | `MessageEvent(assistant, text)` **rồi** `WaitEvent()` | câu hỏi phải hiện trong chat trước khi UI dừng chờ |
| `usage` | — | ghi Mongo (mục 5) |
| `done` | flush buf → `PlanEvent(COMPLETED)` nếu có plan → `DoneEvent()` | |
| `error` | `ErrorEvent(error="<câu tiếng Việt> (mã: <code>)")` | bảng câu ở 3.4 |

**Số thứ tự do backend cấp, không dùng timestamp.** Hai bộ đếm: `seq` của sandbox (1.3) cho phát
lại/nối lại; thứ tự `AgentEvent` do Redis stream quyết định — `output_stream.put` trả id và runner
gán `event.id = event_id` (`agent_task_runner.py:117-119`, `redis_stream_queue.py:86`). Vì 1.5 bỏ
nguồn thứ hai, **không còn chỗ nào trộn theo timestamp** — viết thành comment đầu `cli_engine.py`.

### 3.2 Nhóm tool — tái dùng nguyên `_handle_tool_event`

`_handle_tool_event` (`agent_task_runner.py:195-289`) phân nhánh theo tập đóng
`browser|search|shell|file|skill|mcp`, lạ thì chỉ log cảnh báo (`:286-287`). Vì tool MCP shell/file
của đợt 1 gọi lại **đúng REST `/api/v1/shell|file`** (spec 02 §4 phương án B) nên dùng chung
`ShellService.active_shells` ⇒ `view_shell(function_args["id"])` (`:225`) chạy đúng. Nhờ vậy flow
không viết lại dòng nào sinh `tool_content`, và được `TerminalUpdateEvent`/`FileUpdateEvent` miễn
phí (`agent_task_runner.py:446-473`). `tool_group(name)`: `shell_*`→`shell`; `file_*`→`file`;
`browser_*`→`browser`; 3 tool tiến độ → không phát ToolEvent; **mọi tool gốc của agy**
(`run_command`, `view_file`, `search_web`, …) → `mcp` vì `McpToolContent` là viewer tổng quát
(`event.py:68-70`). `run_command` **không** map vào `shell`: không có shell id của REST nên
`view_shell` vô nghĩa.

### 3.3 Dựng `Plan` từ `plan_update`

Giữ `self._plan`; khi `resume` lấy lại bằng `session.get_last_plan()` (`domain/models/session.py:63-68`).
`Step(id=s["id"], description=s.get("description",""), status=map_status(s["status"]))`
(`domain/models/plan.py:12-19`); `map_status`: `pending→PENDING`, `running|in_progress→RUNNING`,
`completed→COMPLETED`, `failed→FAILED` — cùng ngữ nghĩa `_normalize_step_statuses`
(`domain/services/tools/plan.py:6-14`). Lần đầu `PlanEvent(CREATED)`, sau đó `UPDATED`. So snapshot
cũ/mới: bước đổi sang `RUNNING` → `StepEvent(STARTED)`, `COMPLETED`/`FAILED` → `StepEvent` tương ứng.

### 3.4 Lỗi hiển thị tiếng Việt

`chua_dang_nhap` → "Phiên đăng nhập của động cơ CLI không còn hiệu lực. Cần đăng nhập lại.";
`het_quota` → "Tài khoản động cơ CLI đã hết hạn mức. Đổi model hoặc chờ reset."; `timeout` → "Động
cơ CLI quá thời gian cho phép của lượt này."; `tien_trinh_chet` → "Tiến trình động cơ CLI đã chết
trước khi báo kết quả."; `khac` → "Động cơ CLI báo lỗi: <text rút gọn 300 ký tự>." Tuyệt đối
**không tự xoay sang tài khoản khác** (luật cứng `00-tong-quan.md` §7.3).

## 4. Chọn động cơ

1. `domain/models/session.py`: `class EngineKind(str, Enum): PLAN_ACT="plan_act"; AGY="agy";
   CLAUDE_CODE="claude_code"`; trên `Session` (`:41`) thêm `engine: EngineKind = PLAN_ACT`,
   `conversation_ref: Optional[str] = None`, `engine_last_seq: int = 0`; trên `SessionSummary`
   (`:25`) thêm `engine`.
2. `core/config.py` (sau `:62`): `gen_engine_default="plan_act"`, `gen_engine_model_agy=None`,
   `gen_engine_effort="medium"`, `gen_engine_dev_home=None`, `gen_engine_binary_agy="agy"`,
   `gen_engine_idle_timeout=600`, `gen_engine_max_turn_seconds=3600`, `gen_engine_raw_keep=True`,
   `gen_engine_raw_max_bytes=2_000_000`. Env viết hoa (`BaseSettings` không prefix); ghi vào
   `.env.example` cạnh khối `MCP configuration`.
3. `AgentService.create_session` (`application/services/agent_service.py:61-67`) truyền
   `engine=EngineKind(settings.gen_engine_default)`.
4. **Điểm rẽ**: `AgentTaskRunner.__init__` đang hard-code `PlanActFlow` (`agent_task_runner.py:93-104`)
   và là hàm **sync** nên không đọc được Session ⇒ sửa ở **factory** (`create_runner` vốn async,
   `:549`): đọc `session = await self._session_repository.find_by_id(params["session_id"])`, truyền
   `engine=session.engine`; `__init__` gọi `self._flow = self._build_flow(engine)` — `plan_act` →
   `PlanActFlow` **y nguyên tham số cũ**, `agy|claude_code` → `CliEngineFlow`. `build_params`
   (`:540-547`) không đổi; `AgentDomainService` không đổi.
5. `_run_flow` (`:421-434`): bọc `set_enabled_skills`/`set_skill_catalog` bằng `hasattr` —
   `CliEngineFlow` đợt 2 **không** nhận skill (render skill vào HOME là đợt 3).
6. Đường API, bắt chước **đúng** `task_mode`: `domain/repositories/session_repository.py:95` thêm
   `update_engine`/`update_conversation_ref`/`update_engine_cursor`;
   `mongo_session_repository.py:303-312` nhân bản 3 method, projection `:28` thêm `"engine": 1`,
   `_summary_from_doc:71` thêm `engine=doc.get("engine") or PLAN_ACT`;
   `infrastructure/models/documents.py:125` thêm 3 field; `interfaces/schemas/session.py:27,42,126`;
   `interfaces/api/session_routes.py:131-142` thêm `PATCH /sessions/{id}/engine`. Frontend **không
   sửa** (đổi engine bằng `curl`, đúng `00-tong-quan.md` §8).

## 5. Lưu NDJSON thô + usage vào Mongo

**Một document / một lượt** (không phải một document / một dòng).
`infrastructure/models/documents.py` (sau `SessionDocument`, `:145`):

```python
class EngineRunDocument(Document):
    run_id: str; session_id: str; user_id: str
    tenant_id: Optional[str] = None       # chỗ dành cho SaaS (00 §11); đợt 2 luôn None
    engine: str; conversation_ref: Optional[str] = None; turn_index: int
    started_at: datetime; ended_at: Optional[datetime] = None
    status: Optional[str] = None          # RUNNING|WAITING|SUCCESS|ERROR
    lines: List[Dict[str, Any]] = []      # {seq, stream, ts, raw}
    lines_dropped: int = 0; bytes_total: int = 0; usage: Dict[str, Any] = {}
    class Settings:
        name = "engine_runs"
        indexes = ["session_id", "user_id",
                   IndexModel([("session_id", ASCENDING), ("turn_index", ASCENDING)],
                              name="session_turn", unique=True)]
```

- Đăng ký ở **cả hai** `init_beanie`: `backend/app/main.py:45-53` **và**
  `infrastructure/external/task/celery_worker.py:102-110`. Quên chỗ thứ hai thì `TASK_BACKEND=celery`
  nổ runtime.
- Repo mới `domain/repositories/engine_run_repository.py` (Protocol) +
  `infrastructure/repositories/mongo_engine_run_repository.py` (`open_turn`, `append_lines`,
  `close_turn`, `find_by_session`); nối dây ở `interfaces/dependencies.py:84-94` và
  `celery_worker._build_runner_factory`.
- **Ghi gộp**: đệm trong bộ nhớ, flush `$push: {lines: {$each: [...]}}` mỗi 50 dòng hoặc 2 giây.
- **Giới hạn** (BSON tối đa 16 MB ⇒ chặn trước): 2 MB/lượt (`GEN_ENGINE_RAW_MAX_BYTES`), mỗi dòng
  cắt ở 32 KiB (`{"truncated": true}`); trước khi cắt `_shrink(raw)` bỏ `step_update.tool_info.output`
  vượt 2 KiB (trường phình nhất). Vượt trần → dừng append, `lines_dropped += 1`.
  `GEN_ENGINE_RAW_KEEP=false` → chỉ lưu `usage` + `status`.
- **Usage theo phiên**: `SessionDocument` thêm `engine_usage: Dict[str, Any] = {}` + repo
  `add_engine_usage(session_id, usage)` dùng `$inc` cho `input_tokens`, `output_tokens`,
  `cache_read_tokens`, `thinking_tokens`, `total_tokens`, `turns`.
- `_shrink` phải xoá khoá `env`, `authorization`, `token`, `refresh_token` nếu gặp (gitleaks không
  soi Mongo ⇒ chặn ở code).

## 6. HOME tạm tối thiểu cho đợt 2 (bản đầy đủ ở đợt 3)

**Đã đo:** phiên `agy` trên máy Boss **không nằm trong `~/.gemini` dạng file** —
`docs/evidence/dot-1/README.md:43-52` (`grep -rl "refresh_token|access_token" ~/.gemini` không ra
gì) ⇒ gần như chắc chắn trong keyring ⇒ **`docker cp ~/.gemini` không dùng được** (bằng chứng
`docs/evidence/dot-1/agy-p-auth-failed.txt`).

**Cách tạm:** đăng nhập **tay một lần ngay trong container dev**, vào thư mục bind-mount ra host để
sống qua `restart`. Không chạm tenant, không chạm Session. `core/config.py: gen_engine_dev_home` —
nếu đặt thì flow truyền `HOME=<giá trị>` cho `/engine/start`. `docker-compose-development.yml`
service `sandbox` (`:66-70`) thêm volume
`- ${GEN_ENGINE_DEV_HOME_HOST:-./.dev-home}:/home/ubuntu/.engine-home`; service `backend` (`:58-59`)
thêm `- GEN_ENGINE_DEV_HOME=/home/ubuntu/.engine-home`; `.gitignore` thêm `.dev-home/`. **Không**
sửa `docker-compose.yml` (production).

```bash
C=docker-compose-development.yml
mkdir -p .dev-home && chmod 700 .dev-home
docker compose -f $C up -d --build sandbox
# 1) Đăng nhập — BẮT BUỘC -it (agy đọc mã dán từ terminal, xem agy-p-auth-failed.txt)
docker compose -f $C exec -u ubuntu -e HOME=/home/ubuntu/.engine-home -it sandbox agy
#    → mở URL in ra bằng browser trên host, đăng nhập, dán mã lại vào PTY
# 2) Xác minh container KHÔNG có keyring (nên agy buộc phải ghi ra file)
docker compose -f $C exec sandbox bash -lc \
 'command -v secret-tool gnome-keyring-daemon; ls /run/user 2>/dev/null; echo "DBUS=$DBUS_SESSION_BUS_ADDRESS"'
# 3) Xác minh token đã nằm ở FILE trong HOME tạm (chỉ grep -l, KHÔNG in nội dung)
docker compose -f $C exec -u ubuntu sandbox bash -lc \
 'ls -laR /home/ubuntu/.engine-home | head -60;
  grep -rlI "refresh_token\|access_token\|id_token" /home/ubuntu/.engine-home 2>/dev/null'
# 4) Bằng chứng chức năng (so với bản thất bại đợt 1)
docker compose -f $C exec -u ubuntu -e HOME=/home/ubuntu/.engine-home sandbox bash -lc \
 'agy -p --output-format stream-json --model "$MODEL" --effort low \
      --dangerously-skip-permissions "in ra dung chu: ok"'
# 5) Bền qua restart (chứng minh phiên ở bind-mount, không trong container)
docker compose -f $C restart sandbox && sleep 20 && <lặp lệnh bước 4>
```

- **Nếu bước 3 không thấy file token nào: DỪNG, không thử vòng thứ tư.** Đợt 2 chuyển sang
  `fake-agy` (mục 7) cho toàn bộ test, các mục nghiệm thu cần agy thật dời sang đợt 3; ghi kết luận
  + log vào `docs/evidence/dot-2/README.md` và comment lên Issue #30.
- **Vá denylist MCP (bắt buộc, ~5 dòng).** `sandbox/mcp/rest_client.py:26-28` chặn `~/.gemini`,
  `~/.claude`, `~/.gen-agents`, nhưng `program:mcp` chạy với `HOME=/home/ubuntu`
  (`sandbox/supervisord.conf`) nên `~` **không** nở ra `/home/ubuntu/.engine-home` ⇒ thêm
  `GEN_ENGINE_DEV_HOME` (và `<dev_home>/.gemini`, `<dev_home>/.claude`) vào `_FORBIDDEN_DIRS`, nếu
  không agent tự đọc được token của chính nó qua `file_read`.
- `.dev-home` quyền 700, gitignore, **không bao giờ** đặt `GEN_ENGINE_DEV_HOME` ở production.

## 7. Mock cho test offline + Issue #35

`CliEngineFlow` **không gọi LLM** ⇒ mockserver không phải đường tới hạn; đừng chặn đợt 2 vào #35.

1. **Offline unit (job `backend-offline`).** `backend/tests/harness.py` thêm `FakeEngine` (implement
   `Engine`, nhận list dict NDJSON đã script) + `build_cli_engine_flow` song song
   `build_plan_act_flow` (`harness.py:162-178`); `FakeSandbox` (`harness.py:84-121`) thêm 5 method
   `engine_*`. Test mới: `test_agy_adapter.py` (dịch thuần, dữ liệu vào là **nguyên văn mẫu spec 01
   §3** lưu ở `backend/tests/fixtures/agy_ndjson_samples.ndjson`, thêm dòng lỗi auth từ
   `docs/evidence/dot-1/agy-p-auth-failed.txt`) và `test_cli_engine_flow.py` (`init→TitleEvent`; gom
   `text_delta` → 1 `MessageEvent`; tool đúng nhóm + `ToolStatus`; `plan_update` →
   `PlanEvent`+`StepEvent`; `message_ask_user` → `MessageEvent`+`WaitEvent` và `is_done()` False;
   nối lại từ `WAITING` dùng `from_seq`; `result ERROR` → `ErrorEvent` tiếng Việt; `seq` tăng đơn
   điệu; trần raw cắt đúng).
2. **Sandbox-level (job `e2e`, bước "Sandbox API tests").** `sandbox/tests/fake_agy.py`: đọc từng
   dòng stream-json trên stdin, in `init` một lần, vài `step_update` (gồm một `tool` ACTIVE/DONE và
   một `plan_update`), rồi `result` SUCCESS kèm `usage`; `FAKE_AGY_MODE=ask` phát `message_ask_user`,
   `=error` phát `result` ERROR auth. `sandbox/tests/test_engine_api.py`: dòng > 64 KiB vẫn nguyên
   (kiểm `limit`), `from_seq` phát lại đúng, `start` hai lần → `reused`, `stop` → `alive=false`. Dev
   compose đặt `ENGINE_ALLOWED_BINARIES="agy,claude,fake_agy.py"`.
3. **E2E qua backend thật (`-m e2e`).** PATCH engine → `agy`, env
   `GEN_ENGINE_BINARY_AGY=/app/tests/fake_agy.py`, chat một lượt, kiểm chuỗi `AgentEvent` trên
   WebSocket. Chưa nối dây thì `pytest.skip("fake-agy chưa cài")` — CI chạy `-rs` nên skip hiện rõ,
   không giả xanh.

**Issue #35 — nguyên nhân gốc.** Mockserver phát lại theo **một con trỏ toàn cục** `current_index`
(`mockserver/main.py:117`, `:132-133`) với heuristic reset `len(request.messages) == 2 and
current_index > 1` (`:124-126`). Nhưng `PlanActFlow` chạy **hai agent có registry tool khác nhau**:
PlannerAgent chỉ có `create_plan`/`update_plan` (`domain/services/agents/planner.py:26,41`,
`tools=[]` ở `:61`), executor có `message_*`/`shell_*`/`file_*` (`flows/plan_act.py:90-97`). Hệ quả:
`default.yaml:12` là script "single-loop Manus" của upstream mở đầu bằng `message_notify_user` →
planner không biết tool đó → `"Unknown tool: message_notify_user"`
(`domain/services/agents/base.py:265`); còn `browser_tools.yaml:9` mở đầu đúng `create_plan` nhưng
**lượt gọi đầu của executor cũng có đúng 2 message** nên trúng heuristic reset → nhận lại
`create_plan` → `"Unknown tool: create_plan"`.

**Vá tối thiểu (~25 dòng, `mockserver/main.py`):** đổi `current_index` thành `cursors: dict[str, int]`
khoá `sha1(messages[0].content)[:16]` (mỗi agent một con trỏ vì system prompt khác nhau); reset con
trỏ **của chính khoá đó** khi nó xuất hiện với đúng 2 message; `/mock/reset` và `/mock/scenario` xoá
sạch `cursors`. Rồi sửa **đúng hai** scenario mà regression đợt 2 cần (`default.yaml`,
`plan_act_e2e.yaml`) sang dạng `{planner: [...], executor: [...]}` (giữ tương thích dạng list cũ).
10 scenario còn lại để nguyên + ghi chú lên Issue #35.

## 8. Nghiệm thu (spec 01 §8 mục 1–3 + DoD "mở lại phiên cũ thấy lịch sử")

Bằng chứng trong `docs/evidence/dot-2/` + một `README.md` chỉ mục. **Đuôi `.txt`, không `.log`** —
`.gitignore` chặn `.log` (bài học đợt 0, commit `59259c7`).

| # | Kịch bản | Cách kiểm | Bằng chứng |
| --- | --- | --- | --- |
| 1 | agy nhận lượt qua stdin, trả `result` SUCCESS | mục 6 bước 4–5, rồi qua `/engine/start`+`/send` + `curl -N .../engine/events?engine_id=...` | `01-agy-stdin-result-success.txt` (NDJSON `init`→`result`), `01-engine-api-sse.txt` |
| 1b | **Đo tên tool MCP agy in ra** (chốt `strip_mcp_prefix`) | nhiệm vụ buộc gọi `file_write` qua MCP, `grep tool_name` | `01b-mcp-tool-name-measured.txt` + cập nhật mục 2.1 |
| 2 | "Mở trang web X, chụp màn hình, ghi `output/tom-tat.md`" | UI ai-manus, phiên `engine=agy` | `02-ui-browser-toolevent.png`, `02-novnc.png`, `02-output-file.png`, `02-ndjson.txt` |
| 3 | `message_ask_user` → UI dừng chờ → trả lời → tiếp tục cùng `conversation_id` | UI + `db.engine_runs.find({session_id}).sort({turn_index:1})` | `03-wait-resume-ui.png`, `03-conversation-ref.txt` (hai lượt cùng id), `03-ws-events.txt` |
| 4 | **DoD** mở lại phiên cũ thấy lịch sử | `docker compose -f $C rm -sf sandbox` → reload → mở lại phiên | `04-history-after-sandbox-destroy.png`, `04-session-events.txt` |
| 5 | Lỗi chưa đăng nhập hiện tiếng Việt, không treo | `mv .dev-home/.gemini{,.bak}` rồi chat | `05-error-vi.png`, `05-error-ndjson.txt` |
| 6 | Test tự động | `cd backend && uv run pytest --ignore=tests/test_api_file.py --ignore=tests/test_auth_routes.py --ignore=tests/test_sandbox_file.py -m "not e2e"`; `cd sandbox && uv run pytest -q`; `cd backend && uv run pytest -m e2e -rs` | `06-pytest-backend-offline.txt`, `06-pytest-sandbox.txt`, `06-pytest-e2e.txt` |
| 7 | Không hồi quy `plan_act` | lệnh #6 + 1 nhiệm vụ tay trên phiên `engine=plan_act` | `07-plan-act-khong-hoi-quy.txt` |

Spec 01 §8 mục 4–5 (đổi sang Claude Code, thu phiên đăng nhập) **thuộc đợt 3**.

## 9. File đụng tới, thứ tự commit, rủi ro

**Mới (~1.750 dòng mã + ~860 test):** `sandbox/app/services/engine.py` 200 ·
`sandbox/app/api/v1/engine.py` 110 · `sandbox/app/schemas/engine.py` 45 ·
`sandbox/tests/fake_agy.py` 90 · `sandbox/tests/test_engine_api.py` 150 ·
`backend/app/domain/external/engine.py` 110 ·
`backend/app/infrastructure/external/engine/{agy_engine.py 260, claude_code_engine.py 60, __init__.py 30}` ·
`backend/app/domain/services/flows/cli_engine.py` 330 ·
`backend/app/domain/repositories/engine_run_repository.py` 40 ·
`backend/app/infrastructure/repositories/mongo_engine_run_repository.py` 130 ·
`backend/tests/{test_agy_adapter.py 190, test_cli_engine_flow.py 300, test_e2e_cli_engine.py 110,
fixtures/agy_ndjson_samples.ndjson 8}` · `docs/evidence/dot-2/**`.

**Sửa (~430 dòng):** `sandbox/app/api/router.py` 2 · `sandbox/mcp/rest_client.py` 5 ·
`backend/app/domain/external/sandbox.py` 40 ·
`backend/app/infrastructure/external/sandbox/docker_sandbox.py` 90 ·
`backend/app/domain/models/session.py` 15 · `backend/app/core/config.py` 15 ·
`backend/app/domain/services/agent_task_runner.py` 45 ·
`backend/app/application/services/agent_service.py` 20 ·
`backend/app/domain/repositories/session_repository.py` 20 ·
`backend/app/infrastructure/repositories/mongo_session_repository.py` 45 ·
`backend/app/infrastructure/models/documents.py` 40 · `backend/app/main.py` 2 ·
`backend/app/infrastructure/external/task/celery_worker.py` 6 ·
`backend/app/interfaces/dependencies.py` 12 · `backend/app/interfaces/schemas/session.py` 12 ·
`backend/app/interfaces/api/session_routes.py` 25 · `backend/tests/harness.py` 120 ·
`mockserver/main.py` 25 · `mockserver/mock_datas/{default,plan_act_e2e}.yaml` 30 ·
`docker-compose-development.yml` 6 · `.env.example`/`.gitignore` 20 ·
`docs/spec/{01-dong-co-cli,02-mcp-trong-sandbox}.md` 35 (mục "Lệch so với spec").

**Thứ tự commit (6, mỗi commit test xanh):** (1) `feat(sandbox): endpoint /engine/* chay CLI nhu
tien trinh dai (Refs #30)` — service/API/schema/router + `fake_agy.py` + `test_engine_api.py` + vá
denylist; (2) `feat(backend): hop dong Engine + adapter agy dich NDJSON (Refs #30)` — `engine.py`,
`agy_engine.py`, khung claude_code, mở rộng `Sandbox` Protocol + `DockerSandbox`,
`test_agy_adapter.py`; (3) `feat(backend): CliEngineFlow anh xa EngineEvent sang AgentEvent (Refs
#30)` — flow + `FakeEngine` + `test_cli_engine_flow.py`, **chưa nối vào runner** ⇒ không rủi ro hồi
quy; (4) `feat(backend): truong engine tren Session + diem re trong task runner (Refs #30)`;
(5) `feat(backend): luu NDJSON tho va usage vao Mongo (Refs #30)` — `EngineRunDocument`, repo, giới
hạn kích thước, `init_beanie` **cả hai chỗ**; (6) `fix(mockserver): con tro phat lai theo tung agent
(Refs #35) + bang chung dot 2 (Refs #30)` — vá #35, HOME dev trong compose, `.env.example`,
`docs/evidence/dot-2/`, cập nhật `01`/`02`.

| Rủi ro | Né thế nào |
| --- | --- |
| `StreamReader` 64 KiB → `LimitOverrunError` ngay dòng tool đầu | `limit=8 MiB` + bắt lỗi → dòng `truncated` (1.3); test dòng > 64 KiB |
| Sandbox tự hết hạn giữa nhiệm vụ (SSE không gia hạn timeout) | keepalive `GET /engine/status` mỗi 60s + comment giải thích để không bị xoá oan |
| Mất sự kiện khi phiên qua `WAITING` (Task mới, kết nối mới) | deque + `seq` + `from_seq` + cursor `engine_last_seq` trên Session |
| Prefix tên tool MCP đoán sai ⇒ không ra `PlanEvent`/`WaitEvent` | regex khoan dung + **đo thật** (nghiệm thu #1b); lệch thì sửa 1 regex |
| `_handle_tool_event` cảnh báo "unknown tool", UI trắng | `tool_group()` chỉ trả 6 giá trị runner biết (`agent_task_runner.py:217-287`), mặc định `mcp` |
| Quên đăng ký Document ở `celery_worker.py` | commit 5 sửa cả hai + checklist trong PR |
| Document Mongo vượt 16 MB vì `tool_info.output` | `_shrink` + trần 2 MB/lượt + cắt dòng 32 KiB |
| agy trong container vẫn đòi keyring | mục 6: dừng sau 1 vòng, chuyển `fake-agy`, dời nghiệm thu agy thật sang đợt 3, báo Issue #30 |
| Hồi quy `plan_act` | điểm rẽ ở factory, nhánh `plan_act` dựng y nguyên tham số cũ; nghiệm thu #7 |
| Token lộ qua `file_read` của chính agent | vá `_FORBIDDEN_DIRS` cho dev HOME (mục 6) |
| Phình phạm vi sang đợt 3 | đợt 2 **không** render cấu hình; HOME tạm chỉ là biến trỏ thư mục đã đăng nhập tay |

## Câu hỏi mở cho Claude điều phối

1. **`message_ask_user` dừng chờ ở biên lượt (1.5) có đủ cho nghiệm thu §8.3?** CLI kết thúc lượt
   sau khi hỏi, người trả lời thì bơm lượt mới cùng `conversation_id` — UI đúng (dừng chờ, trả lời,
   chạy tiếp) nhưng *không* phải treo tool giữa lượt. Treo thật cần kênh liên tiến trình
   (`~/.gen-agents/answers/<ask_id>.json` + `/engine/answer`), ~120 dòng. **Chốt: đợt 2 làm biên
   lượt, hay gộp luôn bản treo thật?**
2. **Model/effort mặc định cho agy** (`GEN_ENGINE_MODEL_AGY`): đợt 1 dùng
   `gemini-3.8-flash-low --effort low` cho rẻ. Đề xuất giữ `low` khi test/nghiệm thu — **cần Boss
   xác nhận tên model hiện hành** (tra nguồn, không lấy theo trí nhớ).
3. **Phạm vi #35**: chốt vá con trỏ + 2 scenario như mục 7, hay làm sạch cả 12 scenario trong đợt 2?
   Đề xuất chỉ 2, phần còn lại thành Issue riêng.
4. **`conversation_ref` có cần mã hoá khi lưu Session?** Nó không phải secret (chỉ là id hội thoại
   cục bộ trong `<HOME>/.gemini/antigravity-cli/conversations/<id>.db`) — đề xuất lưu thẳng; xác
   nhận để không phải quay lại.

## Chốt của Claude điều phối (09/10/2026 19:10)
1. **`message_ask_user` dừng chờ ở biên lượt** cho đợt 2 (CLI hỏi xong thì kết thúc lượt; câu trả lời bơm lượt mới cùng `conversation_id`). Instruction sinh vào AGENTS.md phải nói rõ "hỏi người dùng xong thì dừng lượt, không làm tiếp". Bản "treo tool thật" (kênh `/engine/answer`) để đợt 3 nếu nghiệm thu thấy CLI hay làm tiếp sau khi hỏi.
2. **Model mặc định khi test/nghiệm thu**: `gemini-3.8-flash-low`, `--effort low` — đã xác minh bằng `agy models` trên máy Boss ngày 09/10/2026 (danh sách thật: gemini-3.8/3.7/3.6-flash high|medium|low, gemini-3.1-pro high|low, claude-sonnet-4-6, claude-opus-4-6-thinking, gpt-oss-120b-medium). `GEN_ENGINE_MODEL_AGY` mặc định giá trị này; UI chọn model làm ở đợt 4.
3. **#35**: chỉ vá con trỏ theo hash system prompt + 2 scenario cần cho test đợt 2; 10 scenario còn lại → Sonnet mở Issue riêng khi nộp PR.
4. **`conversation_ref` lưu thẳng** trong Session (không phải secret).
