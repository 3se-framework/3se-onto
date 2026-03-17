#!/usr/bin/env python3
# Injects bidirectional skos:related links between 3SE terms based on
# concept name mentions in descriptions.
#
# Algorithm:
#   1. For each term, extract the concept name = title before the first " - "
#   2. For every other term, check if the concept name appears in its description
#   3. If yes, add skos:related in both directions (idempotent)
#
# Only 3SE terms (title ending with "- 3SE") are used as link sources,
# but any term whose description mentions a concept name receives a link.
#
# Run this script after inject_uris.py and before validate_glossary.py.

import json
import re
import sys
from pathlib import Path

import inflect

_inflect = inflect.engine()

TERMS_DIR = Path("terms")
BASE_IRI  = "https://www.3se.info/3se-onto/terms/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_index(terms_dir: Path) -> dict[str, tuple[Path, dict]]:
    """Return mapping of stem -> (path, data) for all JSON files."""
    index: dict[str, tuple[Path, dict]] = {}
    if not terms_dir.exists():
        return index
    for fp in sorted(terms_dir.glob("*.json")):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            index[fp.stem] = (fp, data)
        except json.JSONDecodeError:
            continue
    return index


def concept_name(title: str) -> str | None:
    """
    Extract the concept name from a title.
    e.g. "Feature - 3SE"          -> "Feature"
         "System element - 3SE"   -> "System element"
         "Goal analysis - 3SE"    -> "Goal analysis"
    Returns None if the title has no " - " separator.
    """
    parts = title.split(" - ", maxsplit=1)
    if len(parts) < 2:
        return None
    return parts[0].strip()


def name_variants(name: str) -> list[str]:
    """
    Return all forms to search for: singular and plural.
    Handles multi-word concept names (e.g. 'System element' -> also 'System elements').
    """
    variants = {name}
    # Pluralise the last word of the concept name
    words = name.split()
    plural_last = _inflect.plural(words[-1])
    if plural_last and plural_last.lower() != words[-1].lower():
        variants.add(" ".join(words[:-1] + [plural_last]) if len(words) > 1 else plural_last)
    # Also try singular in case the concept name is already plural
    singular_last = _inflect.singular_noun(words[-1])
    if singular_last:
        variants.add(" ".join(words[:-1] + [singular_last]) if len(words) > 1 else singular_last)
    return list(variants)


def name_in_description(name: str, description: str) -> bool:
    """
    Return True if concept name (or its plural/singular form) appears as a
    whole word/phrase in description. Case-insensitive, word-boundary aware.
    """
    for variant in name_variants(name):
        pattern = r"(?<![a-zA-Z0-9])" + re.escape(variant) + r"(?![a-zA-Z0-9])"
        if re.search(pattern, description, re.IGNORECASE):
            return True
    return False


def uri_for_stem(stem: str) -> str:
    return BASE_IRI + stem


def ensure_related(data: dict, uri: str) -> bool:
    """Add uri to data['related'] if not already present. Returns True if changed."""
    existing = data.get("related", [])
    if isinstance(existing, str):
        existing = [existing]
    if uri in existing:
        return False
    data["related"] = existing + [uri]
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    index = load_index(TERMS_DIR)
    if not index:
        print("⚠️  No terms found — nothing to do.")
        return 0

    # Build mapping: stem -> concept_name, only for 3SE terms
    se3_concepts: dict[str, str] = {}
    for stem, (_, data) in index.items():
        title = data.get("title", "")
        if not title.endswith("- 3SE"):
            continue
        name = concept_name(title)
        if name:
            se3_concepts[stem] = name

    # Track all modifications: stem -> data
    changes: dict[str, dict] = {}

    def get_working(stem: str) -> dict:
        """Return the working (possibly modified) copy of a term's data."""
        if stem not in changes:
            changes[stem] = dict(index[stem][1])
        return changes[stem]

    # For each 3SE concept, scan all other terms' descriptions
    for src_stem, name in se3_concepts.items():
        src_uri = uri_for_stem(src_stem)

        for tgt_stem, (_, tgt_data) in index.items():
            if tgt_stem == src_stem:
                continue

            description = tgt_data.get("description", "")
            if not description:
                continue

            if name_in_description(name, description):
                tgt_uri = uri_for_stem(tgt_stem)

                # Add related on source -> target
                src_working = get_working(src_stem)
                if ensure_related(src_working, tgt_uri):
                    print(f"  related: {src_stem} -> {tgt_stem}  ('{name}' found in target)")

                # Add related on target -> source (bidirectional)
                tgt_working = get_working(tgt_stem)
                if ensure_related(tgt_working, src_uri):
                    print(f"  related: {tgt_stem} -> {src_stem}  (reverse)")

    # Warn about standalone 3SE terms — concept name not found in any description
    for src_stem, name in se3_concepts.items():
        src_uri = uri_for_stem(src_stem)
        working = changes.get(src_stem, index[src_stem][1])
        existing_related = working.get("related", [])
        if isinstance(existing_related, str):
            existing_related = [existing_related]
        if not existing_related:
            print(
                f"  ⚠️  standalone: {src_stem}  "
                f"(concept '{name}' not found in any other term's description)",
                file=sys.stderr,
            )

    # Write changed files
    for stem, data in changes.items():
        path, _ = index[stem]
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    print(f"\nDone — {len(changes)} file(s) updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
