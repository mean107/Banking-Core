# Lab Banking Core trên Ubuntu

Hướng dẫn dùng **Ubuntu Server 24.04 LTS, amd64**, Bash và user có quyền sudo. Máy có thể là VM hoặc máy vật lý. Các lệnh chạy trên Ubuntu, không cần Docker Desktop. Không chạy toàn bộ tài liệu như một script: thực hiện từng mục và kiểm tra kết quả trước khi tiếp tục.

## 1. Chọn phạm vi lab

| Phạm vi | Tài nguyên khởi đầu | Kết quả |
|---|---|---|
| Compose, chỉ ứng dụng | 4 vCPU, 6 GB RAM, 30 GB đĩa trống | Đăng nhập, chuyển tiền, RabbitMQ và persistence |
| Compose + monitoring | 4–8 vCPU, 10 GB RAM, 40 GB đĩa trống | Thêm metrics, logs, traces |
| Kubernetes + GitOps | 8 vCPU, 16 GB RAM, 60 GB đĩa trống | Helm, PostgreSQL/Redis HA, ArgoCD, KEDA |

Đây là mức dự trù cho lab, không phải kết quả capacity test. Khi chuyển sang Kubernetes, dừng Compose để giải phóng RAM và các cổng 3000/3001/8000/9090.

```bash
lsb_release -ds
uname -m
nproc
free -h
df -h /
```

Kỳ vọng Ubuntu 24.04, `x86_64`, đủ RAM/đĩa. Máy cần truy cập Internet tới GitHub, GHCR, Docker Hub và các Helm repository.

## 2. Cài Docker Engine và công cụ cơ bản

Áp dụng cho Ubuntu mới. Nếu đã có Docker, kiểm tra `docker version` và `docker compose version` trước; không cần cài lại. Nếu đang dùng gói `docker.io` của Ubuntu, xử lý xung đột theo [hướng dẫn Docker chính thức](https://docs.docker.com/engine/install/ubuntu/) trước khi đổi sang Docker CE.

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg git jq openssl python3 python3-venv
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "$VERSION_CODENAME")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
```

Thoát SSH rồi đăng nhập lại để nhận group mới. Group `docker` có quyền điều khiển daemon với mức quyền tương đương root; chỉ thêm user vận hành lab.

```bash
docker run --rm hello-world
docker version
docker compose version
docker buildx version
```

Nếu bị `permission denied` ở Docker socket, kiểm tra `id -nG` đã có `docker` chưa. Không dùng `chmod 666 /var/run/docker.sock`.

## 3. Clone source và tạo Python environment

```bash
mkdir -p ~/labs
cd ~/labs
git clone https://github.com/mean107/Banking-Core.git
cd Banking-Core
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python --version
```

Kỳ vọng Python 3.12. Mỗi lần mở terminal mới, chạy `cd ~/labs/Banking-Core` và `source .venv/bin/activate`. Không dùng `sudo pip install`.

## 4. Cấu hình và chạy Compose

Tạo `.env` một lần, không ghi đè khi đã có dữ liệu:

```bash
if [ ! -f .env ]; then
  umask 077
  {
    printf 'DB_PASSWORD=%s\n' "$(openssl rand -hex 16)"
    printf 'REDIS_PASSWORD=%s\n' "$(openssl rand -hex 16)"
    printf 'RABBITMQ_PASSWORD=%s\n' "$(openssl rand -hex 16)"
    printf 'GRAFANA_PASSWORD=%s\n' "$(openssl rand -hex 16)"
  } > .env
fi
chmod 600 .env
docker compose config --quiet
docker compose up -d --build --wait --wait-timeout 300
docker compose ps -a
```

Kỳ vọng PostgreSQL/Redis/RabbitMQ và backend healthy; frontend/Kong running. `migrate` có trạng thái `Exited (0)` là bình thường vì đây là job khởi tạo schema. Nếu `up --wait` hết thời gian, đọc log thay vì xóa volume:

```bash
docker compose logs --tail=100 migrate api auth account transfer notification
docker compose logs --tail=100 postgres redis rabbitmq kong
```

Không đổi mật khẩu trong `.env` rồi giữ nguyên database volume và kỳ vọng mật khẩu DB tự đổi. Các biến khởi tạo PostgreSQL chỉ áp dụng khi volume còn trống.

Nếu terminal trước đó đã export credentials cho Kubernetes, chạy `unset DB_PASSWORD REDIS_PASSWORD RABBITMQ_PASSWORD GRAFANA_PASSWORD` trước khi quay lại Compose để Compose đọc đúng `.env` của môi trường local.

## 5. Truy cập giao diện

| Dịch vụ | URL trên máy Ubuntu | Đăng nhập |
|---|---|---|
| Banking UI | http://127.0.0.1:3000 | Tự đăng ký hai tài khoản |
| API qua Kong | http://127.0.0.1:8000 | Header `X-Session` |
| RabbitMQ | http://127.0.0.1:15672 | `banking` / `RABBITMQ_PASSWORD` trong `.env` |

Các cổng chỉ bind loopback. Nếu Ubuntu là server, chạy lệnh sau **trên máy có trình duyệt**, thay `labuser@UBUNTU_IP` bằng SSH host của bạn:

```bash
ssh -N \
  -L 3000:127.0.0.1:3000 \
  -L 3001:127.0.0.1:3001 \
  -L 8000:127.0.0.1:8000 \
  -L 9090:127.0.0.1:9090 \
  -L 15672:127.0.0.1:15672 \
  labuser@UBUNTU_IP
