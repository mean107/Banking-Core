"""Validate custom resources against the pinned operators' actual CRD schemas.
Needs network to download Helm charts; does not contact/change a cluster.
"""

import os
from pathlib import Path
import subprocess
import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[1]
helm = os.getenv("HELM", "helm")


def render(*args):
    result = subprocess.run(
        [helm, "template", *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    return [d for d in yaml.safe_load_all(result.stdout) if d]


schemas = {}
for release, chart, repo, version in [
    ("cnpg", "cloudnative-pg", "https://cloudnative-pg.github.io/charts", "0.23.2"),
    ("keda", "keda", "https://kedacore.github.io/charts", "2.17.2"),
]:
    for d in render(
        release, chart, "--repo", repo, "--version", version, "--include-crds"
    ):
        if d.get("kind") == "CustomResourceDefinition":
            for v in d["spec"]["versions"]:
                schemas[
                    (d["spec"]["group"] + "/" + v["name"], d["spec"]["names"]["kind"])
                ] = v["schema"]["openAPIV3Schema"]
count = 0
for chart in ["banking", "platform"]:
    for d in render(chart, f"deploy/charts/{chart}"):
        schema = schemas.get((d["apiVersion"], d["kind"]))
        if schema:
            jsonschema.Draft7Validator(schema).validate(d)
            print(f"{d['kind']} {d['metadata']['name']}: schema valid")
            count += 1
assert count == 2, f"Expected Cluster and ScaledObject, validated {count}"
