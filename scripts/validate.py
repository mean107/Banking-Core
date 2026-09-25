"""Read-only local checks; no cluster changes or deployment."""

import os
from pathlib import Path
import subprocess
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]


def run(*cmd):
    subprocess.run(cmd, cwd=ROOT, check=True)


run(sys.executable, "-m", "pytest", "-q")
run(sys.executable, "-m", "compileall", "-q", "backend")
for chart in ["banking", "platform", "observability"]:
    helm = os.getenv("HELM", "helm")
    run(helm, "lint", f"deploy/charts/{chart}")
    result = subprocess.run(
        [helm, "template", chart, f"deploy/charts/{chart}"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    docs = [d for d in yaml.safe_load_all(result.stdout) if d]
    assert all("apiVersion" in d and "kind" in d and "metadata" in d for d in docs)
    print(f"{chart}: {len(docs)} rendered resources parsed")
run("docker", "compose", "config", "--quiet")
