#!/usr/bin/env python3
# Rewrites JSON files that are missing an `@id` field,
# injecting the @id URI derived from the filename stem and the
# canonical base IRI for each directory.
# Run before validate_glossary.py in the CI pipeline.

import json
import sys
from pathlib import Path

# Base IRIs must match the @base declared in each JSON-LD context file.
BASE_IRIS: dict[str, str] = {
    "terms": "https://github.com/3se-framework/3se-onto/terms/",
    "references": "https://github.com/3se-framework/3se-onto/references/",
}


def expected_uri(dir_name: str, stem: str) -> str:
    return BASE_IRIS[dir_name] + stem


def main() -> int:
    injected = 0

    for dir_name, base_iri in BASE_IRIS.items():
        data_dir = Path(dir_name)
        if not data_dir.exists():
            continue

        for file_path in sorted(data_dir.glob("*.json")):
            stem = file_path.stem
            uri = expected_uri(dir_name, stem)

            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue  # let validate_glossary.py report parse errors

            current = data.get("@id")

            if current == uri:
                continue  # already correct, nothing to do

            if current is None:
                data = {"@id": uri, **data}  # keep @id as first key
                print(f"  injected @id \"{uri}\" into {dir_name}/{file_path.name}")
            else:
                data["@id"] = uri
                print(f"  corrected @id \"{current}\" → \"{uri}\" in {dir_name}/{file_path.name}")

            file_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            injected += 1

    print(f"\nDone — {injected} file(s) updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
