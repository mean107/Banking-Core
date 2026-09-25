"""Update both images atomically after both builds have been published."""

import argparse
from pathlib import Path
import yaml

p = argparse.ArgumentParser()
p.add_argument("--owner", required=True)
p.add_argument("--tag", required=True)
a = p.parse_args()
path = Path(__file__).resolve().parents[1] / "deploy/environments/lab/images.yaml"
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(
    yaml.safe_dump(
        {
            kind: {
                "repository": f"ghcr.io/{a.owner.lower()}/banking-core-{kind}",
                "tag": a.tag,
            }
            for kind in ["backend", "frontend"]
        },
        sort_keys=False,
    ),
    encoding="utf-8",
)
