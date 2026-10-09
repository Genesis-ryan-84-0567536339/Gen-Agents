# 03 — Cấu hình thuộc harness

> Mô hình dữ liệu cho mọi thứ một CLI engine cần mà harness sở hữu: Skill,
> Instruction, cấu hình MCP, phiên đăng nhập CLI, bộ nhớ nhiệm vụ, lịch sử.
> Nguyên tắc chung: xem mục 6 "Nguyên tắc sở hữu dữ liệu" của
> `00-tong-quan.md`.

## 1. Skill — tái dùng model có sẵn

ai-manus đã có `Skill`/`UserSkill`
(`backend/app/domain/models/skill.py`) và dịch vụ đồng bộ xuống sandbox
(`backend/app/application/services/skill_runtime_service.py`). Dùng lại
nguyên, không model mới:

- `Skill.body` (SKILL.md) + `SkillRuntimeService.sync_enabled_skills_to_sandbox`
  (`skill_runtime_service.py:50`) đã ghi package skill vào
  `/home/ubuntu/skills/{name}/` trong sandbox trước khi agent chạy
  (`SKILLS_ROOT`, `backend/app/domain/skills/package.py:8`) — việc này
  **không đổi** cho CliEngineFlow, chạy y như với PlanActFlow.
- **Cộng thêm cho engine CLI**: cùng nội dung SKILL.md được ghi vào thư mục
  skill gốc mà CLI tự quét, để CLI dùng được skill theo cơ chế của chính nó
  thay vì chỉ đọc danh mục trong Instruction — agy (đã đo v1.3.2):
  `<HOME tạm>/.gemini/config/skills/<tên>/SKILL.md` (global) hoặc
  `/home/ubuntu/.agents/skills/<tên>/SKILL.md` (chỉ phiên này); Claude Code:
  thư mục skill tương ứng (tra lúc code — xem `01-dong-co-cli.md` mục 9).
- Khác biệt duy nhất với PlanActFlow: PlanActFlow lộ skill cho LLM qua tool
  `load_skill` (`backend/app/domain/services/tools/skill.py` — danh mục L1
  nhúng trong system prompt, L2 lấy lúc gọi tool). CliEngineFlow không có
  khái niệm system prompt riêng của backend — danh mục skill (tên +
  description, từ `SkillRuntimeService.list_enabled_skill_pairs`) phải được
  **render vào Instruction** (mục 2) thay vì vào một tool riêng, vì agy/
  Claude Code đọc năng lực từ file hướng dẫn gốc (AGENTS.md/CLAUDE.md), không
  gọi `load_skill` kiểu LangChain function-calling.

## 2. Instruction — một văn bản gốc, nhiều bản render

**Mô hình mới** (chưa có trong ai-manus gốc — `Project.instruction` hiện chỉ
là một chuỗi tự do gắn với 1 project, không phân biệt theo CLI):

```
Instruction (gốc, lưu ở harness, Markdown + biến nội suy)
  = instruction riêng của người dùng/project (nếu có, kế tục Project.instruction)
  + danh mục skill đang bật (từ mục 1)
  + luật cứng không đổi theo engine (mục 7 của 00-tong-quan.md)
       ↓ render lúc tạo sandbox session
  ├── /home/ubuntu/AGENTS.md  (cho agy)
  └── /home/ubuntu/CLAUDE.md  (cho Claude Code CLI, cùng thư mục)
```

- Một bản gốc, hai bản render ra 2 file khác tên nhưng cùng thư mục làm việc
  — chỉ file khớp tên CLI đang chạy mới được CLI đó đọc, file kia vẫn nằm đó
  vô hại: đã đo, agy chỉ đọc `GEMINI.md`/`AGENTS.md` và **không** đọc
  `CLAUDE.md`.
- Việc render là thuần text/template (biến: tên dự án, danh mục skill, luật
  cứng) — không cần logic khác nhau giữa 2 CLI ngoài tên file đích. Nếu một
  CLI cần cấu trúc khác (heading riêng, giới hạn độ dài), thêm converter nhỏ
  theo CLI đó, không đổi nguồn gốc.
