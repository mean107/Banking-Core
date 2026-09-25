# Banking Core — Application Operation / DevOps Lab

Project thực hành vận hành ứng dụng banking nhiều service, được tổng hợp theo đúng phần **Core Banking System** trong CV Hoang Tuan Nghia. Phát triển từ ý tưởng và giao diện của [kevinram164/banking-demo](https://github.com/kevinram164/banking-demo), [series hướng dẫn Viblo](https://viblo.asia/s/0gdJzpWjVz5). Xem [nguồn gốc và thay đổi](docs/PROVENANCE.md).

Đây là **lab có source, cấu hình triển khai và bài kiểm chứng**, không phải core banking dùng cho tiền thật. Có cấu hình HA không đồng nghĩa đã có kết quả diễn tập HA. Trạng thái kiểm chứng tại máy được ghi tại [VALIDATION.md](docs/VALIDATION.md).

## Khớp với CV như thế nào?

| Ý trong CV | Thành phần cụ thể |
|---|---|
| Multi-service, Docker Compose → Kubernetes/Helm | React, Kong, API producer, auth/account/transfer/notification; `compose.yaml`; 3 Helm chart |
| GitHub Actions + ArgoCD | Test → build 2 image → GHCR → commit image SHA → ArgoCD sync |
| Prometheus, Grafana, Loki, Tempo, OpenTelemetry | Metrics API/consumer; dashboard; Alloy thu logs; trace context qua RabbitMQ |
| KEDA scale theo traffic | ScaledObject tăng/giảm API replica theo RPS của ứng dụng |
| RabbitMQ request buffering | Durable queue, persistent message, publisher confirm, prefetch, TTL, giới hạn queue |
| PostgreSQL/Redis HA | CloudNativePG 3 instance; Redis 3 pod + Sentinel quorum 2; client khám phá primary |
| Load test, persistent storage, namespace separation | k6; PVC/Compose volumes; namespace app/data/messaging/gateway/observability |

Chi tiết từng claim, file và cách chứng minh: [CV-MAPPING.md](docs/CV-MAPPING.md).

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

## Chạy local

Yêu cầu Docker Engine Linux/Compose v2. Dùng khoảng 4 GB RAM cho ứng dụng; thêm observability cần nhiều hơn.

```powershell
cd C:\Kubernetes\Banking-Core
Copy-Item .env.example .env
docker compose up -d --build --wait --wait-timeout 240
```

- Giao diện: <http://localhost:3000>
- API qua Kong: <http://localhost:8000>
- RabbitMQ management: <http://localhost:15672> (`banking`, mật khẩu trong `.env`)
- Tạo hai tài khoản để thử chuyển tiền; mỗi tài khoản demo được cấp 100.000.

Thêm monitoring:

```powershell
docker compose --profile observability up -d
```

- Grafana: <http://localhost:3001>, user `admin`, `GRAFANA_PASSWORD` trong `.env`.
- Prometheus: <http://localhost:9090>.
- Grafana dashboard **Banking Core Operations**; Explore → Loki hoặc Tempo.
- Alloy local đọc Docker socket để thu logs. Chỉ dùng cấu hình này trong môi trường lab tin cậy.

## Kiểm thử

Python 3.12 và Helm 3.17.3:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python scripts/validate.py
python scripts/smoke.py --base-url http://localhost:8000
```

`validate.py` không deploy, không thay đổi cluster. Test concurrency PostgreSQL được skip nếu chưa đặt `TEST_DATABASE_URL`; SQLite unit test không chứng minh row locking trên PostgreSQL.

## Kubernetes / GitOps

Đọc [DEPLOYMENT.md](docs/DEPLOYMENT.md). Cần 3 node schedulable, StorageClass mặc định và image đã build/publish. Repository và GHCR trong mẫu dùng `mean107/Banking-Core`; chưa có thao tác push/publish nào được thực hiện khi tạo project local.

```powershell
python scripts/bootstrap.py --context YOUR_LAB_CONTEXT --gitops
```

Lệnh này thực sự cài operator, tạo namespace/Secret, triển khai platform/monitoring và đăng ký ArgoCD applications. Phải đặt bốn biến mật khẩu trước theo tài liệu. Không chạy trên cluster ngoài phạm vi lab.

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
docs/                 Mapping CV, triển khai, runbook, giới hạn, nguồn gốc
```

Các version là baseline cố định để tái lập lab, không phải cam kết đang là bản mới nhất. Trước khi dùng ngoài lab cần cập nhật và đánh giá bảo mật/dependency. Không đưa Jenkins, Kafka, Vault hoặc AWS vào luồng chính vì chúng không thuộc mô tả project Core Banking trong CV.
