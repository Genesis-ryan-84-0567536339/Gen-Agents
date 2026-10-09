# CLAUDE.md — Gen-Agents

Dự án **Gen-Agents**: harness tự host cho Boss, giao nhiệm vụ cho một agent
CLI (agy / Claude Code CLI) chạy thật trong container Ubuntu + Chrome thật,
xem live qua noVNC, não cắm/rút được không đổi cách dùng sản phẩm.

Fork từ `Simpleyyt/ai-manus` (MIT), remote `upstream` giữ nguyên để kéo vá.
Dự án riêng, **không đụng Gen-Harness** (hệ thống khác của Boss) — hai hệ
thống độc lập, dù dùng chung quy ước Issue → PR → review.

Đặc tả đầy đủ nằm ở `docs/spec/`:
- `00-tong-quan.md` — mục tiêu, DoD, kiến trúc 3 lớp, luật cứng, thuật ngữ,
  hướng SaaS.
- `01-dong-co-cli.md` — bộ chuyển động cơ CLI (lệnh, NDJSON đã đo của agy và
  Claude Code, bảng dịch sang `AgentEvent`, vòng đời nhiệm vụ).
- `02-mcp-trong-sandbox.md` — MCP server trong container nhiệm vụ.
- `03-cau-hinh-thuoc-harness.md` — Skill/Instruction/MCP/phiên đăng nhập CLI/
  lịch sử thuộc harness, đa khách thuê.

Đọc đúng file liên quan trước khi sửa phần đó — đừng suy diễn lại từ code khi
spec đã có câu trả lời, và cập nhật spec khi quyết định đổi.

## Vai trò

- **Boss (Ryan)** — Owner, quyết định cuối, không rành code.
- **Claude Code** — điều phối: đọc Issue, viết spec/review, quyết định kiến
  trúc, tự làm bản sửa nhỏ nhưng khó (≲ 30 dòng, cần hiểu sâu).
- **Sub agent Sonnet** (mặc định) — thi công: đọc/sửa code theo spec đã có,
  chạy test, thao tác PR theo mẫu.
- **Sub agent Opus** — review trước merge, gỡ xung đột, viết spec, gỡ lỗi khó.
- **Sub agent Haiku** — việc rất đơn giản (đọc/liệt kê, đổi tên, định dạng).
- **agy qua gen-workplace** — khi cần chạy việc nhiều code thật trên máy
  Boss, ngoài worktree Claude Code đang giữ.

## Quy trình

Issue → nhánh → PR → tự kiểm + bằng chứng chạy thật → merge (`Refs #n`).

- Issue là bước mặc định, không phải việc cần xin phép — tạo Issue trước khi
  code một thay đổi có ý nghĩa.
- Nhánh đặt tên theo chủ đề (ví dụ `spec/gen-agents-v0`, `feat/mcp-sandbox`).
- PR phải có **bằng chứng chạy thật** theo đúng đường người dùng đi (ví dụ
  CLI → MCP sandbox → tool thật), không chỉ test mock — đặc biệt với mọi đổi
  ở `domain/services/flows/`, `domain/services/tools/`, `sandbox/`.
- Tự kiểm (test pass + bằng chứng ghi trong PR + không xung đột) là đủ để tự
  merge, không chờ duyệt tay riêng — trừ khi việc đó đụng luật cứng dưới đây,
  khi đó hỏi Boss trước.

## Luật cứng (xem chi tiết + lý do ở `docs/spec/00-tong-quan.md` mục 7)

1. Không lách chống bot/CAPTCHA.
2. Không proxy token OAuth của Antigravity — mỗi vai/mỗi tenant tự đăng nhập
   tài khoản CLI của chính họ.
3. Không gộp quota nhiều tài khoản vào một luồng.
4. Mỗi vai một tài khoản.
5. Harness là nguồn gốc duy nhất cho skill/instruction/cấu hình MCP/phiên
   đăng nhập CLI/lịch sử — container sandbox không bao giờ là nơi lưu lâu dài.

