#!/usr/bin/env python3
# Sets `entryCreated` and `entryModified` fields on JSON entries based on git history.
#
# - `entryCreated`: date of the first commit that introduced the file (set once, never overwritten)
# - `entryModified`: date of the latest commit that touched the file (refreshed on every run)
#
# For files just renamed by inject_uuids.py (not yet committed under their new name),
# git history is retried against the original pre-UUID filename as a fallback.
#
# Requires git to be available in PATH and the script to run inside the repository.

import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

DIRS = ["terms", "references", "properties"]

# Matches the trailing 16-char hex UUID suffix added by inject_uuids.py
UUID_SUFFIX_RE = re.compile(r"-[0-9a-f]{16}$")


def git_log_dates(file_path: Path, first: bool) -> list[str]:
    """Return git log date lines for a given path, newest first."""
    cmd = ["git", "log", "--format=%cs"]
    if first:
        cmd += ["--diff-filter=A", "--follow"]
    cmd += ["--", str(file_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout.strip().splitlines()


def git_date(file_path: Path, first: bool) -> str | None:
    """
    Return ISO 8601 date of the first or latest commit touching file_path.
    Falls back to the pre-UUID filename if the current path has no history yet.
    """
    lines = git_log_dates(file_path, first)

    # Fallback: strip UUID suffix and retry with the original filename
    if not lines:
        match = UUID_SUFFIX_RE.search(file_path.stem)
        if match:
            original = file_path.with_name(
                UUID_SUFFIX_RE.sub("", file_path.stem) + ".json"
            )
            lines = git_log_dates(original, first)

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
                continue  # let validate_glossary.py report parse errors

            changed = False

            # `entryCreated`: use oldest git commit date; fall back to today for new files
            if "entryCreated" not in data:
                created = git_date(file_path, first=True) or today()
                data["entryCreated"] = created
                print(f"  set entryCreated='{created}' on {dir_name}/{file_path.name}")
                changed = True

            # `entryModified`: always refresh to the latest commit date (or today if uncommitted)
            updated = git_date(file_path, first=False) or today()
            if data.get("entryModified") != updated:
                data["entryModified"] = updated
                print(f"  set entryModified='{updated}' on {dir_name}/{file_path.name}")
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
