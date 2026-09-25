# Kubernetes và GitOps trên Ubuntu

Thực hiện sau [UBUNTU-LAB.md](UBUNTU-LAB.md): đã có Docker Engine, Git, Python venv và source tại `~/labs/Banking-Core`. Lệnh dùng Bash trên Ubuntu 24.04 amd64. Dừng Compose trước để tránh trùng cổng và thiếu RAM.

## 1. Mô hình lab

Lộ trình chính dùng **k3d: 1 server + 3 agent** trên một máy Ubuntu. Mỗi node Kubernetes là một container Docker; K3s cung cấp StorageClass `local-path`. Cấu hình này đủ để phân tán PostgreSQL/Redis theo node và thử pod failover.

Các node vẫn chung một host vật lý: host tắt thì cả cluster tắt. Muốn thử lỗi máy, dùng ít nhất 3 Ubuntu VM/host độc lập và storage phù hợp. Phần ứng dụng từ mục 4 trở đi dùng được với cluster riêng nếu có ít nhất 3 node schedulable và StorageClass mặc định.

Baseline: Helm 3.17.3, k3d 5.8.3, K3s/Kubernetes 1.31.6. Các phiên bản được pin để khớp bộ operator trong repo, không đại diện cho bản mới nhất. Dùng cho lab cô lập; kiểm tra ma trận tương thích trước khi nâng cấp.

## 2. Cài Helm, kubectl và k3d

```bash
mkdir -p ~/lab-tools
cd ~/lab-tools
curl -fLO https://get.helm.sh/helm-v3.17.3-linux-amd64.tar.gz
curl -fLO https://get.helm.sh/helm-v3.17.3-linux-amd64.tar.gz.sha256sum
sha256sum -c helm-v3.17.3-linux-amd64.tar.gz.sha256sum
tar -xzf helm-v3.17.3-linux-amd64.tar.gz
sudo install -m 0755 linux-amd64/helm /usr/local/bin/helm

curl -fL https://dl.k8s.io/release/v1.31.6/bin/linux/amd64/kubectl -o kubectl
curl -fL https://dl.k8s.io/release/v1.31.6/bin/linux/amd64/kubectl.sha256 -o kubectl.sha256
printf '%s  kubectl\n' "$(cat kubectl.sha256)" | sha256sum --check
sudo install -m 0755 kubectl /usr/local/bin/kubectl

curl -fL https://github.com/k3d-io/k3d/releases/download/v5.8.3/k3d-linux-amd64 -o k3d
sudo install -m 0755 k3d /usr/local/bin/k3d
helm version --short
kubectl version --client
k3d version
cd ~/labs/Banking-Core
source .venv/bin/activate
```

