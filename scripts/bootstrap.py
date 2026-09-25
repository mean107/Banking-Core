"""Explicit-context lab provisioning; never invoked by validation/CI.
Requires kubectl, Helm 3, 3 schedulable nodes and a default StorageClass.
"""

import argparse
import base64
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--context", required=True, help="Exact kubectl context to provision"
    )
    parser.add_argument(
        "--gitops",
        action="store_true",
        help="Install ArgoCD and register the Git repository applications",
    )
    args = parser.parse_args()
    required = [
        "DB_PASSWORD",
        "REDIS_PASSWORD",
        "RABBITMQ_PASSWORD",
        "GRAFANA_PASSWORD",
    ]
    for key in required:
        value = os.getenv(key, "")
        if len(value) < 12 or not all(c.isalnum() or c in "-_" for c in value):
            raise SystemExit(
                f"{key} must be set to >=12 URL-safe letters/digits/-/_; no secrets are printed"
            )

    def kubectl(*cmd, data=None, capture=False):
        return subprocess.run(
            ["kubectl", "--context", args.context, *cmd],
            input=json.dumps(data) if data else None,
            text=True,
            check=True,
            capture_output=capture,
        )

    def helm(*cmd):
        subprocess.run(
            ["helm", "--kube-context", args.context, *cmd], check=True, cwd=ROOT
        )

    nodes = json.loads(kubectl("get", "nodes", "-o", "json", capture=True).stdout)[
        "items"
    ]
    if len(nodes) < 3:
        raise SystemExit(
            "HA profile requires at least 3 nodes; use Compose for a single-machine demo."
        )
    kubectl("get", "storageclass")
    for ns in [
        "banking",
        "data-postgres",
        "data-redis",
        "messaging",
        "gateway",
        "observability",
        "banking-platform",
    ]:
        kubectl(
            "apply",
            "-f",
            "-",
            data={"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": ns}},
        )

    def secret(ns, name, values, kind="Opaque"):
        # Keep existing credentials unless user explicitly manages rotation elsewhere.
        existing = subprocess.run(
            [
                "kubectl",
                "--context",
                args.context,
                "get",
                "secret",
                name,
                "-n",
                ns,
                "-o",
                "json",
            ],
            capture_output=True,
            text=True,
        )
        if existing.returncode == 0:
            stored = json.loads(existing.stdout).get("data", {})
            if any(
                base64.b64decode(stored.get(k, "")).decode() != v
                for k, v in values.items()
            ):
                raise SystemExit(
                    f"Existing secret {ns}/{name} differs. Use the original credentials or follow an explicit rotation procedure."
                )
            print(f"Keeping existing secret {ns}/{name}")
            return
        kubectl(
            "apply",
            "-f",
            "-",
            data={
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": name, "namespace": ns},
                "type": kind,
                "stringData": values,
            },
        )

    secret(
        "data-postgres",
        "banking-db-auth",
        {"username": "banking", "password": os.environ["DB_PASSWORD"]},
        "kubernetes.io/basic-auth",
    )
    secret("data-redis", "redis-auth", {"password": os.environ["REDIS_PASSWORD"]})
    secret("messaging", "rabbitmq-auth", {"password": os.environ["RABBITMQ_PASSWORD"]})
    secret(
        "observability", "grafana-auth", {"password": os.environ["GRAFANA_PASSWORD"]}
    )
    secret(
        "banking",
        "banking-runtime",
        {
            "DATABASE_URL": f"postgresql+psycopg://banking:{os.environ['DB_PASSWORD']}@banking-db-rw.data-postgres.svc.cluster.local:5432/banking",
            "REDIS_SENTINELS": ",".join(
                f"redis-{i}.redis-headless.data-redis.svc.cluster.local:26379"
                for i in range(3)
            ),
            "REDIS_PASSWORD": os.environ["REDIS_PASSWORD"],
            "RABBITMQ_URL": f"amqp://banking:{os.environ['RABBITMQ_PASSWORD']}@rabbitmq.messaging.svc.cluster.local:5672/",
        },
    )
    for name, url in [
        ("cnpg", "https://cloudnative-pg.github.io/charts"),
        ("kedacore", "https://kedacore.github.io/charts"),
        ("argo", "https://argoproj.github.io/argo-helm"),
    ]:
        helm("repo", "add", name, url, "--force-update")
    helm("repo", "update")
    helm(
        "upgrade",
        "--install",
        "cnpg",
        "cnpg/cloudnative-pg",
        "--version",
        "0.23.2",
        "-n",
        "cnpg-system",
        "--create-namespace",
        "--wait",
        "--timeout",
        "10m",
    )
    helm(
        "upgrade",
        "--install",
        "keda",
        "kedacore/keda",
        "--version",
        "2.17.2",
        "-n",
        "keda",
        "--create-namespace",
        "--wait",
        "--timeout",
        "10m",
    )
    helm(
        "upgrade",
        "--install",
        "banking-platform",
        "deploy/charts/platform",
        "-n",
        "banking-platform",
        "--wait",
        "--timeout",
        "15m",
    )
    kubectl(
        "wait",
        "cluster/banking-db",
        "-n",
        "data-postgres",
        "--for=condition=Ready",
        "--timeout=900s",
    )
    helm(
        "upgrade",
        "--install",
        "banking-observability",
        "deploy/charts/observability",
        "-n",
        "observability",
        "--wait",
        "--timeout",
        "10m",
    )
    if args.gitops:
        helm(
            "upgrade",
            "--install",
            "argocd",
            "argo/argo-cd",
            "--version",
            "7.8.23",
            "-n",
            "argocd",
            "--create-namespace",
            "--wait",
            "--timeout",
            "10m",
        )
        kubectl("apply", "-f", str(ROOT / "deploy/argocd/applications.yaml"))
    else:
        helm(
            "upgrade",
            "--install",
            "banking",
            "deploy/charts/banking",
            "-n",
            "banking",
            "-f",
            "deploy/environments/lab/images.yaml",
            "--wait",
            "--timeout",
            "10m",
        )
    print(
        "Bootstrap complete. Verify workloads and run smoke/load/failover tests from docs/RUNBOOK.md."
    )


if __name__ == "__main__":
    main()
