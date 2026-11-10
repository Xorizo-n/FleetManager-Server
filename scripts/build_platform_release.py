"""Build non-secret release assets; invoked only after container tests pass."""
import argparse
import hashlib
import json
import tarfile
from pathlib import Path

import yaml
from alembic.config import Config
from alembic.script import ScriptDirectory

from updater.release import manifest, version


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--backend", required=True)
    parser.add_argument("--frontend", required=True)
    args = parser.parse_args()
    version(args.version)
    root = Path(__file__).resolve().parents[1]
    dest = root / "release-output"
    dest.mkdir(exist_ok=True)
    compose = yaml.safe_load((root / "docker-compose.yml").read_text())
    for name in ("backend", "celery", "celery-beat", "frontend"):
        compose["services"][name].pop("build", None)
        compose["services"][name]["image"] = args.frontend if name == "frontend" else args.backend
    compose["services"]["backend"]["command"] = "uvicorn main:app --host 0.0.0.0 --port 8000"
    config = dest / "compose.json"
    config.write_text(json.dumps(compose, indent=2))
    bundle = dest / "platform.tar.gz"
    with tarfile.open(bundle, "w:gz") as archive:
        archive.add(config, arcname="compose.json")
        archive.add(root / "ansible", arcname="ansible")
    cfg = Config(str(root / "backend/alembic.ini"))
    cfg.set_main_option("script_location", str(root / "backend/alembic"))
    data = manifest({"format": 1, "version": args.version, "commit": args.commit,
                     "schema_revision": ScriptDirectory.from_config(cfg).get_current_head(),
                     "bundle_sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
                     "images": {"backend": args.backend, "frontend": args.frontend}}, args.version)
    (dest / "platform.json").write_text(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
