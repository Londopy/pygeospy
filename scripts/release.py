#!/usr/bin/env python3
"""
Cut a release: move [Unreleased] into a dated section and sync the version.

`patchnotes bump` handles CHANGELOG.md, but the version also lives in
pyproject.toml and pygeospy/__init__.py. CI fails the build when they disagree
(see the `changelog` job), so this script updates all three together.

    python scripts/release.py 0.2.2
    python scripts/release.py 0.2.2 --dry-run

Then review the diff, commit, and tag:

    git commit -am "release: v0.2.2"
    git tag v0.2.2 && git push && git push --tags
"""
from __future__ import annotations

import argparse
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+].+)?$")


def replace_once(path: pathlib.Path, pattern: str, replacement: str) -> str:
    text = path.read_text(encoding="utf-8")
    new_text, count = re.subn(pattern, replacement, text, count=1, flags=re.M)
    if count != 1:
        raise SystemExit(f"error: expected exactly one match for {pattern!r} in {path.name}")
    path.write_text(new_text, encoding="utf-8")
    return new_text


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("version", help="new version, e.g. 0.2.2")
    ap.add_argument("--dry-run", action="store_true", help="show what would change")
    args = ap.parse_args()

    version = args.version.lstrip("v")
    if not SEMVER.match(version):
        raise SystemExit(f"error: {version!r} is not a semantic version (expected X.Y.Z)")

    if shutil.which("patchnotes") is None:
        raise SystemExit("error: patchnotes not found — pip install patchnotes")

    changelog = ROOT / "CHANGELOG.md"
    pyproject = ROOT / "pyproject.toml"
    init_py = ROOT / "pygeospy" / "__init__.py"

    # Refuse to release on top of a broken changelog.
    subprocess.run(
        ["patchnotes", str(changelog), "validate", "--strict"], check=True, cwd=ROOT
    )

    if args.dry_run:
        print(f"would bump CHANGELOG.md -> [{version}]")
        print(f"would set version = \"{version}\" in pyproject.toml")
        print(f"would set __version__ = \"{version}\" in pygeospy/__init__.py")
        return 0

    # patchnotes refuses to bump an empty [Unreleased] or a duplicate version,
    # so a bad release attempt stops here rather than half-applying.
    subprocess.run(["patchnotes", str(changelog), "bump", version], check=True, cwd=ROOT)

    replace_once(pyproject, r'^version(\s*)= ".*"$', rf'version\g<1>= "{version}"')
    replace_once(init_py, r'^__version__ = ".*"$', f'__version__ = "{version}"')

    print(f"\nReleased {version} in CHANGELOG.md, pyproject.toml, pygeospy/__init__.py")
    print("Next:")
    print("  git diff                       # review")
    print(f'  git commit -am "release: v{version}"')
    print(f"  git tag v{version} && git push && git push --tags")
    return 0


if __name__ == "__main__":
    sys.exit(main())
