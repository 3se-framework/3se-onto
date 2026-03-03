#!/usr/bin/env python3
# Sets `contributors` field on JSON entries based on git history.
#
# - Lists all GitHub handles who ever committed the file
# - The creator (first commit author) is always listed first
# - Existing contributors are never duplicated (idempotent)
#
# Requires git to be available in PATH and the script to run inside the repository.

import json
import subprocess
import sys
from pathlib import Path

DIRS = ["terms", "references"]


def git_handles(file_path: Path) -> list[str]:
    """Return all GitHub handles who committed the file, creator first."""
    # Newest-first log of all authors
    cmd = ["git", "log", "--format=%an", "--follow", "--", str(file_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    lines = result.stdout.strip().splitlines()
    if not lines:
        return []

    # Convert names to handles: lowercase, spaces to hyphens
    def to_handle(name: str) -> str:
        return "@" + name.strip().lower().replace(" ", "-")

    all_authors = [to_handle(l) for l in lines if l.strip()]

    # Creator is the last entry (oldest commit), move to front then deduplicate
    creator = all_authors[-1]
    rest = [a for a in all_authors[:-1] if a != creator]

    # Deduplicate while preserving order
    seen = set()
    ordered = []
    for handle in [creator] + rest:
        if handle not in seen:
            seen.add(handle)
            ordered.append(handle)

    return ordered


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

            git_contributors = git_handles(file_path)
            if not git_contributors:
                continue  # untracked file, skip

            existing = data.get("contributors", [])
            existing_set = set(existing)

            # Append only new contributors; creator-first order comes from git_handles
            new_entries = [h for h in git_contributors if h not in existing_set]
            if not new_entries:
                continue

            # Merge: existing list is kept as-is, new ones appended
            # But if contributors was empty, respect creator-first ordering
            if not existing:
                data["contributors"] = git_contributors
            else:
                data["contributors"] = existing + new_entries

            for handle in new_entries:
                print(f"  added contributor '{handle}' to {dir_name}/{file_path.name}")

            file_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            updated_count += 1

    print(f"\nDone — {updated_count} file(s) updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())