# Triển khai từ local đến Kubernetes/GitOps

## 1. Chuẩn bị GitHub và image

1. Kiểm tra source local, tạo commit rồi push lên repo mà bạn sở hữu. Việc tạo project này chưa push GitHub.
2. Workflow dùng GHCR (`ghcr.io/mean107/banking-core-backend`, `...-frontend`). Nếu fork, sửa `repoURL/sourceRepos` trong ArgoCD; script image tự lấy owner của GitHub Actions.
3. Cho workflow quyền `contents:write`, `packages:write`. Nếu branch protection chặn bot push `main`, dùng PR cho file image hoặc cấp quyền theo chính sách repo; không tắt bảo vệ một cách ngầm định.
4. Build cả hai image và test thành công trước khi cập nhật image tag. Tag là full commit SHA, không dùng `latest`.
5. Chọn package GHCR public cho lab, hoặc tạo imagePullSecret trong `banking` và thêm `imagePullSecrets` vào values. ArgoCD cần credential riêng nếu Git repository private.
6. Chờ file `deploy/environments/lab/images.yaml` có SHA thật, không còn `initial`.

Workflow chạy test thật trên PostgreSQL service container, build Compose và smoke API. Test/trạng thái GitHub chỉ có sau khi bạn push và chạy workflow; không được suy ra từ local validation.

## 2. Điều kiện cluster HA

- Kubernetes tương thích với các chart/operator được pin; Helm 3.17.3, kubectl, Python 3.12.
- Ít nhất **3 node schedulable**. PostgreSQL và Redis có required anti-affinity để không dồn toàn bộ replica vào một node.
- StorageClass mặc định có dynamic provisioning; PVC ReadWriteOnce, mỗi instance có volume riêng. Nếu cần class riêng, chỉnh `storageClass` ở cả platform và observability trước khi commit/bootstrap.
- DNS/service networking và egress tới registry/chart repository hoạt động.
- Lab HA tốn nhiều tài nguyên hơn Compose; dự trù tổng khoảng 8–12 GB RAM cho app, operators, dữ liệu và observability; còn phụ thuộc cluster nền.
- Không dùng cùng một thư mục dữ liệu cho các PostgreSQL replica. Một shared storage server duy nhất vẫn có thể là điểm lỗi chung.

## 3. Khởi tạo

Mở PowerShell, vào root project và dùng context lab chính xác:

```powershell
kubectl config get-contexts
$env:DB_PASSWORD = '<12+ URL-safe characters>'
$env:REDIS_PASSWORD = '<12+ URL-safe characters>'
$env:RABBITMQ_PASSWORD = '<12+ URL-safe characters>'
$env:GRAFANA_PASSWORD = '<12+ URL-safe characters>'
python scripts/bootstrap.py --context YOUR_LAB_CONTEXT --gitops
```

Mật khẩu chỉ chứa chữ/số/`-`/`_` để tránh lỗi URI/config Redis. Không commit các giá trị thật. Script truyền Secret qua stdin, không ghi credential vào file Git.

Thứ tự bootstrap:

1. Namespace và credentials.
2. CloudNativePG operator `0.23.2`, KEDA `2.17.2`.
3. Platform: PostgreSQL, Redis/Sentinel, RabbitMQ và Kong.
4. Chờ PostgreSQL Ready.
5. Monitoring chart.
6. ArgoCD chart `7.8.23` và Applications, hoặc cài ứng dụng bằng Helm nếu bỏ `--gitops`.

Đây là bước cài đặt một lần; sau khi chuyển quyền quản lý cho ArgoCD, chỉnh cấu hình trong Git thay vì tiếp tục `helm upgrade` bằng tay. Operators được bootstrap quản lý riêng; ba chart platform/observability/app được ArgoCD theo dõi.

Schema job chạy trước app. Migration hiện tạo schema ban đầu idempotent, không phải hệ thống migration nâng cấp mọi phiên bản. Khi thay schema cần thêm migration versioned và kế hoạch rollback.

## 4. Kiểm tra và truy cập

```powershell
kubectl --context YOUR_LAB_CONTEXT get applications -n argocd
kubectl --context YOUR_LAB_CONTEXT get pods -n banking
kubectl --context YOUR_LAB_CONTEXT get cluster -n data-postgres
kubectl --context YOUR_LAB_CONTEXT get pvc -A
kubectl --context YOUR_LAB_CONTEXT -n banking port-forward svc/frontend 3000:80
```

Mở terminal khác:

```powershell
kubectl --context YOUR_LAB_CONTEXT -n gateway port-forward svc/kong 8000:8000
python scripts/smoke.py --base-url http://localhost:8000
```

Port-forward observability:

```powershell
kubectl --context YOUR_LAB_CONTEXT -n observability port-forward svc/grafana 3001:3000
kubectl --context YOUR_LAB_CONTEXT -n observability port-forward svc/prometheus 9090:9090
```

Mỗi port-forward chạy trong một terminal riêng. Không yêu cầu DNS/domain/Ingress của tác giả gốc. Nếu muốn expose bên ngoài cluster, bổ sung Ingress + TLS phù hợp môi trường; baseline dùng port-forward.

## 5. Rollback

Revert commit cập nhật image tags trong Git, để ArgoCD sync về SHA trước. Kiểm tra schema compatibility trước khi rollback binary. Không dùng `helm rollback` trên release đã được ArgoCD quản lý vì Git sẽ ghi đè trạng thái tay.

## 6. Credentials và dữ liệu

Script bootstrap không âm thầm rotate mật khẩu đang tồn tại. Muốn đổi mật khẩu phải cập nhật DB/broker/Redis và Secret ứng dụng theo thứ tự, rồi rollout ứng dụng. `docker compose down` giữ named volumes; thêm `-v` sẽ mất dữ liệu. Chart platform giữ namespace; tránh prune PVC hoặc CNPG Cluster khi chỉ muốn nâng cấp ứng dụng.
