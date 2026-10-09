# 00 — Tổng quan Gen-Agents v0.1

> Trạng thái: nháp đặc tả, chưa triển khai. Quyết định nền: QD-17. Dự án: DA-9.
> Issue gốc: Gen-Agents #26. Nghiên cứu nền: Brain #135.

## 1. Mục tiêu

Xây "Manus của riêng Boss": một harness tự host trên máy Fedora của Boss, giao
nhiệm vụ cho một agent CLI chạy thật trong container Ubuntu + Chrome thật, xem
được live qua noVNC, giành quyền điều khiển được, và **đổi được não** (agy ↔
Claude Code CLI, sau này có thể thêm CLI khác) **không đổi cách Boss dùng
sản phẩm**. Dự án riêng của Gen-Agents, không chạm Gen-Harness (xem mục 7).

## 2. Người dùng

- **v0.1**: Boss (founder, không rành code) là người dùng duy nhất, tự host
  trên máy của mình.
- **Giai đoạn kế**: một đội nhỏ (vài người Boss tin tưởng) dùng chung một máy
  Fedora.
- **Hướng SaaS** (xem mục 11): nhiều khách thuê (tenant) độc lập, mỗi người tự
  đăng nhập tài khoản CLI riêng — không còn giả định "một người dùng".

Gen-Agents fork từ `Simpleyyt/ai-manus` (MIT). ai-manus đã có khái niệm
multi-user (`User`, `user_id` trên mọi model — xem mục 11) nên nền tảng
multi-tenant tận dụng lại được phần lớn, không viết lại từ đầu.

## 3. Definition of Done — v0.1 (kiểm được, không mơ hồ)

