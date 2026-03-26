#!/usr/bin/env python3
# Resolves bare slugs in term and property URI fields to their full @id URIs.
#
# After inject_uuids.py renames files and assigns @id URIs, a term or property
# written before a UUID was known may still contain a bare slug instead of a
# full URI in any of its relation or reference fields.
#
# Fields resolved against the TERMS index (terms/):
#   broader, narrower, related, semanticRelation  (array of conceptRef)
#   exactMatch, closeMatch, broadMatch,           (array of plain URI strings)
#   narrowMatch, relatedMatch
#   subClassOf, isComposedOf, isRepresentedBy, allocates, canBe
#   superseded_by                                 (scalar)
#
# Fields resolved against the REFERENCES index (references/):
#   isReferencedBy                                (array) — terms AND properties
#
# Fields resolved against the PROPERTIES index (properties/):
#   subPropertyOf                                 (array) — properties only
#
# Fields left untouched (external scheme IRIs):
#   in_scheme, top_concept_of, domain, range
#
# Resolution rules (applied per value):
#   1. Value is an external URI (non-internal scheme)  → keep as-is
#   2. Value is an internal URI already in the index   → keep as-is
#   3. Value is an internal URI missing UUID suffix    → extract slug, resolve
#   4. Value is a bare slug matching exactly one stem  → replace with its @id URI
#   5. Value matches zero or multiple entries          → raise an error and abort
#
# Run this script after inject_uuids.py and before validate_glossary.py.

import json
import re
import sys
from pathlib import Path

# Base IRIs must match the @base declared in each JSON-LD context file.
BASE_IRIS: dict[str, str] = {
    "terms": "https://www.3se.info/3se-onto/terms/",
    "references": "https://www.3se.info/3se-onto/references/",
    "properties": "https://www.3se.info/3se-onto/properties/",
}

TERMS_DIR = Path("terms")
REFERENCES_DIR = Path("references")
PROPERTIES_DIR = Path("properties")

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
    "subClassOf",
    "isComposedOf",
    "isRepresentedBy",
    "allocates",
    "canBe",
    "isResponsibleFor",
    "isAccountableFor",
    "isSupporting"
]

# Fields whose plain-string values resolve against the REFERENCES index.
# Used by both terms and properties.
REFERENCE_ARRAY_FIELDS: list[str] = [
    "isReferencedBy",
]

# Scalar fields that resolve against the TERMS index.
TERM_SCALAR_FIELDS: list[str] = [
    "superseded_by",
]

# Fields whose plain-string values resolve against the PROPERTIES index.
# Used by property entries only.
PROPERTY_ARRAY_FIELDS: list[str] = [
    "subPropertyOf",
]

# A value is a URI if it starts with a scheme (e.g. https://)
URI_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+\-.]*://")


def is_uri(value: str) -> bool:
    return bool(URI_RE.match(value))


def is_internal_uri(value: str) -> bool:
    """Return True if value starts with one of our own base IRIs."""
    return any(value.startswith(base) for base in BASE_IRIS.values())


def uri_to_slug(value: str) -> str:
    """Strip the base IRI prefix to get the bare slug."""
    for base in BASE_IRIS.values():
        if value.startswith(base):
            return value[len(base):]
    return value


def build_index(directory: Path) -> dict[str, str]:
    """
    Return a mapping of stem -> @id URI for all JSON files in a directory.

    For terms/, references/ and properties/ : the stem is the UUID-suffixed filename stem,
    and the @id is derived from it (or read from the file).
    """
    index: dict[str, str] = {}
    if not directory.exists():
        return index
    dir_key = directory.name  # "terms" or "references" or "properties"
    base_iri = BASE_IRIS.get(dir_key, "")
    for file_path in directory.glob("*.json"):
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue  # let validate_glossary.py report parse errors

        uri = data.get("@id") or (base_iri + file_path.stem)
        index[file_path.stem] = uri

    return index


# Matches a full stem that already has a UUID suffix (used in has_uuid_suffix)
UUID_STEM_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*-[0-9a-f]{16}$")

# Matches only the trailing UUID suffix (used in stem_matches_slug to strip it)
UUID_SUFFIX_RE = re.compile(r"-[0-9a-f]{16}$")


def has_uuid_suffix(stem: str) -> bool:
    return bool(UUID_STEM_RE.match(stem))


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
    # Strip the UUID suffix from the stem and compare the remainder to the slug
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
    """Resolve a single string value.
    - External URIs: kept as-is.
    - Internal URIs already present in the index: kept as-is.
    - Internal URIs not in the index (missing UUID suffix): slug-resolved.
    - Bare slugs: slug-resolved.
    """
    if is_uri(value):
        # External URI — leave untouched
        if not is_internal_uri(value):
            return value
        # Internal URI already fully resolved and present in index — leave untouched
        if value in index.values():
            return value
        # Internal URI not yet resolved (missing UUID suffix) — extract slug and resolve
        slug = uri_to_slug(value)
        return resolve_slug(slug, index, field, file_name)

    # Bare slug
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


def process_properties(
        properties_dir: Path,
        prop_index: dict[str, str],
        ref_index: dict[str, str],
) -> int:
    """
    Walk all property files and resolve bare slugs in every URI field.

    Fields resolved:
    - isReferencedBy  → REFERENCES index
    - subPropertyOf   → PROPERTIES index

    Returns the count of files updated.
    """
    updated_count = 0

    for file_path in sorted(properties_dir.glob("*.json")):
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue

        changed = False

        # isReferencedBy → resolved against references
        for field in REFERENCE_ARRAY_FIELDS:
            if process_array_field(data, field, ref_index, file_path.name):
                changed = True

        # subPropertyOf → resolved against properties
        for field in PROPERTY_ARRAY_FIELDS:
            if process_array_field(data, field, prop_index, file_path.name):
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
    prop_index = build_index(PROPERTIES_DIR)

    if not term_index and not ref_index and not prop_index:
        print("⚠️  No entries found in terms/, references/, or properties/ — nothing to resolve.")
        return 0

    total_updated = 0

    if TERMS_DIR.exists():
        updated = process_terms(TERMS_DIR, term_index, ref_index)
        total_updated += updated
    else:
        print("⚠️  No terms/ directory found — skipping term resolution.")

    if PROPERTIES_DIR.exists():
        updated = process_properties(PROPERTIES_DIR, prop_index, ref_index)
        total_updated += updated
    else:
        print("⚠️  No properties/ directory found — skipping property resolution.")

    print(f"\nDone — {total_updated} file(s) updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
