#!/usr/bin/env python3
# Resolves bare slugs in term URI fields to their full @id URIs.
#
# After inject_uuids.py renames files and assigns @id URIs, a term written
# before a UUID was known may still contain a bare slug instead of a full URI
# in any of its relation or reference fields.
#
# Fields resolved against the TERMS index (terms/):
#   broader, narrower, related, semanticRelation   (array of conceptRef)
#   exactMatch, closeMatch, broadMatch,            (array of plain URI strings)
#   narrowMatch, relatedMatch
#   superseded_by                                  (scalar)
#
# Fields resolved against the REFERENCES index (references/):
#   isReferencedBy                                 (array of plain URI strings)
#
# Fields left untouched (external scheme IRIs):
#   in_scheme, top_concept_of
#
# Resolution rules (applied per value):
#   1. Value is already a valid absolute URI         → keep as-is
#   2. Value matches exactly one file stem           → replace with its @id URI
#   3. Value is a prefix of exactly one stem         → replace with its @id URI
#   4. Value matches zero or multiple entries        → raise an error and abort
#
# Run this script after inject_uuids.py and before validate_glossary.py.

import json
import re
import sys
from pathlib import Path

# Base IRIs must match the @base declared in each JSON-LD context file.
BASE_IRIS: dict[str, str] = {
    "terms": "https://github.com/3se-framework/3se-onto/terms/",
    "references": "https://github.com/3se-framework/3se-onto/references/",
}

TERMS_DIR = Path("terms")
REFERENCES_DIR = Path("references")

# Fields whose plain-string values (or @id inside a conceptRef object)
# resolve against the TERMS index.
TERM_ARRAY_FIELDS: list[str] = [
    "broader",
    "narrower",
    "related",
    "semanticRelation",
    "exactMatch",
    "closeMatch",
    "broadMatch",
    "narrowMatch",
    "relatedMatch",
]

# Fields whose plain-string values resolve against the REFERENCES index.
REFERENCE_ARRAY_FIELDS: list[str] = [
    "isReferencedBy",
]

# Scalar fields that resolve against the TERMS index.
TERM_SCALAR_FIELDS: list[str] = [
    "superseded_by",
]

# A value is a URI if it starts with a scheme (e.g. https://)
URI_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+\-.]*://")

# Matches a full stem that already has a UUID suffix (used in has_uuid_suffix)
UUID_STEM_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*-[0-9a-f]{16}$")

# Matches only the trailing UUID suffix (used in stem_matches_slug to strip it)
UUID_SUFFIX_RE = re.compile(r"-[0-9a-f]{16}$")


def is_uri(value: str) -> bool:
    return bool(URI_RE.match(value))


def has_uuid_suffix(stem: str) -> bool:
    return bool(UUID_STEM_RE.match(stem))


def build_index(directory: Path) -> dict[str, str]:
    """
    Return a mapping of file stem -> @id URI for all JSON files in a directory.
    Falls back to deriving the URI from BASE_IRIS if @id is absent.
    """
    index: dict[str, str] = {}
    if not directory.exists():
        return index
    dir_key = directory.name  # "terms" or "references"
    base_iri = BASE_IRIS.get(dir_key, "")
    for file_path in directory.glob("*.json"):
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue  # let validate_glossary.py report parse errors
        uri = data.get("@id") or (base_iri + file_path.stem)
        index[file_path.stem] = uri
    return index


def stem_matches_slug(stem: str, slug: str) -> bool:
    """
    Return True if `stem` is either:
      - exactly equal to `slug` (slug already includes the UUID suffix), or
      - equal to `slug` + "-" + 16 hex chars (UUID suffix not yet in slug).
    This prevents a slug like "ireb-cpre-glossary" from falsely matching
    "ireb-cpre-glossary-amendment-069a..." which merely starts with the same prefix.
    """
    if stem == slug:
        return True
    # Strip the trailing UUID suffix from the stem and compare to the slug
    stripped = UUID_SUFFIX_RE.sub("", stem)
    return stripped == slug