- Lưu nguồn gốc này ở đâu: thêm trường mới trên `Session` hoặc một model
  `CliEngineConfig` riêng (tham khảo thiết kế `Project`
  (`backend/app/domain/models/project.py`) — field `instruction: Optional[str]`
  đã có, có thể mở rộng thành object có thêm `extra_sections` thay vì thêm
  model hoàn toàn mới, cần quyết định lúc code).

## 3. Cấu hình MCP — một bản gốc, render ra định dạng từng CLI

Giống Instruction, không nhân đôi nguồn:

```
MCPConfig gốc (schema đã có: backend/app/domain/models/mcp_config.py)
  = server "sandbox" (mục 02-mcp-trong-sandbox.md) + mọi MCP server khác
    người dùng tự thêm (reuse MCPServerConfig.transport/command/url/headers)
       ↓ render lúc tạo sandbox session
  ├── <HOME tạm>/mcp.json  (Claude Code CLI, truyền qua
  │                          --mcp-config … --strict-mcp-config)
  └── <HOME tạm>/.gemini/config/mcp_config.json  (agy)
      — cùng schema {"mcpServers": {...}}, đã đo; xem 02 mục 5
```

- Model gốc **tái dùng `MCPConfig`/`MCPServerConfig` đã có**
  (`backend/app/domain/models/mcp_config.py:12-56`) — không viết schema mới.
  Hiện ai-manus đọc `MCPConfig` từ 1 file tĩnh `/etc/mcp.json`
  (`backend/app/core/config.py:138`, `FileMcpRepository`); việc mới là thêm
  một **repository theo user/tenant** (Mongo, không phải file tĩnh) để mỗi
  người có cấu hình MCP riêng, rồi render ra sandbox — không đổi
  `MCPConfig`/`MCPServerConfig`.
- Server "sandbox" ở mục 02 luôn được harness tự thêm vào bản render cho mọi
  phiên CliEngineFlow (người dùng không tự xoá được — đây là tool bắt buộc
  để CLI hoạt động), các MCP server khác người dùng tự quản lý qua UI cấu
  hình MCP hiện có (nếu có) hoặc API mới.

## 4. Phiên đăng nhập CLI

**Mô hình mới**, đây là phần nhạy cảm nhất (bảo mật) trong toàn spec.

### 4.1 Lưu trữ

- Một record `CliLoginSession` mới: `id`, `tenant_id` (mục "Đa khách thuê"
  dưới), `user_id`, `cli_kind` (`agy` | `claude_code`), `encrypted_blob`
  (toàn bộ nội dung các đường dẫn trong HOME mà CLI đó dùng để giữ phiên đăng
  nhập — danh sách đúng ở mục 4.2 bước 4; là token OAuth do CLI tự ghi, không
  phải giá trị secret ghi tay), `created_at`,
  `last_used_at`, `revoked_at`.
- Mã hoá bằng key quản lý ở harness (không phải Vault Gen-hub — đây là dữ
  liệu *của Gen-Agents*, không phải secret nghiên cứu của Boss; tham khảo
  cách ai-manus đã mã hoá thứ nhạy cảm khác nếu có, hoặc dùng
  `cryptography.fernet` với key từ biến môi trường/`.env`, không hard-code).
- **Không** lưu plaintext trong Mongo, **không** lưu trong file thường như
  `/etc/mcp.json` hiện tại đang làm với secret MCP (mục 9 của
  `00-tong-quan.md` đã nêu đây là rủi ro kế thừa — phiên đăng nhập CLI không
  được lặp lại lỗi đó).

### 4.2 Luồng đăng nhập lần đầu (chưa có `CliLoginSession` cho cli_kind đó)

1. Harness tạo sandbox tạm (hoặc dùng sandbox của phiên đang mở) chỉ để đăng
   nhập, chạy CLI ở chế độ đăng nhập (`agy auth login` / lệnh tương đương
   Claude Code CLI) qua `sandbox.exec_command` **tương tác** — nghĩa là cần
   `wait_for_process`/`write_to_process` của `Sandbox` Protocol
   (`backend/app/domain/external/sandbox.py` — các method đã có y hệt phần
   shell hiện tại) chạy trong một pseudo-terminal.
