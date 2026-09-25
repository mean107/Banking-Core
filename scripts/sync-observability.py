"""Generate the self-contained monitoring Helm chart from local configuration."""

from pathlib import Path
import json
import yaml

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "deploy/charts/observability"
DEST.mkdir(parents=True, exist_ok=True)
(DEST / "templates").mkdir(exist_ok=True)
(DEST / "Chart.yaml").write_text(
    "apiVersion: v2\nname: banking-observability\nversion: 1.0.0\n", encoding="utf-8"
)
(DEST / "values.yaml").write_text('storageClass: ""\n', encoding="utf-8")
docs = []


def add(kind, name, spec=None, **fields):
    doc = dict(
        apiVersion={
            "Deployment": "apps/v1",
            "ClusterRole": "rbac.authorization.k8s.io/v1",
            "ClusterRoleBinding": "rbac.authorization.k8s.io/v1",
        }.get(kind, "v1"),
        kind=kind,
        metadata={"name": name, "namespace": "observability"},
    )
    if kind.startswith("Cluster"):
        doc["metadata"].pop("namespace")
    if spec is not None:
        doc["spec"] = spec
    doc.update(fields)
    docs.append(doc)


panels = []
for i, (title, expr, unit) in enumerate(
    [
        (
            "API requests per second",
            "sum(rate(banking_http_requests_total[1m]))",
            "reqps",
        ),
        (
            "P95 API latency",
            "histogram_quantile(0.95, sum by (le) (rate(banking_http_duration_seconds_bucket[5m])))",
            "s",
        ),
        (
            "5xx ratio",
            'sum(rate(banking_http_requests_total{status=~"5.."}[5m])) / clamp_min(sum(rate(banking_http_requests_total[5m])), 0.001)',
            "percentunit",
        ),
        (
            "Consumer throughput by role",
            "sum by (role) (rate(banking_messages_total[1m]))",
            "ops",
        ),
    ]
):
    panels.append(
        {
            "id": i + 1,
            "type": "timeseries",
            "title": title,
            "datasource": {"type": "prometheus", "uid": "prometheus"},
            "gridPos": {"x": (i % 2) * 12, "y": (i // 2) * 8, "w": 12, "h": 8},
            "targets": [{"expr": expr, "refId": "A", "legendFormat": "auto"}],
            "fieldConfig": {"defaults": {"unit": unit}},
        }
    )
dashboard = {
    "uid": "banking-core",
    "title": "Banking Core Operations",
    "schemaVersion": 39,
    "version": 1,
    "refresh": "10s",
    "time": {"from": "now-30m", "to": "now"},
    "panels": panels,
}
dashdir = ROOT / "observability/grafana/dashboards"
dashdir.mkdir(exist_ok=True)
(dashdir / "banking.json").write_text(json.dumps(dashboard, indent=2), encoding="utf-8")

prom = {
    "global": {"scrape_interval": "10s"},
    "rule_files": ["/etc/banking/alerts.yaml"],
    "scrape_configs": [
        {
            "job_name": "banking-pods",
            "kubernetes_sd_configs": [
                {"role": "pod", "namespaces": {"names": ["banking"]}}
            ],
            "relabel_configs": [
                {
                    "source_labels": ["__meta_kubernetes_pod_label_part_of"],
                    "regex": "banking-core",
                    "action": "keep",
                },
                {
                    "source_labels": ["__meta_kubernetes_pod_container_port_number"],
                    "regex": "8080",
                    "action": "keep",
                },
                {
                    "source_labels": ["__meta_kubernetes_pod_phase"],
                    "regex": "Running",
                    "action": "keep",
                },
                {
                    "source_labels": ["__meta_kubernetes_pod_name"],
                    "target_label": "pod",
                },
            ],
        }
    ],
}
alerts = {
    "groups": [
        {
            "name": "banking",
            "rules": [
                {
                    "alert": "BankingHighErrorRate",
                    "expr": 'sum(rate(banking_http_requests_total{status=~"5.."}[5m])) / clamp_min(sum(rate(banking_http_requests_total[5m])), 0.001) > 0.05',
                    "for": "2m",
                    "labels": {"severity": "warning"},
                    "annotations": {"summary": "Banking 5xx rate exceeds 5%"},
                }
            ],
        }
    ]
}
alloy = """discovery.kubernetes "pods" { role = "pod" }
discovery.relabel "banking" {
  targets = discovery.kubernetes.pods.targets
  rule {
    source_labels = ["__meta_kubernetes_namespace"]
    regex = "banking"
    action = "keep"
  }
  rule {
    source_labels = ["__meta_kubernetes_pod_label_app"]
    target_label = "service"
  }
  rule {
    source_labels = ["__meta_kubernetes_pod_name"]
    target_label = "pod"
  }
}
loki.source.kubernetes "pods" {
  targets = discovery.relabel.banking.output
  forward_to = [loki.write.local.receiver]
}
loki.write "local" {
  endpoint { url = "http://loki:3100/loki/api/v1/push" }
}
"""
configs = {
    "prometheus": {
        "prometheus.yaml": yaml.safe_dump(prom),
        "alerts.yaml": yaml.safe_dump(alerts),
    },
    "loki": {"loki.yaml": (ROOT / "observability/loki.yaml").read_text()},
    "tempo": {"tempo.yaml": (ROOT / "observability/tempo.yaml").read_text()},
    "otel-collector": {"otel.yaml": (ROOT / "observability/otel.yaml").read_text()},
    "alloy": {"config.alloy": alloy},
    "grafana": {
        "datasources.yaml": (
            ROOT / "observability/grafana/provisioning/datasources/datasources.yaml"
        ).read_text(),
        "dashboards.yaml": (
            ROOT / "observability/grafana/provisioning/dashboards/dashboards.yaml"
        ).read_text(),
        "banking.json": json.dumps(dashboard),
    },
}
components = {
    "prometheus": (
        "prom/prometheus:v3.3.0",
        ["--config.file=/etc/banking/prometheus.yaml"],
        [9090],
        "/prometheus",
        65534,
    ),
    "loki": (
        "grafana/loki:3.4.2",
        ["-config.file=/etc/banking/loki.yaml"],
        [3100],
        "/loki",
        10001,
    ),
    "tempo": (
        "grafana/tempo:2.7.2",
        ["-config.file=/etc/banking/tempo.yaml"],
        [3200, 4317],
        "/var/tempo",
        10001,
    ),
    "otel-collector": (
        "otel/opentelemetry-collector-contrib:0.123.0",
        ["--config=/etc/banking/otel.yaml"],
        [4317, 4318],
        None,
        10001,
    ),
    "alloy": (
        "grafana/alloy:v1.8.1",
        ["run", "/etc/banking/config.alloy", "--storage.path=/tmp/alloy"],
        [12345],
        None,
        0,
    ),
    "grafana": ("grafana/grafana:11.6.0", None, [3000], "/var/lib/grafana", 472),
}
for name, (image, args, ports, data_path, gid) in components.items():
    add("ConfigMap", name + "-config", data=configs[name])
    if data_path:
        add(
            "PersistentVolumeClaim",
            name + "-data",
            {
                "accessModes": ["ReadWriteOnce"],
                "resources": {"requests": {"storage": "5Gi"}},
            },
        )
    mounts = [{"name": "config", "mountPath": "/etc/banking", "readOnly": True}]
    volumes = [{"name": "config", "configMap": {"name": name + "-config"}}]
    if data_path:
        mounts.append({"name": "data", "mountPath": data_path})
        volumes.append(
            {"name": "data", "persistentVolumeClaim": {"claimName": name + "-data"}}
        )
    container = {
        "name": name,
        "image": image,
        "ports": [{"containerPort": p, "name": "p" + str(p)} for p in ports],
        "volumeMounts": mounts,
        "resources": {
            "requests": {"cpu": "50m", "memory": "128Mi"},
            "limits": {"cpu": "1", "memory": "512Mi"},
        },
    }
    if args:
        container["args"] = args
    if name == "grafana":
        for key, path in [
            (
                "datasources.yaml",
                "/etc/grafana/provisioning/datasources/datasources.yaml",
            ),
            ("dashboards.yaml", "/etc/grafana/provisioning/dashboards/dashboards.yaml"),
            ("banking.json", "/var/lib/grafana/dashboards/banking.json"),
        ]:
            mounts.append({"name": "config", "subPath": key, "mountPath": path})
        container["env"] = [
            {
                "name": "GF_SECURITY_ADMIN_PASSWORD",
                "valueFrom": {
                    "secretKeyRef": {"name": "grafana-auth", "key": "password"}
                },
            }
        ]
    if name in ("prometheus", "loki", "tempo", "grafana"):
        container["readinessProbe"] = {
            "httpGet": {
                "path": {
                    "prometheus": "/-/ready",
                    "loki": "/ready",
                    "tempo": "/ready",
                    "grafana": "/api/health",
                }[name],
                "port": ports[0],
            },
            "initialDelaySeconds": 10,
        }
    pod = {
        "containers": [container],
        "volumes": volumes,
        "securityContext": {"fsGroup": gid},
    }
    if name in ("prometheus", "alloy"):
        pod["serviceAccountName"] = "banking-observer"
    add(
        "Deployment",
        name,
        {
            "replicas": 1,
            "strategy": {"type": "Recreate"},
            "selector": {"matchLabels": {"app": name}},
            "template": {"metadata": {"labels": {"app": name}}, "spec": pod},
        },
    )
    add(
        "Service",
        name,
        {
            "selector": {"app": name},
            "ports": [
                {"port": p, "targetPort": p, "name": "p" + str(p)} for p in ports
            ],
        },
    )
add("ServiceAccount", "banking-observer")
add(
    "ClusterRole",
    "banking-observer",
    rules=[
        {
            "apiGroups": [""],
            "resources": ["pods", "pods/log", "namespaces"],
            "verbs": ["get", "list", "watch"],
        }
    ],
)
add(
    "ClusterRoleBinding",
    "banking-observer",
    roleRef={
        "apiGroup": "rbac.authorization.k8s.io",
        "kind": "ClusterRole",
        "name": "banking-observer",
    },
    subjects=[
        {
            "kind": "ServiceAccount",
            "name": "banking-observer",
            "namespace": "observability",
        }
    ],
)
rendered = yaml.safe_dump_all(docs, sort_keys=False)
# Values apply to every claim; default StorageClass remains usable without an override.
rendered = rendered.replace(
    "  accessModes:\n",
    "  {{- if .Values.storageClass }}\n  storageClassName: {{ .Values.storageClass | quote }}\n  {{- end }}\n  accessModes:\n",
)
(DEST / "templates/stack.yaml").write_text(rendered, encoding="utf-8")
print("Generated monitoring chart and Grafana dashboard")
