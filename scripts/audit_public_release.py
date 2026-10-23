#!/usr/bin/env python3
"""Scan source/config files for common accidental disclosure patterns.

This is a review aid, not a proof that code is safe to publish. It intentionally
prints file, line, and category only; it never echoes the matched source text.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

TEXT_SUFFIXES = {
    ".r", ".py", ".sh", ".yaml", ".yml", ".toml", ".json",
    ".env", ".ini", ".cfg", ".sql", ".md", ".rst", ".txt", ".rmd", ".csv", ".tsv",
    ".html", ".js", ".css",
}
EXCLUDED_DIRS = {
    ".git", ".venv", "venv", "renv", "__pycache__", ".pytest_cache",
    "results", "artifacts", "runs",
}
SENSITIVE_DIRS = {"data/raw", "data/private", "data/identifiable"}

PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "personal_or_data_absolute_path",
        re.compile(
            r"""(?ix)
            (?:/Users/[^\s"'\x60]+
            |/home/[^\s"'\x60]+
            |/mnt/[^\s"'\x60]+
            |/Volumes/[^\s"'\x60]+
            |/data/[^\s"'\x60]+
            |/srv/[^\s"'\x60]+
            |[A-Z]:\\(?:Users|data|work|project)\\[^\s"'\x60]+)
            """
        ),
    ),
    (
        "private_ipv4",
        re.compile(
            r"\b(?:10\.(?:\d{1,3}\.){2}\d{1,3}"
            r"|192\.168\.(?:\d{1,3}\.)\d{1,3}"
            r"|172\.(?:1[6-9]|2\d|3[01])\.(?:\d{1,3}\.)\d{1,3})\b"
        ),
    ),
    (
        "internal_hostname",
        re.compile(r"(?i)\b(?:[a-z0-9-]+\.)+(?:local|internal|corp|lan|intra|private)\b"),
    ),
    (
        "email_address",
        re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    ),
    (
        "credential_assignment",
        re.compile(
            r"""(?ix)
            \b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password|passwd|authorization)\b
            \s*(?:=|:|<-|:)\s*['"][^'"]{6,}['"]
            """
        ),
    ),
    (
        "identifying_record_assignment",
        re.compile(
            r"""(?ix)
            \b(?:patient|participant|customer|client|subject|sample)[_-]?
            (?:id|name|code)\s*(?:=|:|<-)\s*['"][^'"]+['"]
            """
        ),
    ),
    (
        "sensitive_identifier_label",
        re.compile(r"(?:患者姓名|身份证号|手机号|病历号|客户名称|客户电话|真实样本编号)"),
    ),
)


def _is_excluded(path: Path) -> bool:
    return any(part in EXCLUDED_DIRS for part in path.parts)


def scan_root(root: Path) -> list[tuple[str, int, str]]:
    """Return (relative_path, line_number, category) findings."""
    findings: list[tuple[str, int, str]] = []
    root = root.resolve()

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if _is_excluded(relative):
            continue

        relative_posix = relative.as_posix()
        # The scanner contains literal detection rules that intentionally resemble
        # sensitive patterns; scanning those rule definitions would self-trigger.
        if relative_posix == "scripts/audit_public_release.py":
            continue

        if any(
            relative_posix == blocked or relative_posix.startswith(blocked + "/")
            for blocked in SENSITIVE_DIRS
        ):
            findings.append((relative_posix, 0, "prohibited_data_directory"))
            continue

        if path.name == ".Rhistory" or (path.name == ".env" and path.stat().st_size > 0):
            findings.append((relative_posix, 0, "local_history_or_secret_file"))
            continue

        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        for line_number, line in enumerate(content.splitlines(), start=1):
            for category, pattern in PATTERNS:
                if pattern.search(line):
                    findings.append((relative_posix, line_number, category))

    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."), help="repository root (default: current directory)")
    args = parser.parse_args(argv)

    if not args.root.is_dir():
        print("ERROR: root must be an existing directory.", file=sys.stderr)
        return 2

    findings = scan_root(args.root)
    if findings:
        for relative_path, line_number, category in findings:
            location = f"{relative_path}:{line_number}" if line_number else relative_path
            print(f"REVIEW {location} [{category}]")
        print(f"Found {len(findings)} possible disclosure(s). Review manually; matched values are not printed.")
        return 1

    print("No configured disclosure patterns found. Manual ownership, license, and data review is still required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