## Kéo vá từ upstream

```bash
git fetch upstream
git log upstream/main --oneline -20      # xem có gì mới
git merge --no-ff upstream/main          # hoặc cherry-pick chọn lọc commit cụ thể
```

Merge chọn lọc khi upstream đổi nhiều — ưu tiên cherry-pick phần vá lỗi/bảo
mật, cân nhắc kỹ phần đổi kiến trúc vì Gen-Agents đã rẽ nhánh ở tầng flow
(`domain/services/flows/`) và tool MCP trong sandbox.

## Ngôn ngữ

Tài liệu, Issue, PR, commit message: **tiếng Việt có dấu**. Code/định danh kỹ
thuật giữ tiếng Anh như chuẩn ngôn ngữ lập trình.

---

## Ghi chú kỹ thuật kế thừa từ upstream (ai-manus)

> Phần dưới giữ lại từ `CLAUDE.md` gốc của upstream — vẫn đúng với cấu trúc
> mã nguồn hiện tại, dùng khi cần lệnh dev/test hoặc hiểu kiến trúc
> PlanActFlow (engine "API thô" dự phòng, xem `00-tong-quan.md` mục 5).

AI Manus là hệ Agent AI đa dụng. Một message của người dùng chạy qua
**Plan-Act agent loop** ở backend (Planner + Executor theo từng step), chạy
tool (shell, browser, file, search, MCP) trong **sandbox Docker riêng mỗi
phiên**, phát mọi event về browser qua **WebSocket**. Monorepo 4 service:
`frontend` (Vue 3 + TS, :5173), `backend` (Python 3.12 FastAPI, :8000),
`sandbox` (Python 3.10 FastAPI + Xvfb/Chrome/VNC qua supervisord, :8080 API/
:5900 VNC/:9222 CDP), `mockserver` (:8090). Backing: MongoDB 7.0 + Redis 7.0.

```bash
cp .env.example .env && ./dev.sh up -d      # dev stack đầy đủ
cd backend && uv run pytest -m "not e2e"     # test backend offline (không cần stack)
cd backend && uv run pytest -m e2e -rs       # test e2e (cần dev stack chạy)
cd sandbox && uv run pytest                   # test sandbox
cd frontend && npm run test && npm run type-check && npm run lint && npm run build
```

Backend theo DDD: `interfaces/` → `application/` → `domain/` ← `infrastructure/`.
Agent loop chính: `domain/services/flows/plan_act.py` (`PlanActFlow`), agent ở
`domain/services/agents/` (`PlannerAgent`, `ExecutionAgent`, cả hai kế thừa
`BaseAgent`), event ở `domain/models/event.py`, tool ở
`domain/services/tools/{shell,browser,file,search,message,mcp,plan,skill}.py`.
Không có linter/formatter cho backend/sandbox; frontend có ESLint, không có
Prettier. CI (`.github/workflows/tests.yml`, chạy trên PR vào `main`/`develop`)
có: test offline backend + `evals.run`, test/type-check/lint/build frontend,
quét secret (gitleaks), kiểm doc embed không lệch, và E2E dựng cả dev stack
(`docker-compose-development.yml`) rồi chạy `pytest -m e2e` (backend) +
`uv run pytest -q` (**`sandbox/`, bước "Sandbox API tests" — CI CÓ chạy test
`sandbox/`, chạy trực tiếp trên runner chứ không qua `docker exec`, nên bất
kỳ port nào test `sandbox/` cần gọi tới đều phải được `docker-compose-development.yml`
map ra host**); `nightly.yml` chạy lại bộ đó mỗi đêm và tự mở Issue khi hỏng.

Chi tiết đầy đủ hơn (bảng biến môi trường, ma trận test theo loại đổi, ghi
chú Cursor Cloud): `AGENTS.md`. API đầy đủ: `.cursor/skills/starter.md`.
