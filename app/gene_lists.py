"""Bounded, exact-match gene list input for differential-expression exploration."""

from __future__ import annotations

import re

MAX_GENE_LIST_CHARS = 4000
MAX_GENE_LIST_ITEMS = 100
MAX_GENE_ID_CHARS = 200


def parse_gene_ids(value: str) -> tuple[str, ...]:
    """Parse pasted lines, CSV-like commas, or whitespace; preserve ID case and order."""
    if len(value) > MAX_GENE_LIST_CHARS:
        raise ValueError("Gene list must contain at most 4000 characters.")
    if not value.strip():
        return ()
    identifiers = []
    seen = set()
    for identifier in re.split(r"[,;\s]+", value.strip()):
        if not identifier or identifier in seen:
            continue
        if len(identifier) > MAX_GENE_ID_CHARS:
            raise ValueError("Individual gene IDs must contain at most 200 characters.")
        identifiers.append(identifier)
        seen.add(identifier)
        if len(identifiers) > MAX_GENE_LIST_ITEMS:
            raise ValueError("Gene list must contain at most 100 unique IDs.")
    return tuple(identifiers)
