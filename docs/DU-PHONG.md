# Dự phóng thi công Gen-Agents (theo QD-14) — bản nộp Boss duyệt, 09/10/2026

Cơ sở: spec `docs/spec/00–03`, Issue #26, nghiên cứu Brain #135, số liệu token thật từ Gen-Harness (QD-14: thi công + review toàn Opus ≈ 2–3M/đợt; mục tiêu ≤ 1,5M/đợt với Sonnet thi công + Opus review 1 vòng).

## Nguyên tắc chung mọi đợt
- Mỗi đợt = 1 Issue con → 1 nhánh → 1 PR → bằng chứng chạy thật trong PR → Opus review 1 vòng → merge → tag `v0.1.x`.
- Thi công: **Sonnet** (sub agent, worktree riêng). Thiết kế/review/gỡ xung đột: **Opus**. Đọc log, kiểm CI, kiểm trạng thái: **Haiku**. Quyết định và bản sửa nhỏ-khó: **Claude điều phối**. Việc nhiều code cần chạy thật trên máy Boss có thể giao **agy** qua gen-workplace (QD-7) thay Sonnet.
- Bằng chứng bắt buộc: output thô theo đúng đường người dùng đi (UI → backend → container → CLI), không chỉ test mock.
- Không đụng Gen-Harness (QD-17). Không proxy token OAuth. Không gộp quota.

## Các đợt

| Đợt | Tên | Nội dung chính | Đội | Token ước | Thời gian máy |
|---|---|---|---|---|---|
| 0 | Nền | Chạy được bản gốc ai-manus trên Fedora bằng `./dev.sh` với mockserver (xác nhận sandbox + noVNC hoạt động trên máy Boss, **và bấm "giành quyền" gõ được trong lúc nhiệm vụ đang chạy** — DoD dòng 2); CI chạy xanh trên repo mới; CLAUDE.md + spec vào main; đổi tên hiển thị Gen-Agents, tiếng Việt cho README | Sonnet thi công · Haiku kiểm CI/log · Opus review nhẹ | 0,6M | 0,5 ngày |
| 1 | MCP trong máy nhiệm vụ | MCP server (streamable-http 127.0.0.1:8081) phơi đúng 25 tool theo `02 §3` — bọc shell/file qua REST :8080, viết lại 12 tool browser qua CDP, cộng `plan_update`, `message_ask_user`, `message_notify_user` báo về backend qua Redis stream; program mới trong supervisord; cài `agy` + `claude` + công cụ xuất `.docx` (python-docx/pandoc — image hiện chưa có gì, mà DoD dòng 3 cần) vào image sandbox; test: `agy -p` trong container gọi được `browser_navigate` qua MCP | Sonnet · Opus review | 1,2M | 1 ngày |
| 2 | Bộ chuyển động cơ agy | `domain/external/engine.py`, `flows/cli_engine.py`, adapter agy (NDJSON → EngineEvent → AgentEvent), chọn động cơ theo phiên, nối lại `--conversation`, WaitEvent qua `message_ask_user`, lưu NDJSON thô, ghi usage; **mở lại phiên cũ sau khi container bị huỷ vẫn thấy đủ lịch sử** (DoD dòng 6); nghiệm thu theo `01 §8` mục 1–3 | Opus thiết kế chi tiết (từ spec 01) · Sonnet thi công · Opus review | 1,5M | 1,5 ngày |
| 3 | Cấu hình thuộc harness + Claude Code | Model `Tenant` + field `tenant_id` trên các model ở `03 §9.1` (làm trước vì mục 4 khoá mã hoá theo tenant đã cần); Model Instruction/MCP/Skill/Phiên đăng nhập theo tenant; render HOME tạm (AGENTS.md/CLAUDE.md, mcp config, settings deny-list, skills); đăng nhập CLI lần đầu qua pseudo-terminal (link + mã) trong UI; adapter Claude Code (`--settings --strict-mcp-config`); thu hồi todo.md/output/bộ nhớ; **nhiệm vụ xuất `.docx` tải được từ UI** (DoD dòng 3) và **tắt–bật máy xong phiên đăng nhập CLI đã lưu vẫn chạy nhiệm vụ mới, không đăng nhập lại** (DoD dòng 7); nghiệm thu `01 §8` mục 4–5 | Sonnet · Opus review | 1,5M | 1,5 ngày |
| 4 | SaaS lớp 1 + trải nghiệm | Enforce lọc `tenant_id` ở tầng query + cách ly file/sandbox (field đã thêm ở đợt 3); Google OAuth; đo dùng theo tenant (nhiệm vụ, phút sandbox, token) + hạn mức mềm; UI tiếng Việt (locale vi); chọn model/mức suy nghĩ từ `agy models --output-format json`; giới hạn lượt/phút mỗi nhiệm vụ | Sonnet · Opus review | 1,5M | 1,5 ngày |
| 5 | Cứng hoá + phát hành v0.1.0 | Tách "trình quản lý sandbox" khỏi backend (bỏ docker.sock khỏi backend) hoặc tối thiểu khoá quyền; mạng riêng mỗi container, không chia sẻ volume giữa tenant; secret MCP vào kho mã hoá; sao lưu Mongo; cài 1 lệnh + Cloudflare tunnel; E2E cài sạch trên máy Boss; ghi chú phát hành tiếng Việt | Sonnet · Opus review đối kháng bảo mật · Haiku kiểm E2E | 1,5M | 2 ngày |
| **Tổng** | | 6 đợt | | **≈ 7,8M** | **≈ 8 ngày máy** |

