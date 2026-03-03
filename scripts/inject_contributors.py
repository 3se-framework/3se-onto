#!/usr/bin/env python3
# Sets `contributors` field on JSON entries based on git history.
#
# - Lists all GitHub handles who ever committed the file
# - The creator (first commit author) is always listed first
# - Existing contributors are never duplicated (idempotent)
#
# Requires git to be available in PATH and the script to run inside the repository.

import json
import re
import subprocess
import sys
from pathlib import Path

DIRS = ["terms", "references"]

# Matches a stem that ends with a 13-char hex UUID suffix
UUID_SUFFIX_RE = re.compile(r"^(.*)-[0-9a-f]{13}$")


def git_log_authors(file_path: Path) -> list[str]:
    """Return git log author lines for a given path, newest first."""
    cmd = ["git", "log", "--format=%an", "--follow", "--", str(file_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout.strip().splitlines()


def git_handles(file_path: Path) -> list[str]:
    """Return all GitHub handles who committed the file, creator first.
    Falls back to the pre-UUID filename if the current path has no history yet."""

    lines = git_log_authors(file_path)

    # Fallback: strip UUID suffix and retry with the original filename
    if not lines:
        match = UUID_SUFFIX_RE.match(file_path.stem)
        if match:
            original = file_path.with_name(f"{match.group(1)}.json")
            lines = git_log_authors(original)

    if not lines:
        return []

    def to_handle(name: str) -> str:
        return "@" + name.strip().lower().replace(" ", "-")

    all_authors = [to_handle(l) for l in lines if l.strip()]

    # Creator is the last entry (oldest commit), move to front then deduplicate
    creator = all_authors[-1]
    rest = [a for a in all_authors[:-1] if a != creator]

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
                continue

            git_contributors = git_handles(file_path)
            if not git_contributors:
                continue  # untracked file, skip

            existing = data.get("contributors", [])
            existing_set = set(existing)

            new_entries = [h for h in git_contributors if h not in existing_set]
            if not new_entries:
                continue

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