```

Giữ terminal tunnel mở và vào `http://localhost:3000` trên máy của bạn. Chỉ cần cho phép SSH tới Ubuntu; không cần mở DB, Redis hoặc RabbitMQ ra Internet.

## 6. Kiểm tra nghiệp vụ và persistence

```bash
python -m pytest -q
python scripts/smoke.py --base-url http://127.0.0.1:8000
```

Smoke test tạo hai user riêng, chuyển tiền, retry cùng key, kiểm tra số dư và logout. Kỳ vọng JSON có `smoke`, `duplicate_retry`, `logout` đều là `passed`. Test PostgreSQL concurrency sẽ skip nếu chưa có `TEST_DATABASE_URL`; cách chạy riêng ở [VALIDATION.md](VALIDATION.md).

Trên UI, đăng ký hai tài khoản rồi dùng hai browser profile để đăng nhập riêng. Chuyển một số tiền nhỏ, kiểm tra thông báo và số dư người nhận.

Để kiểm tra dữ liệu sống qua restart, dùng tài khoản UI vừa tạo:

```bash
docker compose restart postgres
docker compose exec postgres pg_isready -U banking -d banking
```

Chờ PostgreSQL sẵn sàng rồi đăng nhập và kiểm tra số dư cũ. Không dùng một lượt smoke mới để kết luận dữ liệu cũ vẫn còn, vì smoke luôn tạo user mới.

## 7. Bật observability

```bash
docker compose --profile observability up -d
docker compose --profile observability ps
curl -fsS http://127.0.0.1:9090/-/ready
curl -fsS http://127.0.0.1:3001/api/health
python scripts/smoke.py
```

Grafana ở `http://localhost:3001`, user `admin`, mật khẩu `GRAFANA_PASSWORD` trong `.env`. Chờ vài chục giây cho hệ thống thu thập dữ liệu.

- Dashboard **Banking Core Operations**: RPS, P95, 5xx và consumer throughput.
- Explore → Loki: `{service="transfer"}`.
- Explore → Tempo: tìm service `banking-api` hoặc tra trace ID từ log.
- Prometheus → Status/Targets: các endpoint backend phải `UP`.

Khi chưa bật profile này, backend có thể log lỗi kết nối tới `otel-collector`; đó là exporter chưa có nơi nhận trace. Sau khi bật profile, kiểm tra log collector nếu trace vẫn trống:

```bash
docker compose --profile observability logs --tail=100 alloy loki tempo otel-collector
```

Alloy local đọc Docker socket. Với Docker Engine mới, nếu log báo API version không tương thích, cần cập nhật Alloy tương thích và kiểm tra lại cấu hình; không đổi quyền socket để chữa lỗi version.

## 8. Load test bằng container k6

Không cần cài k6 lên host. Container dùng host network của Linux để gọi Kong qua loopback:

```bash
mkdir -p evidence
docker run --rm --network host \
  --user "$(id -u):$(id -g)" \
  -e BASE_URL=http://127.0.0.1:8000 \
  -v "$PWD:/work" -w /work \
  grafana/k6:0.57.0 run \
  --summary-export /work/evidence/k6-compose.json tests/load/traffic.js
```

Kịch bản kéo dài 5 phút, tăng đến 50 VUs, kiểm tra lỗi dưới 1% và P95 dưới 3 giây. Threshold không đạt là kết quả cần phân tích, không phải lý do sửa số liệu. Compose không chạy KEDA; chuyển sang [DEPLOYMENT.md](DEPLOYMENT.md) để thử autoscaling.

## 9. Dừng hoặc chuyển sang Kubernetes

```bash
docker compose --profile observability down
docker volume ls --filter label=com.docker.compose.project=banking-core
```

Named volumes được giữ lại. `down -v` sẽ xóa dữ liệu; không dùng khi chỉ muốn dừng lab. Kubernetes tạo database/PVC mới, không tự nhận dữ liệu Compose. Hướng dẫn này chuyển cách triển khai cùng ứng dụng, không tự migrate dữ liệu giữa hai môi trường.

Tiếp tục ở [DEPLOYMENT.md](DEPLOYMENT.md). Các bài thử buffering, failover, rollback và xử lý sự cố nằm trong [RUNBOOK.md](RUNBOOK.md).
