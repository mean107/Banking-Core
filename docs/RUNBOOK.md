# Runbook vận hành và bài kiểm chứng

Mọi lệnh thay đổi workload dưới đây chỉ chạy trên lab riêng. Thêm `--context YOUR_LAB_CONTEXT` vào lệnh kubectl để chọn đúng cluster. Không coi lệnh mẫu là bằng chứng đã chạy.

## Smoke nghiệp vụ

`python scripts/smoke.py --base-url http://localhost:8000`

Script tạo hai user riêng, đăng nhập, chuyển 123, gửi lại cùng idempotency key, kiểm tra chỉ trừ một lần, đọc thông báo, logout và xác nhận session bị revoke. Không xóa dữ liệu hiện có.

## Quan sát request

1. Chạy smoke và load test để sinh dữ liệu.
2. Prometheus: `sum(rate(banking_http_requests_total[1m]))`.
3. Grafana: dashboard Banking Core Operations; xem RPS, P95, 5xx ratio, consumer throughput.
4. Explore → Loki: `{service="transfer"}`; tìm `consumer_completed`, lấy `trace_id`.
5. Explore → Tempo: tìm trace theo trace ID. Kiểm tra span HTTP API và span `transfer.process` nằm trong cùng trace, không chỉ có health-check spans rời rạc.
6. Collector chỉ tạo trace pipeline; log thu riêng bằng Alloy. Alert rule có trong Prometheus chart, chưa cấu hình kênh gửi thông báo bên ngoài.

## Load test / KEDA

```powershell
k6 run --summary-export evidence/k6-summary.json tests/load/traffic.js
kubectl -n banking get scaledobject,hpa
kubectl -n banking get deployment api -w
```

k6 tạo user rồi gọi account/me, tăng lên 50 VUs; đây không phải cam kết đạt 1.000 CCU. KEDA query metric API, threshold 10 RPS/replica, min 2 max 6. Scale-out không khắc phục mọi bottleneck: consumer, DB hoặc Redis có thể trở thành giới hạn tiếp theo.

Lưu thời gian bắt đầu/kết thúc, cấu hình node, VUs, RPS, P95, errors, replica trước/trong/sau tải. HPA scale-down có stabilization window nên replica không giảm ngay lập tức.

## RabbitMQ buffering

Trên Compose local:

1. Tạo user/login và lưu session.
2. `docker compose stop account`.
3. Gửi GET `/api/account/me` với `X-Session` ở terminal khác; request đang chờ.
4. Trong dưới 30 giây: `docker compose start account`.
5. Request phải hoàn tất, queue giảm. Quan sát queue `account.requests` trong RabbitMQ UI.

Giới hạn: queue tối đa 10.000 message, TTL message theo timeout 30s. Request hết hạn chưa được xử lý có thể bị RabbitMQ bỏ; request đã bắt đầu xử lý vẫn có thể commit sau khi HTTP timeout. Với chuyển tiền, retry **cùng Idempotency-Key**. Không tạo key mới cho cùng ý định chuyển tiền có kết quả chưa xác định.

## PostgreSQL failover

```powershell
kubectl -n data-postgres get cluster banking-db -o jsonpath='{.status.currentPrimary}'
kubectl -n data-postgres get pods -l cnpg.io/cluster=banking-db -o wide
```

Ghi primary và số dư trước thử nghiệm. Xóa đúng pod primary vừa đọc trong lab bằng `kubectl -n data-postgres delete pod <PRIMARY_POD>`. Theo dõi Cluster, pod và endpoint `banking-db-rw`. Chờ primary mới Ready, chạy smoke và kiểm tra dữ liệu cũ. Ghi thời gian lỗi và phục hồi; không đặt trước RTO/RPO bằng 0.

CNPG ở baseline dùng replication mặc định, chưa cấu hình synchronous commit/quorum. HA không đảm bảo không mất dữ liệu trong mọi sự cố, không thay thế backup/PITR.

## Redis Sentinel failover

```powershell
kubectl -n data-redis exec redis-1 -c sentinel -- redis-cli -p 26379 sentinel get-master-addr-by-name banking
```

`REDISCLI_AUTH` đã có trong container. Đọc tên master, đối chiếu với pod rồi xóa đúng pod master trong lab. Từ một pod còn sống, query Sentinel đến khi master thay đổi. Kiểm tra login/session qua API và `/ready`. Client dùng cả ba Sentinel và `master_for`, không hardcode Redis primary endpoint.

Sentinel cần quorum 2. Không xóa đồng thời nhiều Redis pod. Replication Redis bất đồng bộ có thể mất session/response mới ghi trong tình huống lỗi; user có thể cần login lại. Số dư nằm trong PostgreSQL.

## Persistent storage

Tạo user và chuyển tiền, ghi lại dữ liệu. Restart một pod dữ liệu, chờ Ready rồi đọc lại. Không xóa PVC/volume để mô phỏng restart. Kiểm tra cả PVC Bound và volume mount trước khi kết luận persistence hoạt động.

## Xử lý sự cố

| Triệu chứng | Kiểm tra |
|---|---|
| 503 | Readiness API, Redis Sentinel, RabbitMQ connection, DNS, credentials |
| 504 | Queue depth, consumer pod/log, DB connection pool; tra kết quả giao dịch trước khi retry |
| Pod Pending | PVC, StorageClass, tài nguyên, required anti-affinity và đủ 3 node |
| ImagePullBackOff | Tag `initial` chưa thay, package private, imagePullSecret, kết nối registry |
| ArgoCD OutOfSync | Commit image, repo credential, Helm values; API replicas được KEDA quản lý |
| KEDA không scale | API có traffic không; Prometheus scrape từng pod; query có RPS; HPA events |
| Logs/traces trống | Alloy RBAC, Loki readiness, OTEL endpoint, Collector logs, tạo request nghiệp vụ |

## Hồ sơ bằng chứng

Đặt kết quả thật vào `evidence/`: log CI, smoke JSON, k6 summary, ảnh dashboard, ArgoCD status, trạng thái primary trước/sau và timestamps. Không lưu session/password vào file public. Xem `docs/VALIDATION.md` để phân biệt những gì đã kiểm tra tại máy và những gì cần chạy trên cluster.
