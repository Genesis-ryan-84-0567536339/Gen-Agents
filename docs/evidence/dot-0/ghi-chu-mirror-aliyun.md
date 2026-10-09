# Ghi chú: mirror Aliyun không ổn định từ mạng của Boss

Khi chạy `./dev.sh up -d --build` lần đầu (bản gốc, chưa sửa gì), build image
`sandbox` kẹt > 17 phút ở đúng bước `apt-get install -y sudo bc curl wget ...`
(sandbox/Dockerfile dòng 15-28), dù đây chỉ là các gói nhẹ. Kiểm tra độc lập
bằng container `ubuntu:22.04` rời, lặp lại đúng bước sed trỏ mirror Aliyun
(sandbox/Dockerfile dòng 10-12) của sandbox/Dockerfile và backend/Dockerfile
(dòng 16 `UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/`) cho thấy mirror
`mirrors.aliyun.com` phản hồi không ổn định: có lần `apt-get update` xong trong
~6s, có lần treo quá 120s không trả byte nào. Mirror mặc định Ubuntu
(archive.ubuntu.com/security.ubuntu.com) phản hồi ổn định và nhanh trong mọi
lần thử.

Đây là vấn đề hạ tầng mạng (mirror Trung Quốc không tối ưu/đáng tin từ mạng
VN ra ngoài), không phải lỗi của Gen-Agents hay thay đổi trong PR này. Không
sửa sandbox/Dockerfile hay backend/Dockerfile trong PR #28 (ngoài phạm vi,
mục 5 yêu cầu của Issue #28). Để lấy bằng chứng chạy thật trong lúc chờ sửa
dứt điểm (đề xuất: thêm ARG cho phép chọn mirror, hoặc fallback khi mirror
chính lỗi), tôi build cục bộ TẠM THỜI bằng cách bỏ các dòng trỏ mirror Aliyun
(không commit, chỉ chạy tại máy, revert file trước khi commit PR) để xác nhận
kiến trúc sandbox + noVNC hoạt động đúng khi mirror ổn định.

Đề xuất tách Issue riêng: thêm `ARG`/biến môi trường cho phép chọn mirror
(mặc định dùng mirror toàn cầu, cho phép đổi sang Aliyun khi build ở TQ).
