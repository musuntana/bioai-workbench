"""Read a small, allowlisted subset of the DESeq2 workflow manifest."""

from __future__ import annotations

import csv
import re
from pathlib import Path

_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._+()-]{0,100}$")
_FIELDS = {
    "r_version": "r_version",
    "deseq2_version": "deseq2_version",
    "workflow_version": "workflow_version",
    "bioconductor_version": "bioconductor_version",
}


def read_environment_versions(path: Path) -> dict[str, str]:
    """No raw manifest values or host paths leave the runtime."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024:
        return {}
    try:
        with path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream, delimiter="\t", strict=True)
            if reader.fieldnames != ["key", "value"]:
                return {}
            values: dict[str, str] = {}
            for record in reader:
                key = record.get("key", "")
                value = record.get("value", "")
                if key in _FIELDS and isinstance(value, str) and _VERSION.fullmatch(value):
                    values[_FIELDS[key]] = value
            return values
    except (OSError, UnicodeError, csv.Error):
        return {}
