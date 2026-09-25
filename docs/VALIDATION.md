# Báo cáo kiểm chứng — 2026-09-22

## Đã thực hiện tại máy

| Kiểm tra | Kết quả |
|---|---|
| Đọc CV và kiểm tra trực quan trang 2 | Đã đối chiếu bốn bullet đúng mục Core Banking System |
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

## Chưa chạy được / chưa thực hiện

- Docker CLI có sẵn nhưng không kết nối được Linux Engine (`dockerDesktopLinuxEngine` pipe không tồn tại). Đã thử khởi động Docker Desktop; Engine vẫn chưa sẵn sàng.
- Kubeconfig hiện tại trỏ tới `https://192.168.89.133:6443`; kiểm tra read-only bị timeout.
- Vì vậy chưa build Docker image, chưa chạy full Compose smoke, PostgreSQL concurrency, metrics/logs/traces end-to-end, KEDA scale, failover hay load test trên cluster.
- Chưa push GitHub, publish GHCR, chạy GitHub Actions hoặc đăng ký ArgoCD trên cluster thật.
- Chưa có kết quả CCU/RPS/P95/RTO/RPO được đo. Không có dữ liệu giả làm bằng chứng đã vận hành.

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
