#!/usr/bin/env python3
# Sets `created` and `updated` fields on JSON entries based on git history.
#
# - `created`: date of the first commit that introduced the file (set once, never overwritten)
# - `updated`: date of the latest commit that touched the file (refreshed on every run)
#
# Requires git to be available in PATH and the script to run inside the repository.

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

DIRS = ["terms", "references"]


def git_date(file_path: Path, first: bool) -> str | None:
    """Return ISO 8601 date of the first or latest commit touching file_path."""
    cmd = ["git", "log", "--format=%cs"]
    if first:
        cmd += ["--diff-filter=A", "--follow"]
    cmd += ["--", str(file_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    lines = result.stdout.strip().splitlines()
    if not lines:
        return None
    # `git log` is newest-first; last line = oldest commit
    return lines[-1] if first else lines[0]


def today() -> str:
    return date.today().isoformat()


def main() -> int:
    updated_count = 0

    for dir_name in DIRS:
        data_dir = Path(dir_name)
        if not data_dir.exists():
            continue

        for file_path in sorted(data_dir.glob("*.json")):
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue  # let validate.py report parse errors

            changed = False

            # `created`: use oldest git commit date; fall back to today for new files
            if "created" not in data:
                created = git_date(file_path, first=True) or today()
                data["created"] = created
                print(f"  set created='{created}' on {dir_name}/{file_path.name}")
                changed = True

            # `updated`: always refresh to the latest commit date (or today if uncommitted)
            updated = git_date(file_path, first=False) or today()
            if data.get("updated") != updated:
                data["updated"] = updated
                print(f"  set updated='{updated}' on {dir_name}/{file_path.name}")
                changed = True

            if changed:
                file_path.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                updated_count += 1

    print(f"\nDone — {updated_count} file(s) updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
