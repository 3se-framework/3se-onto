#!/usr/bin/env python3
# Injects and prunes bidirectional skos:related links between 3SE terms
# based on concept name mentions in descriptions.
#
# Algorithm:
#   1. For each 3SE term, extract the concept name = title before the first " - "
#   2. For every OTHER 3SE term, check if the concept name appears in its description
#   3. Compute the full set of justified related links for every 3SE term
#   4. Add missing justified links (idempotent injection)
#   5. Remove existing related links that are no longer justified (pruning)
#   6. Warn about standalone 3SE terms with no justified links
#
# Only links between 3SE terms are managed. Links to external terms
# (e.g. ISO standards, SAFe) are never injected or removed by this script.
#
# Pruning rules:
#   - A related link on a 3SE term is removed if it points to a target whose
#     concept name does not appear in the source's description AND the source's
#     concept name does not appear in the target's description.
#   - Links on non-3SE terms are never touched.
#
# Run this script after inject_uris.py and before validate_glossary.py.

import json
import re
import sys
from pathlib import Path

import inflect

_inflect = inflect.engine()

TERMS_DIR = Path("terms")
BASE_IRI = "https://www.3se.info/3se-onto/terms/"


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
    words = name.split()
    plural_last = _inflect.plural(words[-1])
    if plural_last and plural_last.lower() != words[-1].lower():
        variants.add(" ".join(words[:-1] + [plural_last]) if len(words) > 1 else plural_last)
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


def stem_for_uri(uri: str) -> str | None:
    if uri.startswith(BASE_IRI):
        return uri[len(BASE_IRI):]
    return None


def subclass_uris(data: dict) -> set[str]:
    """Return the set of URIs declared as rdfs:subClassOf on a term."""
    val = data.get("subClassOf")
    if not val:
        return set()
    if isinstance(val, str):
        return {val}
    return set(val)


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

    # ── Step 1: compute justified related links for every term ────────────────
    # justified[stem] = set of URIs that are justified for that stem
    justified: dict[str, set[str]] = {stem: set() for stem in index}

    for src_stem, name in se3_concepts.items():
        src_uri = uri_for_stem(src_stem)
        src_data = index[src_stem][1]
        src_subclass_uris = subclass_uris(src_data)

        for tgt_stem, (_, tgt_data) in index.items():
            if tgt_stem == src_stem:
                continue
            description = tgt_data.get("description", "")
            if not description:
                continue

            if name_in_description(name, description):
                tgt_uri = uri_for_stem(tgt_stem)
                tgt_title = tgt_data.get("title", "")

                # Only justify links to other 3SE terms
                if not tgt_title.endswith("- 3SE"):
                    continue

                # Skip if source is already a subclass of target or vice versa
                tgt_subclass_uris = subclass_uris(tgt_data)
                if tgt_uri in src_subclass_uris or src_uri in tgt_subclass_uris:
                    continue

                # Forward: source 3SE term -> target 3SE term
                justified[src_stem].add(tgt_uri)
                # Reverse: target 3SE term -> source 3SE term
                justified[tgt_stem].add(src_uri)

    # ── Step 2: inject and prune, tracking all changes ────────────────────────
    changes: dict[str, dict] = {}

    def get_working(stem: str) -> dict:
        if stem not in changes:
            changes[stem] = dict(index[stem][1])
        return changes[stem]

    for stem, (_, data) in index.items():
        title = data.get("title", "")

        # Only touch related links on 3SE terms
        if not title.endswith("- 3SE"):
            continue

        existing = data.get("related", [])
        if isinstance(existing, str):
            existing = [existing]
        existing_set = set(existing)
        justified_set = justified[stem]

        to_add = justified_set - existing_set
        to_remove = existing_set - justified_set

        if not to_add and not to_remove:
            continue

        working = get_working(stem)
        # Rebuild related: keep only justified, preserving original order, then append new
        kept = [uri for uri in existing if uri in justified_set]
        added = sorted(justified_set - set(kept))  # sort for determinism
        working["related"] = kept + added

        for uri in sorted(to_add):
            tgt_stem = stem_for_uri(uri) or uri
            print(f"  + related: {stem} -> {tgt_stem}")
        for uri in sorted(to_remove):
            tgt_stem = stem_for_uri(uri) or uri
            print(f"  - removed: {stem} -> {tgt_stem}  (no longer justified)")

    # ── Step 3: warn about standalone 3SE terms ───────────────────────────────
    for stem, name in se3_concepts.items():
        working = changes.get(stem, index[stem][1])
        existing = working.get("related", [])
        if isinstance(existing, str):
            existing = [existing]
        if not existing:
            print(
                f"  ⚠️  standalone: {stem}  "
                f"(concept '{name}' not found in any other term's description)",
                file=sys.stderr,
            )

    # ── Step 4: write changed files ───────────────────────────────────────────
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