2. CLI in ra một link đăng nhập (OAuth device-code hoặc tương tự) + một mã
   ngắn. Harness bắt dòng đó từ output pseudo-terminal, hiện lên UI cho người
   dùng (link bấm được + mã dán).
3. Người dùng mở link ở máy của họ (ngoài sandbox, trình duyệt thật của họ —
   **không** phải Chrome trong sandbox, vì đây là tài khoản cá nhân của họ,
   không phải việc nhiệm vụ), đăng nhập, dán mã ngược lại nếu CLI yêu cầu
   (qua `write_to_process`).
4. CLI xác nhận đăng nhập xong, harness đọc đúng những đường dẫn trong HOME
   nơi CLI vừa ghi token (đã đo): **agy** → `~/.gemini/antigravity-cli/`
   (`settings.json`, `conversations/`) và `~/.gemini/config/`; **Claude Code**
   → `~/.claude/.credentials.json` *và* `~/.claude.json` (file này nằm ở gốc
   HOME, không trong `~/.claude/` — gói cả hai, thiếu một cái là coi như chưa
   đăng nhập). Đóng gói + mã hoá thành `encrypted_blob`, lưu
   `CliLoginSession`, huỷ sandbox tạm.

### 4.3 Dùng lại cho mỗi nhiệm vụ

1. Trước khi chạy CLI trong sandbox nhiệm vụ, harness giải mã
   `encrypted_blob` của `CliLoginSession` đang hiệu lực, ghi ra một thư mục
   HOME tạm riêng của phiên (ví dụ qua `file_write` nhiều lần, hoặc
   `tar`+ghi 1 file rồi giải nén bằng `shell_exec` — cách nào ít round-trip
   hơn quyết định lúc code), set biến môi trường `HOME` (hoặc tương đương
   theo CLI) trỏ vào đó khi `exec_command` chạy CLI.
2. CLI chạy nhiệm vụ như thường, tự refresh token nếu cần (hành vi của chính
   CLI, harness không can thiệp).
3. Sau khi nhiệm vụ xong: harness đọc lại thư mục HOME tạm đó, nếu nội dung
   token đổi (refresh) thì mã hoá + cập nhật `encrypted_blob` (`last_used_at`
   cập nhật); sau đó xoá thư mục tạm khỏi sandbox trước khi huỷ container —
   **thu hồi**, không để lại bản rõ nào sống lâu hơn container.
4. `revoked_at` được set khi người dùng chủ động "đăng xuất" CLI đó từ UI
   harness — lần chạy kế tiếp quay lại luồng 4.2.

## 5. Bộ nhớ nhiệm vụ

- Nguồn trong lúc chạy: `/home/ubuntu/todo.md` + thư mục làm việc
  `/home/ubuntu/` (kết quả nhiệm vụ đặt ở `/home/ubuntu/output/`, xem
  `01-dong-co-cli.md` mục 5) trong sandbox — CLI tự ghi tự đọc, không khác gì một
  máy thật của nó.
- Sau nhiệm vụ: harness liệt kê + tải về những file đã đổi trong thư mục làm
  việc (dùng `file_find_by_name`/`file_read` qua tool API hiện có, hoặc một
  lệnh `tar` + download một lần cho rẻ round-trip), gắn vào `Session.files`
  (model `FileInfo` đã có, `backend/app/domain/models/file.py`) — **tái dùng
  đúng cơ chế file hiện có của ai-manus**, không có "bộ nhớ nhiệm vụ" là một
  khái niệm lưu trữ riêng.
- `todo.md` không drive Plan UI (ghi chú đã có sẵn trong `file.py:13` —
  nguyên tắc này giữ nguyên cho CliEngineFlow: Plan UI của ai-manus hiện tại
  có thể tạm ẩn/không áp dụng cho CliEngineFlow vì không có PlannerAgent,
  hoặc suy ra từ `PlanEvent` nếu adapter CLI dựng được — xem câu hỏi mở).

