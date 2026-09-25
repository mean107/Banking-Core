# Kết quả thực nghiệm

Lưu kết quả smoke test, load test, dashboard và failover tại đây. Ghi kèm ngày chạy, image tag và cấu hình môi trường để so sánh giữa các lần thử.

Xem `../docs/VALIDATION.md` để biết trạng thái kiểm tra local và CI.

Không commit password/session/token, database dumps hoặc logs chứa thông tin cá nhân.

## Ghi lại một lượt lab Ubuntu

Chạy từ root repository, sau khi đã mở API qua Compose hoặc Kubernetes port-forward:

```bash
mkdir -p evidence
{
  date -Is
  git rev-parse HEAD
  uname -srmo
  docker version --format '{{.Server.Version}}'
} > evidence/environment.log
python scripts/smoke.py --base-url http://127.0.0.1:8000 \
  > evidence/smoke.json
```

Kết quả k6 dùng các lệnh trong `docs/RUNBOOK.md`. Khi ghi nhận failover, lưu primary/master trước và sau, thời gian lỗi, thời gian phục hồi và kết quả kiểm tra tài khoản cũ. Phân biệt pod restart, planned failover và mất node thực sự.

File JSON/log trong thư mục này được Git ignore mặc định. Đọc và loại bỏ dữ liệu nhạy cảm trước khi chủ động chia sẻ một báo cáo.
