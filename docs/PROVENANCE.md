# Nguồn gốc và các quyết định kỹ thuật

- Upstream: https://github.com/kevinram164/banking-demo
- Series: https://viblo.asia/s/0gdJzpWjVz5
- Source local được đọc: `C:\Users\Admin\Downloads\banking-demo`.
- Commit upstream local: `3768a19140ce0c3fcc602b3d879960b16be1462b`.
- Giữ nguyên MIT license và copyright upstream tại `LICENSE`.
- Giao diện React được lấy từ frontend bản gốc; đổi tên, bổ sung logout phía server, refresh số dư khi nhận WebSocket và giữ idempotency key cho retry.
- Backend được tổ chức lại thành một package dùng chung với năm runtime role. Duy trì nghiệp vụ đăng ký/login, tài khoản, chuyển tiền, thông báo; hợp nhất kiến trúc queue của Phase 8 với deployment/monitoring/GitOps.
- Helm và pipeline được viết lại cho một project thống nhất; loại domain, registry credentials và storage class riêng của tác giả gốc.
- PostgreSQL chuyển sang CloudNativePG vì primary/read-replica đơn thuần không đủ chứng minh tự động failover. Redis dùng Sentinel và client discovery thực tế.
- Log collector dùng Alloy. Không sao chép các Helm chart vendor lớn hoặc toàn bộ chín phase thành các bản ứng dụng trùng lặp.
- Không đưa Jenkins/Harbor/Vault, chatbot, Kafka, AWS hoặc Java vào project này: chúng không nằm trong bốn bullet Core Banking System.

Tài liệu kỹ thuật tham khảo:

- https://github.com/cloudnative-pg/charts
- https://cloudnative-pg.io/documentation/1.25/bootstrap/
- https://redis.io/docs/latest/operate/oss_and_stack/management/sentinel/
- https://keda.sh/docs/2.17/scalers/prometheus/
- https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.kubernetes/

## Giới hạn được giữ rõ

- Shared PostgreSQL schema; không tuyên bố mỗi microservice sở hữu database riêng.
- Request buffering không tăng năng lực DB vô hạn và không đảm bảo request luôn thành công.
- Transfer receipt chống duplicate cho cùng user/key. Redis response bị mất vẫn retry được nếu còn dùng cùng key và session phù hợp.
- Notification record được commit cùng chuyển tiền; push realtime là best effort, có thể mất khi Redis outage. Chưa dùng transactional outbox để đảm bảo push.
- Chưa có backup/PITR, TLS public, NetworkPolicy, WAF, audit/compliance hoặc threat model cho production.
- Required anti-affinity cho dữ liệu tránh tập trung replica lên một node, nhưng HA vẫn phụ thuộc storage/network và quorum.
- Pipeline/template sẵn sàng cho lab không phải bằng chứng về lịch sử vận hành của người dùng; hồ sơ kết quả chỉ điền khi thực sự chạy.