## 6. Lịch sử

- **NDJSON thô**: mọi dòng CLI in ra (`stream-json`) được harness lưu y
  nguyên, không mất mát, vào Mongo — một collection mới `cli_raw_logs` (hoặc
  trường mới trên `Session`), khoá theo `session_id` + thứ tự dòng. Mục đích:
  gỡ lỗi, xem lại đúng những gì CLI thực sự đã in, không phụ thuộc độ chính
  xác của bước ánh xạ sang `AgentEvent`.
- **AgentEvent**: như ai-manus hiện có, `Session.events`
  (`backend/app/domain/models/session.py:52`) — đây là thứ frontend/WebSocket
  dùng để hiển thị, không đổi.
- Hai nguồn song song, không nguồn nào thay nguồn kia: AgentEvent có thể mất
  chi tiết khi ánh xạ (ví dụ CLI in thêm metadata mà `AgentEvent` không có
  trường tương ứng — bỏ qua lúc ánh xạ), NDJSON thô giữ lại toàn bộ để tra
  cứu sau nếu cần.

## 7. Vòng đời

```
tạo container (docker_sandbox.py, như hiện có)
        ↓
sinh HOME tạm cho CLI (mục 4.3 bước 1) — chỉ khi engine = CLI
        ↓
sync skill (mục 1, không đổi) + render Instruction (mục 2) + MCP config (mục 3)
        ↓
chạy CLI qua exec_command, đọc NDJSON → AgentEvent (CliEngineFlow)
        ↓
hứng sự kiện realtime → Redis/WebSocket (không đổi so với PlanActFlow)
        ↓
CLI kết thúc nhiệm vụ (hoặc bị dừng tay)
        ↓
thu hồi: file nhiệm vụ (mục 5) + HOME tạm cập nhật lại CliLoginSession (mục 4.3 bước 3)
         + NDJSON thô đã ghi xuyên suốt (mục 6, không cần thu hồi cuối vì ghi stream)
        ↓
huỷ container
```

## 8. Bảng ánh xạ "thứ harness giữ → file cho agy → file cho Claude Code"

| Thứ harness giữ | Model/nguồn ở harness | File cho agy | File cho Claude Code |
| --- | --- | --- | --- |
| Skill đang bật | `Skill`/`UserSkill` (`skill.py`) | danh mục vào `AGENTS.md` + `~/.gemini/config/skills/<tên>/SKILL.md` | danh mục vào `CLAUDE.md` + thư mục skill của Claude Code |
| Instruction gốc | mới, mục 2 (mở rộng `Project.instruction`) | `AGENTS.md` | `CLAUDE.md` |
| Cấu hình MCP gốc | `MCPConfig`/`MCPServerConfig` (có sẵn) | `~/.gemini/config/mcp_config.json` | `<HOME tạm>/mcp.json` (qua `--mcp-config`) |
| Phiên đăng nhập CLI | mới: `CliLoginSession` (mục 4) | `~/.gemini/antigravity-cli/` + `~/.gemini/config/` | `~/.claude/.credentials.json` + `~/.claude.json` |
| Bộ nhớ nhiệm vụ | `Session.files` (có sẵn, `file.py` model) | `/home/ubuntu/` trong sandbox (CLI tự ghi) | như trên |
| Lịch sử | mới: NDJSON thô (collection mới) + `Session.events` (có sẵn) | stdout của `agy -p --output-format stream-json` | stdout của `claude -p --output-format stream-json` |

## 9. Đa khách thuê (bổ sung theo yêu cầu SaaS — xem mục 11 của `00-tong-quan.md`)

Phần này chi tiết hoá mô hình dữ liệu; mục 11 bên `00-tong-quan.md` giữ phần
khung và đánh dấu v0.1 vs sau — đọc mục đó trước.

### 9.1 Tenant là gì, nằm ở đâu trong schema hiện có

