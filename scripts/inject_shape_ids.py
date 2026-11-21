#!/usr/bin/env python3
# Appends a UUIDv7 suffix to the bare `@id` of every SHACL shape in the
# `hasShape` field of a term.
#
# A shape is identified by the IRI of the term that declares it, a `#`, and a
# slug, like terms are identified by a slug and a UUIDv7 suffix:
#
#   before: <term IRI>#goal-allocation
#   after:  <term IRI>#goal-allocation-018f1a2b3c4d5e6f   (16 hex chars from UUIDv7)
#
# A shape is considered already processed if its fragment ends with a 16-char
# hex suffix, so running the script again changes nothing. Shapes without an
# `@id` are reported on stderr and left alone. An `@id` that is not the term's
# own IRI plus a fragment, or a fragment used twice in one term, is an error.
#
# Run this script after inject_ids.py and before inject_dates.py in the CI
# pipeline. Only term files that actually change are written back to disk.

import json
import re
import sys
from pathlib import Path

from uuid_extensions import uuid7

TERMS_DIR = Path("terms")

# Matches a fragment that already ends with a 16-char hex suffix
UUID_SUFFIX_RE = re.compile(r"-[0-9a-f]{16}$")


def generate_suffix() -> str:
    """Return the first 16 hex characters of a UUIDv7 (without hyphens)."""
    raw = str(uuid7()).replace("-", "")
    return raw[:16]


def main() -> int:
    updated = 0

    for file_path in sorted(TERMS_DIR.glob("*.json")):
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue  # let validate_glossary.py report parse errors

        shapes = data.get("hasShape")
        if not shapes:
            continue

        term_iri = data.get("@id")
        if not term_iri:
            continue  # inject_ids.py sets it

        prefix = term_iri + "#"
        seen: set[str] = set()
        changed = False

        for position, shape in enumerate(shapes, start=1):
            shape_id = shape.get("@id")
            if shape_id is None:
                print(f"  ⚠️  {file_path.name}: hasShape[{position}] has no @id", file=sys.stderr)
                continue
            if not shape_id.startswith(prefix) or len(shape_id) == len(prefix):
                print(f"ERROR: {file_path.name}: hasShape[{position}] @id must be {prefix}<slug>")
                return 1

            fragment = shape_id[len(prefix):]
            if not UUID_SUFFIX_RE.search(fragment):
                fragment = f"{fragment}-{generate_suffix()}"
                shape["@id"] = prefix + fragment
                changed = True
                print(f"  {file_path.name}: hasShape[{position}] -> #{fragment}")

            if fragment in seen:
                print(f"ERROR: {file_path.name}: shape #{fragment} is declared twice")
                return 1
            seen.add(fragment)

        if changed:
            file_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            updated += 1

    print(f"\nDone — {updated} file(s) updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
