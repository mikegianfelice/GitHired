#!/usr/bin/env python3
import json
from collections import Counter, defaultdict
from pathlib import Path

DATA_PATH = Path("site/api-dataset.json")

def main() -> None:
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    jobs = data.get("jobs") or []
    missing = [j for j in jobs if not j.get("province")]
    print(json.dumps({"total": len(jobs), "null_province": len(missing)}, indent=2))
    # Top 30 patterns by (location, company)
    combo = Counter((str(j.get("location") or j.get("location_raw") or "").strip(), j.get("company")) for j in missing)
    print("\nTop 30 (location, company) with null province:")
    for (loc, co), n in combo.most_common(30):
        print(f"{n:4d}  {loc or '(blank)'}  — {co}")

if __name__ == "__main__":
    main()

