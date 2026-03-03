#!/usr/bin/env python3
# Renames JSON files that do not yet have a UUIDv7 suffix in their filename,
# and updates the `id` field accordingly.
#
# Filename pattern before: my-term.json
# Filename pattern after:  my-term-018f1a2b3c4d.json  (first 13 hex chars of UUIDv7)
#
# A file is considered already processed if its stem matches:
#   ^[a-z0-9]+(?:-[a-z0-9]+)*-[0-9a-f]{13}$

import json
import re
import subprocess
import sys
from pathlib import Path

from uuid_extensions import uuid7 as uuid7lib

DIRS = ["domains", "terms", "references"]

# Matches a stem that already ends with a 13-char hex suffix
UUID_SUFFIX_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*-[0-9a-f]{13}$")


def has_uuid_suffix(stem: str) -> bool:
    return bool(UUID_SUFFIX_RE.match(stem))


def generate_suffix() -> str:
    """Return the first 16 hex characters of a UUIDv7 (without hyphens)."""
    raw = str(uuid7lib.uuid7()).replace("-", "")
    return raw[:16]


def git_rename(old: Path, new: Path) -> None:
    """Use git mv so the rename is tracked in history."""
    subprocess.run(["git", "mv", str(old), str(new)], check=True)


def main() -> int:
    renamed_count = 0

    for dir_name in DIRS:
        data_dir = Path(dir_name)
        if not data_dir.exists():
            continue

        for file_path in sorted(data_dir.glob("*.json")):
            stem = file_path.stem

            if has_uuid_suffix(stem):
                continue  # already processed, skip

            suffix = generate_suffix()
            new_stem = f"{stem}-{suffix}"
            new_path = file_path.with_name(f"{new_stem}.json")

            # Rename file via git mv
            git_rename(file_path, new_path)
            print(f"  renamed {dir_name}/{file_path.name} → {new_path.name}")

            # Update id field in the file to match new stem
            # (inject_ids.py will also enforce this, but we set it explicitly here
            #  so the file is self-consistent immediately after this script runs)
            try:
                data = json.loads(new_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue  # let validate.py report parse errors

            data["id"] = new_stem
            new_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            renamed_count += 1

    print(f"\nDone — {renamed_count} file(s) renamed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
