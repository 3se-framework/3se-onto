#!/usr/bin/env python3
# Rewrites JSON files that are missing an `id` field,
# injecting the id derived from the filename.
# Run before validate.py in the CI pipeline.

import json
import sys
from pathlib import Path

DIRS = ["terms", "references"]


def main() -> int:
    injected = 0

    for dir_name in DIRS:
        data_dir = Path(dir_name)
        if not data_dir.exists():
            continue

        for file_path in sorted(data_dir.glob("*.json")):
            expected_id = file_path.stem

            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue  # let validate.py report parse errors

            current_id = data.get("id")

            if current_id == expected_id:
                continue  # already correct, nothing to do

            if current_id is None:
                data = {"id": expected_id, **data}  # keep id as first key
                print(f"  injected id \"{expected_id}\" into {dir_name}/{file_path.name}")
            else:
                data["id"] = expected_id
                print(f"  corrected id \"{current_id}\" → \"{expected_id}\" in {dir_name}/{file_path.name}")

            file_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            injected += 1

    print(f"\nDone — {injected} file(s) updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