Tham khảo chính thức: [Helm](https://helm.sh/docs/intro/install/), [kubectl Linux](https://kubernetes.io/docs/tasks/tools/install-kubectl-linux/), [k3d cluster create](https://k3d.io/v5.8.3/usage/commands/k3d_cluster_create/).

## 3. Tạo cluster

Chạy `cluster create` một lần. Nếu đã có cluster, kiểm tra `k3d cluster list` rồi dùng cluster hiện có.

```bash
k3d cluster create banking-lab \
  --image rancher/k3s:v1.31.6-k3s1 \
  --servers 1 --agents 3 \
  --api-port 127.0.0.1:6550 \
  --k3s-arg '--disable=traefik@server:0' \
  --wait
export LAB_CONTEXT=k3d-banking-lab
kubectl --context "$LAB_CONTEXT" wait --for=condition=Ready nodes --all --timeout=180s
kubectl --context "$LAB_CONTEXT" get nodes -o wide
kubectl --context "$LAB_CONTEXT" get storageclass
```

Kỳ vọng 4 node Ready, `local-path` có `(default)`. PostgreSQL/Redis có required anti-affinity; thiếu node schedulable sẽ gây Pending. `local-path` giữ dữ liệu qua pod restart trên cùng node, không replicate volume giữa các node.

Mỗi terminal mới cần `export LAB_CONTEXT=k3d-banking-lab`. Với cluster có sẵn, thay bằng context thực tế và kiểm tra endpoint:

```bash
kubectl config get-contexts
kubectl --context "$LAB_CONTEXT" cluster-info
```

## 4. Chọn nguồn image

**Cách A — Helm với image build tại Ubuntu:** không cần GHCR hoặc quyền push GitHub; phù hợp kiểm tra runtime trước, chưa chạy GitOps.

```bash
docker build -t banking-core-backend:lab -f backend/Dockerfile .
docker build -t banking-core-frontend:lab frontend
k3d image import banking-core-backend:lab banking-core-frontend:lab -c banking-lab
cp deploy/environments/lab/images.yaml /tmp/banking-images.before-lab.yaml
python - <<'PY'
from pathlib import Path
import yaml
p = Path('deploy/environments/lab/images.yaml')
p.write_text(yaml.safe_dump({
    'backend': {'repository': 'banking-core-backend', 'tag': 'lab'},
    'frontend': {'repository': 'banking-core-frontend', 'tag': 'lab'},
}, sort_keys=False))
PY
```

Không commit tag `lab` vào nhánh GitOps. Mục 10 khôi phục file từ bản backup khi chuyển sang GitOps. Image import chỉ áp dụng cho k3d; cluster VM riêng cần registry mà các node truy cập được.

**Cách B — GitOps với GHCR:** dùng image SHA thật trong file image. Trước bootstrap, kiểm tra pull được cả hai image:

```bash
python - <<'PY'
from pathlib import Path
import subprocess, yaml
values = yaml.safe_load(Path('deploy/environments/lab/images.yaml').read_text())
for name in ('backend', 'frontend'):
    image = values[name]
    assert image['tag'] not in ('initial', 'lab'), 'Cần image tag từ CI'
    subprocess.run(['docker', 'pull', image['repository'] + ':' + image['tag']], check=True)
PY
```

Nếu `denied`, xem mục 11. Đăng nhập Docker trên host không tự cấp quyền pull image cho Kubernetes.

## 5. Chuẩn bị namespace cho Helm

`bootstrap.py` tạo namespace bằng kubectl trước khi gọi Helm, trong khi chart platform cũng quản lý chúng. Với source hiện tại, cần gắn metadata sở hữu để tránh lỗi `invalid ownership metadata` khi cài lần đầu.

Chỉ áp dụng cho namespace **lab mới**, không nhận quyền quản lý namespace đang thuộc release khác:

```bash
for ns in banking data-postgres data-redis messaging gateway observability; do
  kubectl --context "$LAB_CONTEXT" create namespace "$ns" --dry-run=client -o yaml \
    | kubectl --context "$LAB_CONTEXT" apply -f -
  kubectl --context "$LAB_CONTEXT" label namespace "$ns" \
    app.kubernetes.io/managed-by=Helm --overwrite
  kubectl --context "$LAB_CONTEXT" annotate namespace "$ns" \
    meta.helm.sh/release-name=banking-platform \
    meta.helm.sh/release-namespace=banking-platform --overwrite
done
```

## 6. Tạo và giữ credentials

Lưu ngoài Git để chạy lại bootstrap với cùng mật khẩu. Không bật `set -x` trong terminal chứa secrets.

```bash
mkdir -p ~/.config/banking-core
if [ ! -f ~/.config/banking-core/lab.env ]; then
  umask 077
  {
    printf 'DB_PASSWORD=%s\n' "$(openssl rand -hex 16)"
    printf 'REDIS_PASSWORD=%s\n' "$(openssl rand -hex 16)"
    printf 'RABBITMQ_PASSWORD=%s\n' "$(openssl rand -hex 16)"
    printf 'GRAFANA_PASSWORD=%s\n' "$(openssl rand -hex 16)"
  } > ~/.config/banking-core/lab.env
fi
chmod 600 ~/.config/banking-core/lab.env
set -a
source ~/.config/banking-core/lab.env
set +a
```

Mật khẩu cần ít nhất 12 ký tự chữ/số/`-`/`_`; hex ở trên đáp ứng điều kiện. Chạy lại phải source đúng file cũ. Script dừng nếu Secret đã tồn tại khác mật khẩu cung cấp; không dùng bootstrap để rotate mật khẩu.

## 7. Bootstrap

Chọn **một** lệnh tương ứng mục 4:

```bash
# Cách A: Helm và image đã import vào k3d
python scripts/bootstrap.py --context "$LAB_CONTEXT"
```

```bash
# Cách B: ArgoCD lấy cấu hình từ Git và image từ GHCR
python scripts/bootstrap.py --context "$LAB_CONTEXT" --gitops
```

Thứ tự: Secret → CNPG 0.23.2 → KEDA 2.17.2 → platform → PostgreSQL Ready → observability → ứng dụng Helm hoặc ArgoCD 7.8.23 + Applications. Lần đầu có thể mất 10–30 phút do tải image và tạo PVC.

Terminal khác để quan sát:

```bash
kubectl --context "$LAB_CONTEXT" get pods -A -w
```

Nếu script dừng, đọc events/log ở [RUNBOOK.md](RUNBOOK.md), sửa nguyên nhân rồi chạy lại với cùng credentials. Không xóa PVC để xử lý lỗi image/namespace. Schema job chỉ tạo schema ban đầu idempotent; khi thay đổi schema cần migration versioned riêng.

## 8. Kiểm tra workload

```bash
kubectl --context "$LAB_CONTEXT" get pods -n banking
kubectl --context "$LAB_CONTEXT" get cluster banking-db -n data-postgres
kubectl --context "$LAB_CONTEXT" get pods -n data-redis -o wide
kubectl --context "$LAB_CONTEXT" get pvc -A
kubectl --context "$LAB_CONTEXT" get scaledobject,hpa -n banking
```

Kỳ vọng app Ready; PostgreSQL 3 instance và Cluster Ready; Redis 3 pod, mỗi pod 2 container Redis/Sentinel phân tán theo node; PVC Bound. PVC `WaitForFirstConsumer` có thể Pending cho tới khi pod được schedule. Schema job thành công có thể đã bị xóa theo hook policy.

## 9. Truy cập dịch vụ

Mỗi lệnh chạy trong một terminal Ubuntu riêng, giữ terminal mở:

```bash
kubectl --context "$LAB_CONTEXT" -n banking port-forward svc/frontend 3000:80
```

```bash
kubectl --context "$LAB_CONTEXT" -n gateway port-forward svc/kong 8000:8000
```

```bash
kubectl --context "$LAB_CONTEXT" -n observability port-forward svc/grafana 3001:3000
```

```bash
kubectl --context "$LAB_CONTEXT" -n observability port-forward svc/prometheus 9090:9090
```

```bash
kubectl --context "$LAB_CONTEXT" -n messaging port-forward svc/rabbitmq 15672:15672
```

Dùng SSH tunnel ở [UBUNTU-LAB.md](UBUNTU-LAB.md) nếu trình duyệt ở máy khác. Grafana dùng `admin` và password trong `~/.config/banking-core/lab.env`, không phải file `.env` Compose nếu hai file khác nhau.

```bash
python scripts/smoke.py --base-url http://127.0.0.1:8000
```

Port-forward gắn vào một pod; nếu pod đó restart thì chạy lại port-forward. Đây không phải cơ chế expose bền vững cho production.

## 10. Chuyển từ Helm local sang GitOps

Nếu đã làm cách A, khôi phục cấu hình image remote rồi kiểm tra pull image như cách B:

```bash
cp /tmp/banking-images.before-lab.yaml deploy/environments/lab/images.yaml
git diff -- deploy/environments/lab/images.yaml
```

Nếu fork, chỉnh `sourceRepos` và tất cả `repoURL` trong `deploy/argocd/applications.yaml`. Push lên `main`, đợi CI build/publish và cập nhật image SHA. Workflow cần `contents:write`, `packages:write`. Nếu branch protection cấm bot push, dùng quy trình PR cập nhật image phù hợp chính sách repo.

Source local và branch GitOps cần cùng cấu hình platform trước khi ArgoCD nhận quản lý. Source lại credentials mục 6 và chạy bootstrap với `--gitops`. Không uninstall release/PVC trước khi chuyển. Sau chuyển giao, thay đổi values trong Git, không tiếp tục `helm upgrade` bằng tay.

Mở ArgoCD:

```bash
kubectl --context "$LAB_CONTEXT" -n argocd port-forward svc/argocd-server 8081:443
```

Lấy mật khẩu admin ban đầu trong terminal riêng trên máy tin cậy:

```bash
kubectl --context "$LAB_CONTEXT" -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 --decode
printf '\n'
```

Vào `https://localhost:8081`, user `admin`, certificate tự ký của lab. Nếu truy cập qua SSH, mở thêm tunnel `ssh -N -L 8081:127.0.0.1:8081 labuser@UBUNTU_IP`.

```bash
kubectl --context "$LAB_CONTEXT" get applications -n argocd
kubectl --context "$LAB_CONTEXT" -n banking get deployment api \
  -o jsonpath='{.spec.template.spec.containers[0].image}'
printf '\n'
```

Kỳ vọng ba Application Synced, app Healthy, image SHA khớp Git. CNPG custom resource có thể cần health customization trong ArgoCD; kiểm tra thêm Cluster Ready. Rollback bằng revert image commit sau khi kiểm tra schema compatibility.

## 11. Git repository hoặc GHCR private

Lab đơn giản nhất dùng Git repository và hai package GHCR public. Nếu private, thêm Git credential trong ArgoCD Settings → Repositories trước khi sync. Git credential trên Ubuntu không truyền tự động sang ArgoCD.

Tạo imagePullSecret trong `banking` sau mục 5; dùng token có quyền đọc package:

```bash
read -rp 'GitHub username: ' GH_USER
read -rsp 'GHCR read token: ' GHCR_TOKEN
printf '\n'
export GH_USER GHCR_TOKEN
printf '%s' "$GHCR_TOKEN" | docker login ghcr.io -u "$GH_USER" --password-stdin
python - <<'PY'
import base64, json, os, subprocess
auth = base64.b64encode((os.environ['GH_USER'] + ':' + os.environ['GHCR_TOKEN']).encode()).decode()
config = json.dumps({'auths': {'ghcr.io': {'auth': auth}}})
secret = {'apiVersion': 'v1', 'kind': 'Secret',
          'metadata': {'name': 'ghcr-pull', 'namespace': 'banking'},
          'type': 'kubernetes.io/dockerconfigjson',
          'stringData': {'.dockerconfigjson': config}}
subprocess.run(['kubectl', '--context', os.environ['LAB_CONTEXT'], 'apply', '-f', '-'],
               input=json.dumps(secret), text=True, check=True)
PY
unset GHCR_TOKEN
```

Sửa `deploy/charts/banking/values.yaml` thành `imagePullSecrets: [{name: ghcr-pull}]`. Với GitOps phải commit/push trước khi sync. Secret cần tồn tại trước schema PreSync job.

## 12. Tạm dừng và dọn lab

Giữ cluster/data để dùng lại:

```bash
k3d cluster stop banking-lab
# Lần sau:
k3d cluster start banking-lab
```

Chỉ khi muốn **xóa toàn bộ cluster lab và dữ liệu local-path**, sau khi lưu kết quả cần giữ:

```bash
k3d cluster delete banking-lab
```

Bài thử KEDA, buffering và failover: [RUNBOOK.md](RUNBOOK.md).
