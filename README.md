# Gen-Agents

[English upstream README](README_upstream.md) · [中文](README_zh.md) · License: [MIT](LICENSE)

Gen-Agents là harness tự host cho Boss (Ryan), fork từ
[`Simpleyyt/ai-manus`](https://github.com/Simpleyyt/ai-manus) (MIT). Nó giao
nhiệm vụ cho một agent CLI (agy / Claude Code CLI) chạy thật trong container
Ubuntu kèm Chrome thật, xem và giành quyền điều khiển trực tiếp qua noVNC —
mục tiêu là "Manus của riêng Boss" với bộ não CLI cắm/rút được mà không đổi
cách dùng sản phẩm.

## Kiến trúc 3 lớp

```
LỚP 1 — HARNESS (backend ai-manus: FastAPI + Mongo + Redis)
  Sở hữu User, Session, Skill, Instruction, cấu hình MCP, phiên đăng nhập
  CLI, lịch sử. Chọn engine theo phiên (PlanActFlow cũ hoặc CliEngineFlow
  mới). Tạo/huỷ container sandbox qua docker.sock, 1 container / phiên.
        │ exec_command() qua REST :8080
        ▼
LỚP 2 — SANDBOX NHIỆM VỤ (container Ubuntu riêng mỗi phiên)
  Xvfb, Chrome remote-debug, x11vnc + noVNC, Tool API FastAPI :8080, MCP
  server bọc tool API + CDP Chrome. HOME tạm của CLI ghi vào container từ
  phiên đăng nhập đã lưu.
        │ CLI chạy trong sandbox, gọi MCP tool cục bộ
        ▼
LỚP 3 — ĐỘNG CƠ CLI (bộ não, cắm/rút được)
  agy (Antigravity CLI) hoặc Claude Code CLI, headless, stream-json. Tự lập
  kế hoạch, tự gọi tool qua MCP — không bị planner/executor cũ can thiệp.
```

Chi tiết đầy đủ (mục tiêu, Definition of Done, luật cứng, hướng SaaS) nằm ở
[`docs/spec/00-tong-quan.md`](docs/spec/00-tong-quan.md) và các file
`docs/spec/01–03`. Kế hoạch thi công 6 đợt: [`docs/DU-PHONG.md`](docs/DU-PHONG.md).

> Hai file trên thuộc nhánh spec (PR #27) — nếu chưa thấy trên `main`, nghĩa
> là PR đó chưa merge; xem trực tiếp trên nhánh `spec/gen-agents-v0`.

## Trạng thái

**Đợt 0 / 6** — Nền: chạy được bản gốc ai-manus trên máy Fedora của Boss qua
`./dev.sh` với mockserver (sandbox + noVNC hoạt động, giành quyền điều khiển
được), CI xanh trên repo mới, dọn dependabot kế thừa từ upstream, README
tiếng Việt. Xem Issue #28 và bằng chứng tại
[`docs/evidence/dot-0/`](docs/evidence/dot-0/).

Các đợt kế (1–5): MCP trong máy nhiệm vụ, bộ chuyển động cơ agy, cấu hình
thuộc harness + Claude Code, SaaS lớp 1, cứng hoá + phát hành v0.1.0 — xem
`docs/DU-PHONG.md`.

## Chạy dev

Giữ nguyên lệnh của upstream (ai-manus). Cần Docker + Docker Compose.

```bash
git clone https://github.com/Genesis-ryan-84-0567536339/Gen-Agents.git
cd Gen-Agents
cp .env.example .env
```

Sửa `.env`: tối thiểu cần `API_KEY`. Để chạy với mockserver (không cần key
thật) và bỏ xác thực khi thử nhanh trên máy cá nhân:

```ini
API_KEY=sk-xxxx
API_BASE=http://mockserver:8090/v1
AUTH_PROVIDER=none
```

Chạy ở chế độ debug (reload code tự động):

```bash
./dev.sh up -d
./dev.sh ps
```

Mở `http://localhost:5173` để dùng UI. Cổng khác: `8000` (API backend),
`8080` (sandbox tool API), `5902` (sandbox VNC), `27017` (MongoDB).

Dừng và dọn:

```bash
./dev.sh down        # giữ volume
./dev.sh down -v      # xoá luôn volume khi đổi dependency
```

Chi tiết cấu hình đầy đủ: [`.env.example`](.env.example) hoặc
[docs cấu hình upstream](https://docs.ai-manus.com/#/en/configuration).

## Liên quan

- Issue gốc: [#26](https://github.com/Genesis-ryan-84-0567536339/Gen-Agents/issues/26),
  [#28](https://github.com/Genesis-ryan-84-0567536339/Gen-Agents/issues/28) (đợt 0).
- Spec kiến trúc: `docs/spec/00-tong-quan.md` → `03-cau-hinh-thuoc-harness.md`.
- Dự phóng 6 đợt: `docs/DU-PHONG.md`.
- Hướng dẫn làm việc với repo: `CLAUDE.md`.
- README gốc tiếng Anh (upstream ai-manus, giữ nguyên để tham khảo tính
  năng/demo): [`README_upstream.md`](README_upstream.md).

Gen-Agents fork từ `Simpleyyt/ai-manus`, giấy phép MIT — xem [`LICENSE`](LICENSE).
