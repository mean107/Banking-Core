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

## Tái lập kiểm tra

```powershell
pip install -r requirements-dev.txt
python scripts/validate.py
python scripts/validate-crds.py
cd frontend
npm ci
npm run build
```

`validate-crds.py` cần Internet để tải chart operator. Helm CLI cần có trong PATH hoặc đặt biến `HELM` thành đường dẫn executable.

Khi Docker hoạt động:

```powershell
docker compose up -d --build --wait --wait-timeout 240
python scripts/smoke.py
```

Theo `RUNBOOK.md` để tạo bằng chứng observability, load test và HA. Theo `DEPLOYMENT.md` để chạy pipeline và GitOps. Chỉ cập nhật cột kết quả sau khi thực sự thực hiện.
