# Runbook lab trên Ubuntu

Chạy Bash từ `~/labs/Banking-Core`, đã `source .venv/bin/activate`. Với Kubernetes, đặt `export LAB_CONTEXT=k3d-banking-lab` và mở port-forward Kong 8000, Prometheus 9090, Grafana 3001 theo [DEPLOYMENT.md](DEPLOYMENT.md). Với Compose, dùng các cổng tương ứng đã publish. Không chạy hai môi trường cùng cổng.

## 1. Kiểm tra cơ bản

```bash
export BASE_URL=http://127.0.0.1:8000
python scripts/smoke.py --base-url "$BASE_URL"
```

Kỳ vọng `smoke`, `duplicate_retry`, `logout` đều `passed`. Script tạo tài khoản mới mỗi lần; để kiểm tra dữ liệu sau sự cố, cần đọc lại tài khoản cũ như mục 2.

## 2. Lab chuyển tiền và idempotency bằng curl

Các lệnh sau dùng trong **cùng một terminal**. Tài khoản có hậu tố riêng để không đụng dữ liệu cũ. Mật khẩu này chỉ dùng cho tài khoản demo:

```bash
export BASE_URL=http://127.0.0.1:8000
SUFFIX=$(date +%s)
ALICE="alice_$SUFFIX"
BOB="bob_$SUFFIX"
for user in "$ALICE" "$BOB"; do
  jq -n --arg u "$user" '{username:$u,password:"LabPass123!"}' \
    | curl -fsS "$BASE_URL/api/auth/register" \
        -H 'Content-Type: application/json' -d @- | jq .
done
SESSION=$(jq -n --arg u "$ALICE" '{username:$u,password:"LabPass123!"}' \
  | curl -fsS "$BASE_URL/api/auth/login" -H 'Content-Type: application/json' -d @- \
  | jq -er .session)
KEY=$(cat /proc/sys/kernel/random/uuid)
BODY=$(jq -n --arg to "$BOB" '{to_username:$to,amount:123}')

curl -fsS "$BASE_URL/api/account/me" -H "X-Session: $SESSION" | jq .
for attempt in 1 2; do
  curl -fsS "$BASE_URL/api/transfer/transfer" \
    -H 'Content-Type: application/json' \
    -H "X-Session: $SESSION" -H "Idempotency-Key: $KEY" \
    -d "$BODY" | jq .
done
curl -fsS "$BASE_URL/api/account/me" -H "X-Session: $SESSION" | jq .
curl -fsS "$BASE_URL/api/notifications/notifications" -H "X-Session: $SESSION" | jq .
```

Kỳ vọng Alice từ 100000 còn 99877; hai response có cùng `transfer_id`. Không trừ thêm ở lần retry. Muốn kiểm tra conflict, gửi cùng key nhưng đổi amount: API phải trả 409. Với timeout/503, kết quả chuyển tiền có thể chưa xác định; retry cùng payload và key, không tự tạo key mới.

Sau restart hoặc failover, dùng lại lệnh GET `/api/account/me` trên **SESSION cũ**. Nếu session Redis bị mất, login lại Alice rồi kiểm tra vẫn còn 99877; dữ liệu tiền nằm ở PostgreSQL.

## 3. Metrics, logs và traces

Sau khi gửi vài request:

```bash
curl -fsSG http://127.0.0.1:9090/api/v1/query \
  --data-urlencode 'query=sum(rate(banking_http_requests_total[1m]))' | jq '.data.result'
curl -fsSG http://127.0.0.1:9090/api/v1/query \
  --data-urlencode 'query=sum by (role) (rate(banking_messages_total[1m]))' | jq '.data.result'
```

Chờ ít nhất hai chu kỳ scrape nếu query ban đầu rỗng. Grafana:

1. Dashboard **Banking Core Operations**: RPS, P95, tỷ lệ 5xx, throughput từng consumer.
2. Explore → Loki → `{service="transfer"}` → tìm `consumer_completed`.
3. Lấy trường `trace_id`, sang Explore → Tempo → tìm theo trace ID.
4. Kiểm tra cùng trace có HTTP span của `banking-api` và span `transfer.process`; đây là kiểm tra context qua RabbitMQ.

Compose dùng static service targets; Kubernetes scrape từng pod. Alert rule nằm trong chart Prometheus, chưa nối kênh gửi cảnh báo. Không thấy log thì kiểm tra Alloy/Loki; không có trace thì kiểm tra app/Collector/Tempo, không chỉ Grafana.

## 4. Load test và KEDA

Chỉ Kubernetes mới có KEDA. Trước test:

