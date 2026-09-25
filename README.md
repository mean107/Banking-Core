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

## Triển khai và vận hành

Docker Compose chạy ứng dụng cùng PostgreSQL, Redis, RabbitMQ và Kong; profile observability bổ sung hệ thống giám sát. Trên Kubernetes, ba Helm chart tách ứng dụng, nền tảng dữ liệu và observability. Các thành phần được phân chia theo namespace và dùng persistent volume cho dữ liệu.

GitHub Actions chạy kiểm tra, build hai image backend/frontend và publish lên GHCR. Khi pipeline thành công, CI cập nhật image tag theo commit SHA trong `deploy/environments/lab/images.yaml`; ArgoCD đồng bộ ba application từ Git xuống cluster.

Prometheus thu metrics và cung cấp dữ liệu RPS cho KEDA scale API producer từ 2 đến 6 replica. Grafana hiển thị dashboard vận hành, truy vấn logs từ Loki và traces từ Tempo. OpenTelemetry truyền trace context qua HTTP và RabbitMQ để theo dõi request giữa API và consumer.

## Kiểm thử

Bộ kiểm thử gồm pytest cho nghiệp vụ, kiểm tra concurrency trên PostgreSQL, smoke test qua API và kịch bản tải bằng k6. Test concurrency cần PostgreSQL riêng; unit test dùng SQLite không xác nhận được hành vi row locking của PostgreSQL. Các kịch bản tải và failover phục vụ thực hành, chưa có số liệu benchmark hoặc kết quả xác nhận HA trên cluster đích.

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
```

## Phạm vi và giới hạn

Các service dùng chung PostgreSQL schema. RabbitMQ chạy một node có persistent volume; KEDA chỉ scale API producer. Cấu hình HA PostgreSQL/Redis cần được kiểm tra trên cluster đích. Chưa có backup/PITR và TLS public.

## Nguồn gốc

Phát triển từ [kevinram164/banking-demo](https://github.com/kevinram164/banking-demo) và [series Viblo](https://viblo.asia/s/0gdJzpWjVz5). Giữ nguyên thông tin bản quyền upstream trong [MIT License](LICENSE).
