#!/usr/bin/env python3
"""
Guard against source-file corruption.

A stray run of NUL bytes appended to `_rustcore/src/sar.rs` made cargo reject
the file outright ("unknown start of token: \\u{0}"), which silently broke every
Rust build for months while the pure-Python fallback quietly took over.

This check is cheap, has no dependencies, and runs in CI before anything else.
Exits non-zero and lists offenders if any tracked source file contains a NUL
byte or is not valid UTF-8.
"""
from __future__ import annotations

import pathlib
import sys

PATTERNS = (
    "pygeospy/**/*.py",
    "tests/**/*.py",
    "_rustcore/src/**/*.rs",
    "*.toml",
    "*.md",
)


def main() -> int:
    root = pathlib.Path(__file__).resolve().parent.parent
    problems: list[str] = []
    checked = 0

    for pattern in PATTERNS:
        for path in sorted(root.glob(pattern)):
            if not path.is_file():
                continue
            checked += 1
            raw = path.read_bytes()
            rel = path.relative_to(root)

            nuls = raw.count(b"\x00")
            if nuls:
                problems.append(f"{rel}: contains {nuls} NUL byte(s)")
                continue

            try:
                raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                problems.append(f"{rel}: not valid UTF-8 ({exc})")

    if problems:
        print("Source encoding check FAILED:\n", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    print(f"Source encoding check passed ({checked} files, clean UTF-8, no NUL bytes).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