def resolve_slug(
        slug: str,
        index: dict[str, str],
        field: str,
        file_name: str,
) -> str:
    """
    Resolve a bare slug to its full @id URI using the given index.

    Matching strategy:
      1. Exact match against a known stem (slug already contains the UUID suffix).
      2. UUID-suffix match: slug equals a stem with its trailing UUID suffix removed
         (the normal case — UUID was not yet known when the file was authored).
    Exits with an error on ambiguous or unresolvable slugs.
    """
    # 1. Exact match
    if slug in index:
        uri = index[slug]
        if uri != slug:
            print(f"  [{file_name}] {field}: resolved \"{slug}\" -> \"{uri}\"")
        return uri

    # 2. UUID-suffix match
    matches = {stem: uri for stem, uri in index.items() if stem_matches_slug(stem, slug)}

    if len(matches) == 1:
        resolved_stem, uri = next(iter(matches.items()))
        print(f"  [{file_name}] {field}: resolved \"{slug}\" -> \"{uri}\"")
        return uri

    if len(matches) == 0:
        print(
            f"\n❌ Error in {file_name}: "
            f"{field} value \"{slug}\" is neither a valid URI "
            f"nor a resolvable slug.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Multiple matches — ambiguous (two entries share the same base name)
    candidates = ", ".join(f'"{s}"' for s in sorted(matches.keys()))
    print(
        f"\n❌ Error in {file_name}: "
        f"{field} value \"{slug}\" is ambiguous — "
        f"it matches multiple entries: {candidates}",
        file=sys.stderr,
    )
    sys.exit(1)


def resolve_value(
        value: str,
        index: dict[str, str],
        field: str,
        file_name: str,
) -> str:
    """Resolve a single string value: no-op if already a URI, else resolve slug."""
    if is_uri(value):
        return value
    return resolve_slug(value, index, field, file_name)


def process_array_field(
        data: dict,
        field: str,
        index: dict[str, str],
        file_name: str,
) -> bool:
    """
    Resolve all slugs in an array field in-place.
    Items may be plain strings (URI or slug) or conceptRef objects {"@id": ...}.
    Returns True if any value was changed.
    """
    items = data.get(field)
    if not items:
        return False

    resolved: list = []
    changed = False

    for item in items:
        if isinstance(item, str):
            new_value = resolve_value(item, index, field, file_name)
            resolved.append(new_value)
            if new_value != item:
                changed = True
        elif isinstance(item, dict):
            # conceptRef object — resolve the @id key
            old_id = item.get("@id", "")
            new_id = resolve_value(old_id, index, field, file_name) if old_id else old_id
            if new_id != old_id:
                resolved.append({**item, "@id": new_id})
                changed = True
            else:
                resolved.append(item)
        else:
            resolved.append(item)  # unexpected type, leave untouched

    if changed:
        data[field] = resolved
    return changed


def process_scalar_field(
        data: dict,
        field: str,
        index: dict[str, str],
        file_name: str,
) -> bool:
    """
    Resolve a slug in a scalar URI field in-place.
    Returns True if the value was changed.
    """
    value = data.get(field)
    if not value or not isinstance(value, str):
        return False
    new_value = resolve_value(value, index, field, file_name)
    if new_value != value:
        data[field] = new_value
        return True
    return False


def process_terms(
        terms_dir: Path,
        term_index: dict[str, str],
        ref_index: dict[str, str],
) -> int:
    """
    Walk all term files and resolve bare slugs in every URI field.
    Returns the count of files updated.
    """
    updated_count = 0

    for file_path in sorted(terms_dir.glob("*.json")):
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue  # let validate_glossary.py report parse errors

        changed = False

        # Array fields -> terms index
        for field in TERM_ARRAY_FIELDS:
            if process_array_field(data, field, term_index, file_path.name):
                changed = True

        # Array fields -> references index
        for field in REFERENCE_ARRAY_FIELDS:
            if process_array_field(data, field, ref_index, file_path.name):
                changed = True

        # Scalar fields -> terms index
        for field in TERM_SCALAR_FIELDS:
            if process_scalar_field(data, field, term_index, file_path.name):
                changed = True

        if changed:
            file_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            updated_count += 1

    return updated_count


def main() -> int:
    term_index = build_index(TERMS_DIR)
    ref_index = build_index(REFERENCES_DIR)

    if not term_index and not ref_index:
        print("⚠️  No entries found in terms/ or references/ — nothing to resolve.")
        return 0

    if not TERMS_DIR.exists():
        print("⚠️  No terms/ directory found — nothing to resolve.")
        return 0

    updated = process_terms(TERMS_DIR, term_index, ref_index)
    print(f"\nDone — {updated} file(s) updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
