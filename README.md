# Banking Core

Banking Core là ứng dụng ngân hàng demo gồm đăng ký, đăng nhập, xem số dư, chuyển tiền và thông báo realtime. Các service xử lý request qua RabbitMQ, lưu giao dịch trong PostgreSQL và dùng Redis cho session, kết quả xử lý và Pub/Sub.

Hệ thống chạy local bằng Docker Compose hoặc triển khai lên Kubernetes bằng Helm và ArgoCD. Đây là môi trường thực hành, không dùng cho giao dịch tiền thật.

## Thành phần

| Thành phần | Vai trò |
|---|---|
| React + Nginx | Giao diện đăng nhập, tài khoản, chuyển tiền và thông báo |
| FastAPI + SQLAlchemy | API producer và các service auth, account, transfer, notification |
| Kong | Định tuyến HTTP và WebSocket |
| RabbitMQ | Queue riêng cho từng service, persistent message và publisher confirm |
| PostgreSQL | Lưu tài khoản, số dư, giao dịch và thông báo; CloudNativePG quản lý 3 instance trên Kubernetes |
| Redis | Session, kết quả xử lý và Pub/Sub; 3 pod với Sentinel quorum 2 trên Kubernetes |
| GitHub Actions + ArgoCD | Test, build image, publish GHCR, cập nhật image SHA và đồng bộ deployment |
| Prometheus, Grafana, Loki, Tempo | Metrics, dashboard, logs và traces; thu thập qua Alloy và OpenTelemetry |
| KEDA | Điều chỉnh số API replica theo RPS |
| pytest + k6 | Kiểm tra nghiệp vụ, concurrency và tải |

Chuyển tiền dùng database transaction, khóa tài khoản theo thứ tự ID và idempotency key để xử lý retry. Thông báo được lưu cùng giao dịch; WebSocket đẩy thông báo tới người nhận qua Redis Pub/Sub.

## Kiến trúc

```text
Browser → React/Nginx → Kong → API producer → RabbitMQ → auth/account/transfer/notification
                                  ↑                            │
                                  └──── response trong Redis ───┘
                                                               ├── PostgreSQL: users, balances, transfers
Browser ← WebSocket ← notification ← Redis Pub/Sub ← transfer ─┘

API metrics → Prometheus → Grafana / KEDA → API replicas
Container logs → Alloy → Loki → Grafana
HTTP + message spans → OpenTelemetry Collector → Tempo → Grafana
```

Các role backend dùng chung code/image nhưng chạy ở các container/Deployment riêng và consume queue riêng. PostgreSQL dùng schema chung. HTTP vẫn chờ consumer trả kết quả; timeout có thể là kết quả chưa xác định, không phải bằng chứng giao dịch thất bại.

## Bắt đầu trên Ubuntu

Hướng dẫn chi tiết theo thứ tự:

1. [Chuẩn bị Ubuntu và chạy Docker Compose](docs/UBUNTU-LAB.md).
2. [Dựng Kubernetes, Helm và GitOps](docs/DEPLOYMENT.md).
3. [Lab chuyển tiền, monitoring, autoscaling và failover](docs/RUNBOOK.md).
4. [Kiểm thử và trạng thái xác nhận](docs/VALIDATION.md).

Các lệnh bên dưới dùng Bash trên Ubuntu 24.04 amd64.

## Chạy nhanh bằng Compose

Yêu cầu Docker Engine Linux/Compose v2. Dùng khoảng 4 GB RAM cho ứng dụng; thêm observability cần nhiều hơn.

```bash
git clone https://github.com/mean107/Banking-Core.git
cd Banking-Core
cp -n .env.example .env
docker compose up -d --build --wait --wait-timeout 240
```

- Giao diện: <http://localhost:3000>
- API qua Kong: <http://localhost:8000>
- RabbitMQ management: <http://localhost:15672> (`banking`, mật khẩu trong `.env`)
- Tạo hai tài khoản để thử chuyển tiền; mỗi tài khoản demo được cấp 100.000.

Thêm monitoring:

```bash
docker compose --profile observability up -d
```

- Grafana: <http://localhost:3001>, user `admin`, `GRAFANA_PASSWORD` trong `.env`.
- Prometheus: <http://localhost:9090>.
- Grafana dashboard **Banking Core Operations**; Explore → Loki hoặc Tempo.
- Alloy local đọc Docker socket để thu logs. Chỉ dùng cấu hình này trong môi trường lab tin cậy.

## Kiểm thử

Python 3.12 và Helm 3.17.3:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python scripts/validate.py
python scripts/smoke.py --base-url http://localhost:8000
```

`validate.py` không deploy, không thay đổi cluster. Test concurrency PostgreSQL được skip nếu chưa đặt `TEST_DATABASE_URL`; SQLite unit test không chứng minh row locking trên PostgreSQL.

## Kubernetes / GitOps

Đọc [DEPLOYMENT.md](docs/DEPLOYMENT.md). Cần 3 node schedulable, StorageClass mặc định và image đã build/publish. Image tag được quản lý trong `deploy/environments/lab/images.yaml`.

```bash
export LAB_CONTEXT=k3d-banking-lab
python scripts/bootstrap.py --context "$LAB_CONTEXT" --gitops
```

Trước khi chạy bootstrap, thực hiện các bước tạo cluster, chuẩn bị namespace cho Helm, credentials và image trong hướng dẫn triển khai. Lệnh trên không thay thế những bước chuẩn bị đó.

## Cấu trúc

```text
backend/app/          API, consumer, banking transaction, telemetry
frontend/             React UI được điều chỉnh từ project gốc
infra/                Kong local
observability/        Cấu hình metrics/logs/traces và Grafana dashboard
deploy/charts/        banking, platform, observability
deploy/argocd/        AppProject và 3 Applications
deploy/environments/ Image tags do CI cập nhật
.github/workflows/   CI, integration smoke, image publication, GitOps update
tests/                Unit, PostgreSQL concurrency, k6
scripts/              Bootstrap, validate, smoke, cập nhật image
docs/                 Triển khai, runbook, kiểm chứng và quyết định kỹ thuật
```

## Tài liệu và giới hạn

- [Ubuntu lab](docs/UBUNTU-LAB.md): cài công cụ, Compose và truy cập qua SSH tunnel.
- [Triển khai](docs/DEPLOYMENT.md): chuẩn bị image, cluster và GitOps.
- [Runbook](docs/RUNBOOK.md): smoke test, load test, quan sát hệ thống và diễn tập failover.
- [Kiểm chứng](docs/VALIDATION.md): kết quả kiểm tra và các phần chưa kiểm chứng runtime.
- [Thiết kế và nguồn gốc](docs/PROVENANCE.md): các thay đổi so với upstream và giới hạn kỹ thuật.

Các service dùng chung PostgreSQL schema. RabbitMQ chạy một node có persistent volume; KEDA chỉ scale API producer. Cấu hình HA PostgreSQL/Redis cần được kiểm tra trên cluster đích. Chưa có backup/PITR và TLS public.

## Nguồn gốc

Phát triển từ [kevinram164/banking-demo](https://github.com/kevinram164/banking-demo) và [series Viblo](https://viblo.asia/s/0gdJzpWjVz5). Giữ nguyên thông tin bản quyền upstream trong [MIT License](LICENSE).