```bash
kubectl --context "$LAB_CONTEXT" -n banking get scaledobject,hpa
kubectl --context "$LAB_CONTEXT" -n banking get deployment api
mkdir -p evidence
date -Is > evidence/load-start.log
```

Mở terminal khác để theo dõi:

```bash
kubectl --context "$LAB_CONTEXT" -n banking get hpa -w
```

Chạy k6 trên Ubuntu, không cần cài binary:

```bash
docker run --rm --network host \
  --user "$(id -u):$(id -g)" \
  -e BASE_URL=http://127.0.0.1:8000 \
  -v "$PWD:/work" -w /work \
  grafana/k6:0.57.0 run \
  --summary-export /work/evidence/k6-kubernetes.json tests/load/traffic.js
date -Is > evidence/load-end.log
kubectl --context "$LAB_CONTEXT" -n banking get deployment api
```

Test tăng tới 50 VUs trong 5 phút. KEDA dùng tổng RPS, threshold 10/replica, min 2 max 6; không cam kết chắc chắn đạt max replica. Prometheus query trong ScaledObject phải trả số khác 0 khi có traffic. Sau dừng tải, đợi stabilization window của HPA trước khi kết luận scale-down lỗi.

Chỉ API producer được scale; consumer giữ replica cố định. k6 đi qua `kubectl port-forward` cũng chịu giới hạn kết nối của port-forward, nên đây là bài lab chức năng, không phải benchmark production. Lưu cấu hình node, image SHA, P95, error rate, RPS và replica thay vì chỉ chụp số VUs.

## 5. RabbitMQ buffering

Thực hiện trên **Compose**, dùng `SESSION` từ mục 2. Chạy trong cùng terminal:

```bash
docker compose stop account
(
  sleep 5
  docker compose start account
) &
RECOVERY_PID=$!
curl --max-time 40 -sS -w '\nHTTP %{http_code}; duration %{time_total}s\n' \
  "$BASE_URL/api/account/me" -H "X-Session: $SESSION"
wait "$RECOVERY_PID"
docker compose ps account
```

Request phải chờ consumer được bật lại rồi trả 200 nếu startup hoàn tất trước 30s. Quan sát queue `account.requests` trong RabbitMQ management. Nếu quá timeout, API trả 504; bật consumer và kiểm tra lại trước khi thử tiếp.

Queue giới hạn 10000 message, TTL theo timeout 30s; message hết hạn chưa được xử lý có thể bị bỏ. Message đã bắt đầu xử lý vẫn có thể commit sau khi HTTP timeout. Persistent message/volume không có nghĩa RabbitMQ một node là HA.

## 6. PostgreSQL: phục hồi pod và quan sát failover

Chỉ thực hiện trong cluster lab và khi cả 3 PostgreSQL pod đang Ready. Giữ lại tài khoản/số dư từ mục 2.

```bash
kubectl --context "$LAB_CONTEXT" -n data-postgres get cluster banking-db
kubectl --context "$LAB_CONTEXT" -n data-postgres get pods \
  -l cnpg.io/cluster=banking-db -o wide
OLD_PRIMARY=$(kubectl --context "$LAB_CONTEXT" -n data-postgres get cluster banking-db \
  -o jsonpath='{.status.currentPrimary}')
test -n "$OLD_PRIMARY"
printf 'Primary before: %s\n' "$OLD_PRIMARY"
kubectl --context "$LAB_CONTEXT" -n data-postgres delete pod "$OLD_PRIMARY"
```

Quan sát terminal khác:

```bash
kubectl --context "$LAB_CONTEXT" -n data-postgres get cluster banking-db -w
```

Sau khi ổn định:

```bash
kubectl --context "$LAB_CONTEXT" -n data-postgres wait cluster/banking-db \
  --for=condition=Ready --timeout=300s
NEW_PRIMARY=$(kubectl --context "$LAB_CONTEXT" -n data-postgres get cluster banking-db \
  -o jsonpath='{.status.currentPrimary}')
printf 'Primary before=%s after=%s\n' "$OLD_PRIMARY" "$NEW_PRIMARY"
curl -fsS "$BASE_URL/api/account/me" -H "X-Session: $SESSION" | jq .
```

Xóa pod không đảm bảo primary đổi: nếu pod khởi động lại đủ nhanh, operator có thể giữ nguyên primary. Chỉ ghi nhận **failover** nếu primary thực sự đổi; nếu không, đây là kiểm chứng pod recovery. Theo dõi log operator và mốc thời gian, không suy ra RTO/RPO bằng 0. Replication mặc định bất đồng bộ; HA không thay backup/PITR.

