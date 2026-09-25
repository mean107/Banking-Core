# Kiểm chứng

## GitHub Actions — cập nhật 2026-09-25

[CI run 36092512859](https://github.com/mean107/Banking-Core/actions/runs/36092512859) của commit `68f0b08` đã hoàn tất thành công. Workflow gồm unit/API tests, PostgreSQL concurrency, Helm validation, build Compose, smoke test và publish image. Commit `c8d0a0b` cập nhật image SHA trong cấu hình GitOps.

Chưa xác nhận triển khai ArgoCD trên cluster, observability end-to-end, KEDA autoscaling hoặc diễn tập failover. Chưa có số liệu CCU/RPS/P95/RTO/RPO được đo trên cluster.

## Kiểm tra local — 2026-09-22

| Kiểm tra | Kết quả |
|---|---|
| Python unit/API tests | **20 passed** |
| PostgreSQL concurrency test | **1 skipped**: chưa có PostgreSQL test database |
| Python compile | Thành công |
| Frontend `npm ci` và production build | Thành công |
| Docker Compose config | Hợp lệ; không cần Docker Engine để parse |
| Helm lint: banking/platform/observability | 3/3 chart qua kiểm tra |
| Helm template | 61 resource render và parse được |
| kubeconform strict | 59 resource chuẩn hợp lệ; 0 invalid, 0 error; 2 custom resource kiểm tra riêng |
| CloudNativePG Cluster schema | Hợp lệ theo CRD của chart 0.23.2 |
| KEDA ScaledObject schema | Hợp lệ theo CRD của chart 2.17.2 |
| Bootstrap CLI | `--help` chạy được; không thực hiện bootstrap |

Test nghiệp vụ kiểm tra: bảo toàn số dư, atomicity khi từ chối giao dịch, idempotency key, payload conflict, số tiền sai; test API kiểm tra route/method, JSON, trace propagation, dependency failure và timeout có kết quả chưa xác định.

Cảnh báo build/test: dependency frontend cũ có deprecation/Browserslist warning; Python TestClient có warning về AnyIO alias. Không phải test failure. Chưa thực hiện dependency security audit toàn bộ.

## Giới hạn môi trường local tại thời điểm kiểm tra

- Docker CLI có sẵn nhưng không kết nối được Linux Engine (`dockerDesktopLinuxEngine` pipe không tồn tại). Đã thử khởi động Docker Desktop; Engine vẫn chưa sẵn sàng.
- Kết nối Kubernetes API bị timeout.
- Vì vậy chưa build Docker image, chưa chạy full Compose smoke, PostgreSQL concurrency, metrics/logs/traces end-to-end, KEDA scale, failover hay load test trên cluster.
- Các kiểm tra CI bổ sung sau đó được ghi ở đầu tài liệu; kết quả CI không thay thế kiểm tra vận hành trên cluster.

## Tái lập trên Ubuntu 24.04

Thực hiện [UBUNTU-LAB.md](UBUNTU-LAB.md) để có Docker/Python và [DEPLOYMENT.md](DEPLOYMENT.md) mục 2 để có Helm. Lệnh chạy từ root repository:

```bash
cd ~/labs/Banking-Core
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python scripts/validate.py
python scripts/validate-crds.py
```

`validate.py` chạy pytest, compile Python, Helm lint/template và Compose config; không triển khai cluster. `validate-crds.py` tải chart CNPG/KEDA để kiểm tra custom resource theo schema tương ứng. Cần Internet và Helm trong PATH.

### PostgreSQL concurrency thật

Chạy PostgreSQL riêng ở cổng 55432, không dùng database app. Nếu cổng/tên container đã được sử dụng, chọn tên/cổng khác đồng bộ với URL bên dưới:

```bash
docker run -d --rm --name banking-test-postgres \
  -e POSTGRES_USER=test -e POSTGRES_PASSWORD=test -e POSTGRES_DB=test \
  -p 127.0.0.1:55432:5432 postgres:17.4-alpine
for attempt in $(seq 1 30); do
  if docker exec banking-test-postgres pg_isready -U test -d test; then break; fi
  sleep 1
done
docker exec banking-test-postgres pg_isready -U test -d test
export TEST_DATABASE_URL='postgresql+psycopg://test:test@127.0.0.1:55432/test'
python -m pytest -q
unset TEST_DATABASE_URL
docker stop banking-test-postgres
```

Kỳ vọng không còn skip test PostgreSQL: test tạo schema riêng, gửi concurrent duplicate và chuyển tiền hai chiều, xác nhận số dư/tổng giao dịch rồi dọn schema. Container test không có volume; dừng sẽ xóa dữ liệu test. Mật khẩu `test` chỉ dùng cho container tạm bind loopback này.

### Build frontend

Không cần Node.js trên host; Dockerfile build frontend trong Node container:

```bash
docker build -t banking-core-frontend:check frontend
```

### Smoke end-to-end

```bash
docker compose up -d --build --wait --wait-timeout 300
python scripts/smoke.py --base-url http://127.0.0.1:8000
```

Với Kubernetes, mở port-forward Kong trước rồi chạy cùng smoke command. Xem [RUNBOOK.md](RUNBOOK.md) cho observability, buffering, tải và failover.

## Kiểm tra tài liệu Ubuntu

Các lệnh hướng dẫn được đối chiếu với service/namespace/script trong repository và kiểm tra cú pháp Bash. Việc kiểm tra cú pháp không thực hiện cài đặt Docker, tạo cluster hoặc chứng minh các bài lab đã chạy thành công trên một Ubuntu host mới. Lưu kết quả thực tế theo [evidence/README.md](../evidence/README.md).
