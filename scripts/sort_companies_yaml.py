#!/usr/bin/env python3
"""
Sort and de-duplicate config/companies.yaml.

- Sort alphabetically by casefolded company name
- Remove duplicate (ats, board_token) pairs, keeping the first occurrence
- Remove duplicate names after case/space/punctuation normalization
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "config" / "companies.yaml"


def _norm_name(name: str) -> str:
    return "".join(ch for ch in name.casefold() if ch.isalnum())


def main() -> None:
    data = yaml.safe_load(PATH.read_text(encoding="utf-8"))
    companies: list[dict[str, Any]] = list(data.get("companies") or [])
    # Stable sort by casefolded name
    companies.sort(key=lambda c: str(c.get("name") or "").casefold())
    deduped: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()
    for c in companies:
        name = str(c.get("name") or "").strip()
        if not name:
            continue
        key_name = _norm_name(name)
        ats = str(c.get("ats") or "").casefold()
        token = str(c.get("board_token") or "").casefold().strip()
        key_pair = (ats, token) if token else None
        if key_name in seen_names:
            continue
        if key_pair and key_pair in seen_pairs:
            continue
        seen_names.add(key_name)
        if key_pair:
            seen_pairs.add(key_pair)
        deduped.append(c)
    out = {"companies": deduped}
    PATH.write_text(yaml.safe_dump(out, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"wrote {len(deduped)} companies to {PATH}")


if __name__ == "__main__":
    main()