## 7. Redis Sentinel: chuyển master có kiểm soát

Đảm bảo cả 3 pod Redis Ready. Xác định master từ Sentinel:

```bash
kubectl --context "$LAB_CONTEXT" -n data-redis get pods -o wide
kubectl --context "$LAB_CONTEXT" -n data-redis exec redis-1 -c sentinel -- \
  redis-cli -p 26379 --raw sentinel get-master-addr-by-name banking
```

`REDISCLI_AUTH` đã có trong container, không cần đưa password vào command line. Yêu cầu Sentinel chuyển master để kiểm tra client discovery:

```bash
kubectl --context "$LAB_CONTEXT" -n data-redis exec redis-1 -c sentinel -- \
  redis-cli -p 26379 sentinel failover banking
```

Query lại mỗi vài giây đến khi master thay đổi:

```bash
kubectl --context "$LAB_CONTEXT" -n data-redis exec redis-1 -c sentinel -- \
  redis-cli -p 26379 --raw sentinel get-master-addr-by-name banking
curl -sS -w '\nHTTP %{http_code}\n' "$BASE_URL/api/account/me" \
  -H "X-Session: $SESSION"
```

Đây là **planned failover**, không mô phỏng mất node. Client dùng danh sách 3 Sentinel và `master_for`. Nếu muốn thử crash pod, xóa đúng master pod sau khi đối chiếu hostname; giống PostgreSQL, pod phục hồi nhanh có thể không dẫn tới đổi master. Không xóa nhiều Redis pod đồng thời; quorum là 2. Redis replication bất đồng bộ có thể mất session mới, nhưng không làm mất số dư PostgreSQL.

## 8. GitOps và rollback

```bash
kubectl --context "$LAB_CONTEXT" -n argocd get applications
kubectl --context "$LAB_CONTEXT" -n banking get deploy api \
  -o jsonpath='{.spec.template.spec.containers[0].image}'
printf '\n'
git log --oneline -- deploy/environments/lab/images.yaml
```

Trong repo bạn có quyền ghi, revert **đúng commit cập nhật image** cần rollback rồi push. Trước khi làm, kiểm tra không có schema migration không tương thích. ArgoCD sẽ đồng bộ image cũ; không `helm rollback` trên release đã giao cho ArgoCD. Sau rollout, chạy smoke và kiểm tra user cũ.

## 9. Chẩn đoán nhanh

```bash
kubectl --context "$LAB_CONTEXT" get events -A --sort-by=.lastTimestamp | tail -n 40
kubectl --context "$LAB_CONTEXT" -n banking get pods -o wide
kubectl --context "$LAB_CONTEXT" -n banking logs deployment/api --tail=100
kubectl --context "$LAB_CONTEXT" -n banking logs deployment/transfer --tail=100
kubectl --context "$LAB_CONTEXT" -n data-postgres get pvc
kubectl --context "$LAB_CONTEXT" -n data-redis get pvc
```

| Lỗi | Kiểm tra / hướng xử lý |
|---|---|
| `invalid ownership metadata` | Namespace preparation mục 5 DEPLOYMENT; không adopt namespace của release khác |
| `ImagePullBackOff` | Tag và quyền GHCR; imagePullSecret cần cho cả app và schema job |
| Pod Pending | `describe pod`, PVC/StorageClass, node tài nguyên và required anti-affinity |
| 503 | Redis/Sentinel, RabbitMQ, readiness API, DNS, credentials |
| 504 | Queue depth, consumer log, DB pool; retry chuyển tiền cùng key |
| `Existing secret differs` | Source lại đúng file credentials cũ, không generate lại mật khẩu |
| KEDA không scale | Prometheus Targets/PromQL, ScaledObject events, API có traffic chưa |
| Logs trống | Alloy RBAC hoặc Docker API compatibility, Loki readiness |
| Traces trống | `OTEL_EXPORTER_OTLP_ENDPOINT`, Collector logs, Tempo; gửi request nghiệp vụ |
| ArgoCD repo inaccessible | Git repository credential trong ArgoCD, không phải credential host |
| Port already allocated | Compose chưa down, hoặc port-forward/tunnel cũ còn chạy |

## 10. Lưu kết quả

Lưu vào `evidence/`: ngày chạy, source commit, image SHA, môi trường, smoke JSON, k6 summary, master/primary trước-sau và thời gian phục hồi. Loại bỏ session/token/password trước khi chia sẻ. Tham khảo [VALIDATION.md](VALIDATION.md) để phân biệt kết quả đã xác nhận với kế hoạch kiểm tra.
