# Bằng chứng đợt 0 (Issue #28)

## Build

- `build-sandbox-log.txt`: log build image `sandbox` (plain progress) sau khi đổi
  mirror apt/uv/npm từ Aliyun về mặc định — build từ cache, `EXITCODE:0`.
- `ghi-chu-mirror-aliyun.md`: chẩn đoán vì sao build bản gốc (mirror Aliyun)
  kẹt >17 phút trên mạng VN, và lý do đổi mirror (commit riêng, có trong PR).

## Chạy thật + healthy

- `docker-compose-ps-healthy.txt`: output `docker compose ps` (6 container
  Up: backend, frontend-dev, mockserver, mongodb, redis, sandbox) +
  `supervisorctl status` trong sandbox (toàn bộ RUNNING: xvfb, chrome, socat,
  x11vnc, websockify, app) + curl 200 trên backend/mockserver/frontend.
  Ghi chú: cổng frontend map tạm 5174->5173 trên máy test này vì 5173 đang bị
  một project khác (Ai-Games/Gen-Stage) chiếm — không phải do Gen-Agents;
  không commit thay đổi này vào `docker-compose-development.yml`.

## noVNC + giành quyền (takeover)

- `sandbox-chrome-before-takeover-click.png`: chụp trực tiếp display X11 (`
  DISPLAY=:1 import -window root`) trong container sandbox, cho thấy Chrome
  thật đang mở example.com — đúng nội dung mà noVNC phục vụ qua WebSocket
  (`backend` proxy `/ws/vnc/{session_id}` → sandbox `:5901` websockify).
- Xác nhận qua UI thật: mở `http://localhost:5174/chat/<sessionId>?vnc=1`
  (route `TakeOverView.vue`), thấy `VNCViewer` hiển thị đúng Chrome + nút
  "Exit Takeover" (xác nhận đang ở chế độ giành quyền, `view-only: false`).
- Click vào link "Learn more" trong khung noVNC của UI → Chrome trong sandbox
  điều hướng sang `iana.org/help/example-domains`.
- `sandbox-chrome-after-takeover-click.png`: chụp lại X11 ngay sau click,
  xác nhận Chrome đã đổi trang — chứng minh điều khiển hai chiều qua noVNC
  hoạt động đúng (DoD dòng 2 của `docs/spec/00-tong-quan.md`).

## Lưu ý

Mock scenario `browser_tools.yaml`/`default.yaml` trả "Unknown tool:
message_notify_user" / "Unknown tool: create_plan" khi để agent tự chạy —
có vẻ là lệch phiên bản giữa scenario mock có sẵn và tool registry hiện tại
của backend trên nhánh `main`, không liên quan tới thay đổi của PR này. Vì
vậy bằng chứng noVNC/takeover ở trên lấy bằng cách mở trực tiếp route
`?vnc=1` của phiên đã tạo, thao tác tay qua UI thay vì chờ agent tự gọi
browser tool. Đáng theo dõi ở đợt sau nếu cần test e2e tự động qua mock.