Sau v0.1.0 (chưa dự phóng, cần QD mới): lịch chạy định kỳ, Wide Research (nhiều sub-agent), bộ nhớ dài hạn theo tenant, thanh toán, sandbox chạy trên máy khác, Codex CLI.

## Thứ tự và phụ thuộc
0 → 1 → 2 → 3 → 4 → 5 (tuyến tính, không có vòng). Đợt 1 và 2 có thể song song một phần (adapter viết trước bằng NDJSON đã đo), nhưng nghiệm thu đợt 2 cần đợt 1.

Phủ Definition of Done (`00 §3`, 7 dòng): dòng 1 → đợt 0+2 · dòng 2 (giành quyền) → đợt 0 · dòng 3 (`.docx` tải được) → đợt 1 (công cụ trong image) + đợt 3 (nghiệm thu đầu-cuối) · dòng 4 (đổi động cơ) → đợt 3 · dòng 5 (sự kiện realtime) → đợt 2 · dòng 6 (lịch sử sau khi huỷ container) → đợt 2 · dòng 7 (tắt–bật máy vẫn còn phiên đăng nhập) → đợt 3. Đợt 4–5 là SaaS và cứng hoá, không gánh dòng DoD nào của v0.1.

## Rủi ro ảnh hưởng ước tính
- Quota agy/Claude trong lúc thử nghiệm: đợt 2–3 cần ~30–60 lượt chạy thật; dùng Gemini Flash low cho thử nghiệm.
- Image sandbox nặng thêm (agy + claude + Node + công cụ `.docx`): kéo dài build; chấp nhận.
- 12 tool browser phải viết lại qua CDP trong MCP server (không tái dùng được `browser_use` của backend — `02 §4`) là khối code lớn nhất đợt 1; nếu phải giữ nguyên ngữ nghĩa `[index]<tag/>` thì ước 1,2M có thể thiếu ~0,3M.
- Chưa biết đường dẫn skills của Claude Code trong HOME tạm → có thể thêm 0,2M ở đợt 3.
- Nếu Boss muốn giao thi công cho agy (gen-workplace) thay Sonnet thì token Claude giảm ~40% mỗi đợt, thời gian máy tăng nhẹ.

## Cách Boss duyệt
Dán vào chat hoặc Kho: "Duyệt dự phóng Gen-Agents 6 đợt" (hoặc nêu đợt muốn bỏ/đổi thứ tự). Sau khi duyệt, Claude tạo 6 Issue con, ghi VIEC- tương ứng, và bắt đầu đợt 0.
