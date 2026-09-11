#!/usr/bin/env python3
# Promotes statuses of 3SE domains, terms, and properties relative to the
# latest release tag.
#
# Current status  entryModified vs release  Release status  Action
# --------------  ------------------------  --------------  --------
# reviewed        unchanged                 any             approved
# draft           any                       any             reviewed
# any             any                       draft           reviewed
# reviewed        changed                   any             no change
# approved        any                       any             no change
#
# Usage:
#   python scripts/manage_statuses.py [--dry-run] [--release TAG]
#
#   --dry-run     Show what would change without writing any file.
#   --release TAG Use this tag instead of the latest X.Y tag.

import argparse
import json
import subprocess
import sys
from pathlib import Path

DIRS = ["terms", "domains", "properties"]


def latest_release_tag() -> str:
    result = subprocess.run(
        ["git", "tag", "--sort=-version:refname"],
        capture_output=True, text=True, check=True,
    )
    for line in result.stdout.splitlines():
        tag = line.strip()
        parts = tag.split(".")
        if len(parts) == 2 and all(p.isdigit() for p in parts):
            return tag
    sys.exit("No X.Y release tag found in this repository.")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json_from_tag(tag: str, rel_path: str) -> dict | None:
    result = subprocess.run(
        ["git", "show", f"{tag}:{rel_path}"],
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    return json.loads(result.stdout.decode("utf-8-sig"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Promote term/domain/property statuses.")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing.")
    parser.add_argument("--release", metavar="TAG", help="Release tag to compare against.")
    args = parser.parse_args()

    tag = args.release or latest_release_tag()
    print(f"Comparing against release: {tag}\n")

    changed = 0
    skipped = 0

    for folder in DIRS:
        folder_path = Path(folder)
        if not folder_path.is_dir():
            continue
        for json_file in sorted(folder_path.glob("*.json")):
            rel_path = json_file.as_posix()
            current = read_json(json_file)

            current_status = current.get("status", "")
            current_modified = current.get("entryModified", "")

            release_data = read_json_from_tag(tag, rel_path)

            # New file (not in release) — nothing to compare.
            if release_data is None:
                skipped += 1
                continue

            release_status = release_data.get("status", "")
            release_modified = release_data.get("entryModified", "")

            new_status: str | None = None

            if current_status == "reviewed" and current_modified == release_modified:
                # Reviewed and unchanged since the release → approve.
                new_status = "approved"
            elif current_status == "draft":
                # Still draft → promote to reviewed.
                new_status = "reviewed"
            elif release_status == "draft":
                # Was draft at the release (but current is not draft) → promote to reviewed.
                new_status = "reviewed"

            if new_status is None or new_status == current_status:
                continue

            label = json_file.name
            print(f"  {label:<60}  {current_status}  →  {new_status}")

            if not args.dry_run:
                current["status"] = new_status
                write_json(json_file, current)

            changed += 1

    if changed == 0:
        print("No status changes required.")
    else:
        suffix = " (dry run — no files written)" if args.dry_run else ""
        print(f"\n{changed} file(s) updated{suffix}.")

    if skipped:
        print(f"{skipped} new file(s) not present in {tag} were skipped.")


if __name__ == "__main__":
    main()