- [ ] Boss giao 1 nhiệm vụ qua UI ai-manus hiện có ("tìm kiếm web về X, xuất
      báo cáo .docx") → nhiệm vụ chạy trong container sandbox riêng của phiên.
- [ ] Boss mở noVNC của phiên, thấy Chrome thật đang chạy, bấm "giành quyền"
      và tự gõ/click được trong lúc agent đang chạy.
- [ ] Nhiệm vụ hoàn tất → file `.docx` xuất ra tải được từ UI (giữ cơ chế file
      hiện có của ai-manus, không viết lại).
- [ ] Đổi cấu hình engine của phiên từ agy sang Claude Code CLI (hoặc ngược
      lại) → lặp lại đúng 3 bước trên cho ra kết quả tương đương, Boss không
      phải đổi cách bấm/gõ gì trên UI.
- [ ] Toàn bộ sự kiện của nhiệm vụ (plan, tool call, message, done) hiện trên
      UI thời gian thực qua WebSocket hiện có — không UI riêng cho "engine
      CLI".
- [ ] Sau khi nhiệm vụ xong và container bị huỷ, Boss mở lại phiên cũ vẫn thấy
      lại lịch sử đầy đủ (vì lịch sử gốc ở harness — xem `03-cau-hinh-thuoc-harness.md`).
- [ ] Tắt máy, bật lại, không cấu hình gì thêm → phiên đăng nhập CLI đã lưu
      (agy / Claude Code) vẫn dùng được cho nhiệm vụ mới, không phải đăng nhập
      lại từ đầu mỗi lần.

Không có "điểm số" mơ hồ — mỗi dòng trên là một kịch bản tay chạy được và quan
sát được kết quả.

## 4. Kiến trúc 3 lớp

```
┌───────────────────────────────────────────────────────────────────────┐
│ LỚP 1 — HARNESS (backend ai-manus: FastAPI + Mongo + Redis)            │
│                                                                         │
│  - Sở hữu: User, Session, Skill, Instruction, cấu hình MCP,            │
│    phiên đăng nhập CLI (mã hoá), lịch sử (NDJSON thô + AgentEvent)     │
│  - Chọn "engine" theo cấu hình phiên/người dùng: PlanActFlow (cũ,      │
│    LangChain, "API thô") HOẶC CliEngineFlow (mới, xem mục 5)           │
│  - Tạo/huỷ container sandbox qua docker.sock, 1 container / phiên      │
│  - Phát AgentEvent ra WebSocket cho frontend (không đổi giao diện)     │
└───────────────────────────┬─────────────────────────────────────────┘
                              │ exec_command() qua REST :8080 (docker_sandbox.py)
                              ▼
┌───────────────────────────────────────────────────────────────────────┐
│ LỚP 2 — SANDBOX NHIỆM VỤ (container Ubuntu riêng mỗi phiên)            │
│                                                                         │
│  - Xvfb :1, Chrome remote-debug :8222 (socat → :9222), x11vnc :5900,   │
│    noVNC :5901                                                          │
│  - Tool API FastAPI :8080 (shell/file) — sandbox/app/api/v1/*.py       │
│  - MCP server mới (xem 02-mcp-trong-sandbox.md) bọc tool API +         │
│    CDP Chrome, chạy như 1 program nữa trong supervisord                │
│  - HOME tạm của CLI được ghi VÀO TRONG container (không bind-mount)    │
│    từ phiên đăng nhập đã lưu — xem 03 mục 4.3 và 9.5                    │
└───────────────────────────┬─────────────────────────────────────────┘
                              │ CLI chạy trong sandbox, gọi MCP tool cục bộ
                              ▼
┌───────────────────────────────────────────────────────────────────────┐
│ LỚP 3 — ĐỘNG CƠ CLI (bộ não, cắm/rút được)                             │
│                                                                         │
│  - agy (Antigravity CLI) HOẶC Claude Code CLI, headless                │
│    `-p --output-format stream-json`, chạy dài trong 1 process sandbox  │
│  - Nhận skill/instruction/cấu hình MCP do harness render ra đúng       │
│    định dạng từng CLI (AGENTS.md / CLAUDE.md / mcp_config.json /       │
│    settings.json)                                                       │
│  - Tự lập kế hoạch, tự gọi tool qua MCP — hành vi tự hành KHÔNG bị      │
│    planner/executor của ai-manus can thiệp (khác PlanActFlow cũ)       │
└───────────────────────────────────────────────────────────────────────┘
```

Quyết định đã chốt (Claude điều phối, không bàn lại trong spec này): bộ
chuyển động cơ cắm ở **tầng Flow** (`backend/app/domain/services/flows/`),
KHÔNG ở `LLM.ask()` (`backend/app/domain/external/llm.py`). Nếu chỉ thay LLM,
vòng lặp planner/executor hiện có
(`backend/app/domain/services/agents/base.py:230` `_tool_loop`) vẫn là não,
CLI chỉ còn là "model" bị gọi từng lượt — mất hết năng lực tự hành (tự lập
plan nhiều bước, tự sửa lỗi, tự quyết dùng tool nào) mà chính CLI đã có sẵn.

## 5. Flow mới: CliEngineFlow

Thêm `backend/app/domain/services/flows/cli_engine.py` (tên tạm), implement
`BaseFlow` (`backend/app/domain/services/flows/base.py`) y như
`PlanActFlow` (`backend/app/domain/services/flows/plan_act.py:58`). Khác biệt:

- Không có PlannerAgent/ExecutionAgent. Không có state machine
  PLANNING/EXECUTING. Một CLI process duy nhất chạy từ đầu đến hết nhiệm vụ.
- Khởi chạy CLI bằng `sandbox.exec_command()` (interface Protocol
  `backend/app/domain/external/sandbox.py:12`), tiến trình chạy dài — không
  phải lệnh chạy-rồi-thoát như `shell_exec` thường dùng.
- Đọc NDJSON CLI stream ra, ánh xạ từng dòng sang `AgentEvent` đã có
  (`backend/app/domain/models/event.py`: `PlanEvent`, `ToolEvent`, `StepEvent`,
  `MessageEvent`, `WaitEvent`, `DoneEvent`, `TerminalUpdateEvent`,
  `FileUpdateEvent`). Vì `ws_routes.py` chỉ biết `AgentEvent`, frontend +
  WebSocket không phải sửa gì.
- Tool call của CLI không đi qua `ShellToolkit`/`FileToolkit`/`BrowserToolkit`
  Python nữa — CLI tự gọi MCP server chạy trong sandbox (xem
  `02-mcp-trong-sandbox.md`). Flow chỉ còn việc đọc log & forward sự kiện,
  không còn là người thực thi tool.
- Chọn `PlanActFlow` hay `CliEngineFlow` theo cấu hình phiên/người dùng (field
  mới trên `Session`/`User`, chi tiết ở `03-cau-hinh-thuoc-harness.md`).
  `PlanActFlow` + LangChain giữ nguyên làm engine "API thô" dự phòng — không
  xoá, không phải di cư bắt buộc.

## 6. Nguyên tắc sở hữu dữ liệu

**Harness là nguồn gốc duy nhất (single source of truth).** Mọi thứ cấu hình
hay trạng thái liên quan đến một CLI engine — skill, instruction, cấu hình
MCP, phiên đăng nhập, bộ nhớ nhiệm vụ, lịch sử — *sinh ra* trong sandbox lúc
chạy, nhưng *thuộc về* harness trước và sau khi chạy:

- Trước khi chạy: harness render cấu hình gốc ra file đúng định dạng CLI cần,
  ghi vào sandbox.
- Trong khi chạy: sandbox là bản làm việc tạm (working copy) — CLI tự do đọc
  viết trong container của chính nó.
- Sau khi chạy: harness thu hồi lại những gì cần giữ (bộ nhớ nhiệm vụ, lịch sử
  NDJSON, phiên đăng nhập đã cập nhật) rồi huỷ container.

Container không bao giờ là nơi lưu trữ lâu dài. Một CLI session không được
giữ trạng thái nào mà harness không biết và không phục dựng lại được.

## 7. Luật cứng (áp cho mọi engine, mọi tầng)

1. **Không lách chống bot/CAPTCHA.** Chrome thật trong sandbox dùng để browse
   bình thường, không dùng kỹ thuật né phát hiện automation.
2. **Không proxy token OAuth của Antigravity.** Mỗi vai (Boss, từng thành
   viên đội, sau này từng tenant) tự đăng nhập tài khoản CLI của chính họ;
   harness không chặn giữa để mạo danh hay chia sẻ token.
3. **Không gộp quota nhiều tài khoản vào một luồng.** Một phiên nhiệm vụ dùng
   đúng một tài khoản CLI đã đăng nhập cho vai đó — không round-robin, không
   gộp pool quota của nhiều tài khoản cho một nhiệm vụ.
4. **Mỗi vai một tài khoản.** Không tái sử dụng cùng một tài khoản CLI cho
   nhiều vai/nhiều người/nhiều tenant khác nhau.
5. **Dự án riêng, không đụng Gen-Harness.** Gen-Agents không sửa, không phụ
   thuộc runtime vào Gen-Harness; là hai hệ thống độc lập dù có thể dùng
   chung một số quy ước (Issue → PR → review).
6. **Token đăng nhập của tenant là thứ dễ lộ nhất — coi là "khi nào", không
   phải "nếu".** Phiên đăng nhập CLI chỉ sống trong HOME tạm trên tmpfs của
   máy nhiệm vụ, file quyền 600; `settings.json` do harness sinh **cấm tool
   file/lệnh của CLI đọc** thư mục phiên (`~/.gemini/antigravity-cli/`,
   `~/.claude/`); bỏ `sudo NOPASSWD` khỏi image sandbox; Chrome chạy user
   khác với CLI; mọi phiên có `last_used_at`, nút **Thu hồi** ngay trên UI và
   cảnh báo khi dùng bất thường (nhiều IP/nhiều nhiệm vụ cùng lúc). Tenant có
   thể bật danh sách tên miền cho phép (egress allowlist) cho máy nhiệm vụ;
   mặc định mở (agent tổng quát cần web) kèm cảnh báo rủi ro bắt buộc đọc
   khi đăng nhập CLI (tinh thần QD-12: có công cụ, Owner tự quyết, app phải
   nói rõ rủi ro). Phần dư rủi ro (prompt injection từ trang web khiến CLI
   tự gửi token) được ghi nhận, không che giấu.

## 8. Phạm vi KHÔNG làm ở v0.1

- Không nhiều sandbox/CLI chạy song song trong một nhiệm vụ (1 nhiệm vụ = 1
  container = 1 CLI engine tại một thời điểm).
- Không tự động chọn CLI engine theo nội dung nhiệm vụ — người dùng/cấu hình
  chọn tay.
- Không UI cấu hình riêng cho CliEngineFlow trên frontend — dùng API/cấu hình
  backend trước, UI đẹp để sau.
- Không hỗ trợ CLI thứ ba ngoài agy và Claude Code (thiết kế adapter cho phép
  thêm sau, nhưng v0.1 chỉ build và kiểm 2 cái này).
- Không "giành quyền" đa người cùng lúc trên một VNC (vẫn single-writer như
  ai-manus hiện có).
- Không billing/tính tiền thật, không giới hạn cứng theo tenant (mục 11 chỉ
  đặt nền, chưa thực thi).
- Không hạ tầng nhiều máy chạy sandbox (mục 11.5 chỉ chuẩn bị kiến trúc).

## 9. Rủi ro đã biết, kế thừa từ ai-manus (không phải việc v0.1 phải sửa hết, nhưng phải biết)

- `docker.sock` được mount vào backend (`docker_sandbox.py`) — ai chiếm được
  backend coi như chiếm được host Docker. Hướng giảm rủi ro: xem mục 11.6.
- `sudo NOPASSWD` cho user `ubuntu` trong sandbox (`sandbox/Dockerfile`).
- Chrome chạy `--no-sandbox` trong `supervisord.conf` (chấp nhận được vì đã
  nằm trong container, nhưng là lớp phòng vệ kém hơn Chrome sandbox thật).
- Secret MCP (API key, token) hiện nằm trong file thường (`/etc/mcp.json`),
  không mã hoá — phiên đăng nhập CLI mới (mục 03) phải làm tốt hơn mức này.

## 10. Thuật ngữ tiếng Việt

| Thuật ngữ | Tiếng Việt dùng trong spec | Giải thích |
| --- | --- | --- |
| harness | lớp vỏ điều phối | backend ai-manus: quản người dùng, phiên, cấu hình, lịch sử |
| sandbox | máy nhiệm vụ | container Ubuntu riêng cho một phiên, có Chrome thật + tool API |
| engine | động cơ / não | thứ thực sự suy nghĩ và quyết định hành động: agy, Claude Code, hoặc PlanActFlow cũ |
| adapter | bộ chuyển | lớp dịch giữa một CLI cụ thể và giao diện chung (NDJSON ↔ AgentEvent, cấu hình gốc ↔ file riêng của CLI) |
| flow | luồng điều phối | state machine cấp cao chọn & chạy một engine cho một phiên (`BaseFlow`) |
| phiên nhiệm vụ | task session | một `Session` ai-manus — một container, một cuộc trò chuyện, một (hoặc nhiều) lần chạy engine |
| phiên đăng nhập CLI | CLI login session | thông tin đăng nhập đã lưu để CLI không phải đăng nhập lại mỗi nhiệm vụ |
| tenant | khách thuê | một đơn vị khách hàng độc lập về dữ liệu, cấu hình, sandbox (xem mục 11) |
| giành quyền | takeover | người dùng tự cầm chuột/gõ phím trong VNC khi agent đang chạy |

Quy ước dùng từ: "máy nhiệm vụ" và "sandbox" là **cùng một thứ** — dùng
"sandbox" khi đang nói tới mã nguồn/đường dẫn (`sandbox/`, `docker_sandbox.py`,
`/home/ubuntu`), dùng "máy nhiệm vụ" khi giải thích cho Boss. Không có khái
niệm thứ ba.

## 11. Hướng SaaS (bổ sung theo yêu cầu Boss, chưa triển khai ở v0.1 trừ khi ghi rõ)

Gen-Agents phải *đi được* đến mô hình SaaS nhiều khách thuê — không bắt buộc
có ở v0.1, nhưng kiến trúc v0.1 không được chặn đường đó. Chi tiết mô hình dữ
liệu, luồng đăng nhập theo tenant, đo dùng nằm ở
`03-cau-hinh-thuoc-harness.md` mục "Đa khách thuê"; mục này chỉ nêu khung và
đánh dấu v0.1 vs sau.

**11.1 Tenant là đơn vị tách dữ liệu, file, sandbox, cấu hình, skill.**
ai-manus đã có sẵn trục tách theo người dùng: `User.id`
(`backend/app/domain/models/user.py:14`), và mọi Beanie document chính đã có
`user_id` (`backend/app/infrastructure/models/documents.py`: `SessionDocument`
dòng 108, `ProjectDocument` dòng 150, `UserSkillDocument` dòng 196,
`FileFavoriteDocument` dòng 217) cộng `Project`
(`backend/app/domain/models/project.py`) làm đơn vị nhóm phiên theo
`user_id`. **v0.1**: thêm `tenant_id` song song `user_id` trên các model này
(một `tenant` có nhiều `user`, giữ `user_id` để không phá API hiện có) —
không bắt buộc *dùng* ngay, nhưng field phải có mặt từ đầu để không phải
migrate dữ liệu thật sau. **Sau**: enforce tách ở tầng truy vấn (mọi query
Mongo lọc theo `tenant_id`), tách network Docker theo tenant (xem 11.5).

**11.2 Mỗi khách tự đăng nhập tài khoản CLI của họ — luật cứng, không phải
tính năng tuỳ chọn.** Harness tuyệt đối không dùng tài khoản Antigravity/
Claude Code của Boss cho khách (vi phạm điều khoản dịch vụ + làm lẫn quota
nhiều người vào một tài khoản — xem luật cứng mục 7.2–7.4, áp y nguyên cho
tenant). Phiên đăng nhập CLI (mục 03) mã hoá theo `tenant_id`, không chỉ theo
`user_id` — một tenant có nhiều user dùng chung phiên đăng nhập CLI của
tenant đó (hoặc mỗi user tự đăng nhập riêng, tuỳ gói). **v0.1**: thiết kế
khoá mã hoá theo tenant ngay từ đầu dù v0.1 chỉ có 1 tenant (Boss).

**11.3 Đăng nhập Google OAuth cho người dùng.** `auth_provider` hiện tại chỉ
có `password`/`none`/`local` (`backend/app/core/config.py:95`), chưa có
OAuth. **v0.1**: thêm `auth_provider = "google"` làm một provider nữa cạnh
`password` (không thay, không bắt buộc bật) — cần cho SaaS vì khách không
nên tự đặt mật khẩu cho một hệ thống họ mới dùng lần đầu. **Sau**: multi-IdP
khác (Microsoft, GitHub) nếu cần.

**11.4 Đo dùng theo tenant.** Đếm số nhiệm vụ, số phút sandbox (từ lúc
container `running` tới lúc huỷ — đã có sẵn trong vòng đời
`docker_sandbox.py`), và token dùng (cả agy và Claude Code đều emit `usage`
theo lượt trong stream-json — đã đo thật, xem `01-dong-co-cli.md` mục 3–4). **v0.1**: chỉ đo dùng theo tenant (ghi `TenantUsageEvent`), không tính tiền, **không hạn mức** (QD-19). **Sau**: tính tiền thật, hạn mức, dashboard cho khách.

**11.5 Hạ tầng v0.1: một máy Fedora + Cloudflare tunnel.** Giống hạ tầng
Gen-hub hiện có của Boss (`hub.genos.top`, Docker, Cloudflare tunnel) — tái
dùng mô hình đó, không phát sinh hạ tầng mới. Trong một máy, **cách ly
sandbox giữa tenant ngay ở v0.1**: mỗi container sandbox nối vào một Docker
network riêng theo tenant (`settings.sandbox_network`,
`backend/app/core/config.py:58`, hiện là 1 network cố định toàn hệ thống —
đổi thành tạo/chọn network theo `tenant_id`), không tenant nào share volume
với tenant khác (hiện tại `docker_sandbox.py` không mount volume nào cả —
giữ nguyên "không volume chia sẻ", chỉ thêm network riêng).

**11.6 Chuẩn bị tách "trình quản lý sandbox" khỏi backend (sau v0.1).** Rủi
ro `docker.sock` trong backend (mục 9) nặng hơn trong mô hình nhiều khách: một
lỗi ở backend là lộ toàn bộ host cho mọi tenant. Hướng tới: tách một service
riêng "sandbox manager" sở hữu `docker.sock` + implement interface
`Sandbox` Protocol hiện có (`backend/app/domain/external/sandbox.py`) qua
REST/gRPC nội bộ, để sau này service đó chạy trên máy khác (hoặc nhiều máy)
mà backend không cần đổi gì ngoài endpoint. **v0.1 chỉ cần**: không viết thêm
code mới giả định docker.sock nằm cùng process backend (gọi `Sandbox` Protocol
qua DI như hiện có — `interfaces/dependencies.py` — không gọi `docker` SDK
trực tiếp từ nơi khác). Việc tách thật là một dự án riêng sau v0.1.

## Câu hỏi mở

1. CliEngineFlow có cần một bước "điểm dừng" (checkpoint) giữa nhiệm vụ để
   harness thu hồi bộ nhớ/lịch sử sớm hơn lúc container bị huỷ không, hay thu
   hồi một lần ở cuối là đủ cho v0.1?
2. Khi engine là CLI tự hành hoàn toàn, "giành quyền" VNC giữa nhiệm vụ có
   cần báo cho CLI biết (để nó dừng tool call đang chạy) hay chỉ là người
   dùng chen vào song song, mặc kệ CLI đang làm gì?
3. `tenant_id` nên là bắt buộc trên mọi model ngay ở v0.1 (migrate ngay, dù
   chỉ có 1 tenant), hay optional trước rồi bắt buộc khi thực sự có tenant
   thứ 2? Nghiêng về bắt buộc ngay để tránh migrate dữ liệu thật sau, nhưng
   cần Boss xác nhận vì ảnh hưởng toàn bộ schema Mongo hiện có.
4. `auth_provider = "google"` có thay thế được use case "team nhỏ dùng chung
   máy Boss" (mục 2, giai đoạn kế) hay giai đoạn đó vẫn dùng `password`/
   `none` nội bộ, chỉ SaaS mới cần Google OAuth?