Thêm model mới `Tenant` (`id`, `name`, `created_at`, `plan`/`status` tối
giản cho v0.1 — không cần trường billing thật). Quan hệ: 1 `Tenant` — nhiều
`User` (`backend/app/domain/models/user.py`) — mỗi `User` vẫn có `user_id`
riêng như hiện tại (không đổi auth hiện có).

**v0.1 — chỉ thêm field, chưa enforce:**

| Model hiện có | Field `user_id`/`owner_user_id` đã có ở | Field `tenant_id` thêm |
| --- | --- | --- |
| `SessionDocument` | `documents.py:108` | cạnh `user_id`; index mới `[tenant_id, latest_message_at]` song song index đã có (dòng 133) |
| `ProjectDocument` | `documents.py:150` | thêm `tenant_id: str` |
| `UserSkillDocument` | `documents.py:196` | thêm `tenant_id: str` (lọc theo tenant khi liệt kê) |
| `SkillDocument` (owner_type=PERSONAL) | `documents.py:177` (`owner_user_id`) | thêm `tenant_id: str` |
| `FileFavoriteDocument` | `documents.py:217` | thêm `tenant_id: str` |
| `CliLoginSession` (mới, mục 4) | `user_id` (field mới) | bắt buộc ngay từ đầu — model mới, không phải migrate |
| Instruction gốc (mới, mục 2) | theo `Project`/`Session` | kế thừa từ `Session`/`Project` cha |

Không đổi `user_id` hiện có ở bất cứ đâu — `tenant_id` là field **cộng
thêm**, để API/luồng hiện tại không vỡ. Enforce lọc theo `tenant_id` ở tầng
query (mọi repository thêm `tenant_id` vào filter) là việc của giai đoạn sau,
khi thực sự có tenant thứ 2.

### 9.2 Mỗi khách tự đăng nhập tài khoản CLI riêng

`CliLoginSession` (mục 4.1) khoá mã hoá tách theo `tenant_id` — không dùng
một key mã hoá chung cho mọi tenant (tránh một key lộ là lộ hết). **v0.1**:
dù chỉ có 1 tenant (Boss), implement `tenant_id` là tham số bắt buộc của hàm
mã hoá/giải mã ngay từ đầu, để không phải đổi chữ ký hàm khi có tenant thứ 2.
Luật cứng mục 7.2–7.4 (`00-tong-quan.md`) áp dụng y nguyên: harness không
bao giờ tự ý dùng phiên đăng nhập của tenant A cho nhiệm vụ của tenant B.

### 9.3 Đăng nhập Google OAuth

Thêm `auth_provider = "google"` (cạnh `password`/`none`/`local` hiện có,
`backend/app/core/config.py:95`) ở tầng xác thực **người dùng vào harness**
— khác hoàn toàn với phiên đăng nhập CLI ở mục 4 (đó là người dùng đăng nhập
vào *Antigravity/Claude Code*, việc này là đăng nhập vào *chính ai-manus*).
Không đổi `User` model, chỉ thêm một code path xác thực mới song song
provider hiện có, gắn `User` vào đúng `Tenant` lúc tạo account (ví dụ theo
domain email, hoặc theo invite — quyết định lúc code).

### 9.4 Đo dùng theo tenant

Model mới `TenantUsageEvent`: `tenant_id`, `session_id`, `kind`
(`task_started` | `task_completed` | `sandbox_minutes` | `cli_token_usage`),
`value` (số), `recorded_at`.

- Số nhiệm vụ: ghi 1 `task_completed` mỗi khi `Session` chuyển sang
  `SessionStatus.COMPLETED`.
- Phút sandbox: lấy từ thời điểm `ensure_sandbox` xác nhận container `RUNNING`
  (`docker_sandbox.py:ensure_sandbox`) tới thời điểm container bị huỷ (hiện
  `containers.run(..., remove=True)` tự xoá — harness cần tự ghi lại timestamp
  huỷ *trước khi* gọi lệnh huỷ, vì container tự dọn không còn log lại được).
- Token CLI: đọc trường `usage` ở dòng kết thúc lượt — **đã đo**: agy v1.3.2
  trả `result.usage.{input_tokens,output_tokens,…}`, Claude Code v2.1.295 trả
  `usage` trên dòng `result`. Cả hai đều có, không cần đường dự phòng.

