"""Validate native runtime and model manifests before packaging."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.artifact_manifest import ManifestError, verify_manifest


MANIFESTS = (
    ROOT / "manifests" / "whisper-runtime.windows-x64.json",
    ROOT / "manifests" / "models.json",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--release",
        action="store_true",
        help="Require verified, non-empty release-ready manifests.",
    )
    args = parser.parse_args()

    try:
        for manifest in MANIFESTS:
            verify_manifest(
                manifest,
                root=ROOT,
                require_release_ready=args.release,
            )
            print(f"Verified {manifest.relative_to(ROOT)}")
    except ManifestError as exc:
        print(f"Artifact manifest validation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