**v0.1**: chỉ ghi `TenantUsageEvent`, không tính tiền. Một hạn mức mềm (ví
dụ số nhiệm vụ/ngày) chỉ log cảnh báo khi vượt, không chặn chạy nhiệm vụ.
**Sau**: tính tiền thật, hạn mức cứng (chặn tạo session mới khi vượt),
dashboard cho tenant tự xem usage của họ.

### 9.5 Cách ly sandbox giữa tenant

`settings.sandbox_network` (`backend/app/core/config.py:58`) hiện là một
tên network Docker cố định cho toàn hệ thống
(`docker_sandbox.py: container_config["network"] = settings.sandbox_network`
khi có cấu hình). **v0.1**: đổi thành hàm `network_name_for_tenant(tenant_id)`
— tạo (nếu chưa có) một Docker network riêng mỗi tenant lúc tenant được tạo,
dùng tên đó khi `containers.run`. Xác nhận lại: `docker_sandbox.py` hiện
**không mount volume nào** cho container sandbox (không có tham số
`volumes`/`binds` trong `container_config` hiện tại) — giữ đúng như vậy
(không tenant nào có volume chia sẻ với tenant khác); HOME tạm cho CLI (mục
4.3) ghi *vào trong* container qua tool API (`file_write`/`shell_exec`), không
qua bind-mount từ host — nên không phát sinh volume chia sẻ mới khi thêm
tính năng CLI login.

### 9.6 Chuẩn bị tách sandbox manager (sau v0.1)

Xem mục 11.6 của `00-tong-quan.md`. Ghi chú kỹ thuật thêm ở đây: khi tách,
`network_name_for_tenant` (9.5) và việc tạo/huỷ container theo tenant chuyển
hết vào service "sandbox manager" đó — backend chỉ còn gọi `Sandbox` Protocol
(`backend/app/domain/external/sandbox.py`) qua client REST/gRPC, không đổi gì
ở tầng `domain/services/tools/{shell,file,browser}.py` hay `CliEngineFlow`.
Đây là lý do phải giữ nguyên tắc "gọi qua Protocol, không gọi thẳng `docker`
SDK" ngay từ v0.1 (mục 11.6) — tách sau không phải viết lại business logic.

## Câu hỏi mở

1. HOME tạm cho CLI (mục 4.3) nên dựng bằng cách ghi từng file qua tool API
   hiện có (chậm nếu nhiều file nhỏ) hay nén thành 1 file rồi giải nén bằng
   1 lệnh shell — cần đo thử với kích thước thật của thư mục cấu hình agy/
   Claude Code trước khi chốt.
2. `CliEngineConfig`/Instruction gốc (mục 2) nên là field mở rộng trên
   `Project` hay một model Mongo hoàn toàn mới gắn `session_id`/`project_id`?
   Ảnh hưởng tới có cần migrate `Project.instruction` hiện có hay không.
3. ~~Đường dẫn HOME-con thật của agy và Claude Code~~ **đã đo, xem mục 4.2
   bước 4.** Còn lại một chi tiết nhỏ: Claude Code đọc `CLAUDE_CONFIG_DIR` —
   nếu set biến này thì vị trí `~/.claude/` đổi theo, nên luồng 4.2/4.3 phải
   **không** set `CLAUDE_CONFIG_DIR` (để đường dẫn cố định trong HOME tạm).
4. Plan UI hiện tại của ai-manus có nên cố ánh xạ từ sự tự hành của CLI
   (suy ra `PlanEvent` từ cách CLI tự chia việc) hay CliEngineFlow chấp nhận
   Plan UI trống/ẩn cho engine này ở v0.1?
5. `Tenant.plan`/hạn mức mềm cụ thể là số gì (nhiệm vụ/ngày? phút sandbox/
   tháng?) — cần Boss chọn số thật trước khi code mục 9.4, v0.1 có thể để
   một hằng số cấu hình duy nhất áp cho mọi tenant (chưa cần gói nhiều mức).
