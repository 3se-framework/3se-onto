#!/usr/bin/env python3

import json
import re
import sys
from pathlib import Path
import jsonschema
from jsonschema import validate, Draft202012Validator

DIRS = {
    "terms": {"dir": "terms", "schema": "schemas/term.schema.json"},
    "references": {"dir": "references", "schema": "schemas/reference.schema.json"},
    "properties": {"dir": "properties", "schema": "schemas/property.schema.json"},
}

TERM_BASE_IRI = "https://www.3se.info/3se-onto/terms/"
REFERENCE_BASE_IRI = "https://www.3se.info/3se-onto/references/"
PROPERTY_BASE_IRI = "https://www.3se.info/3se-onto/properties/"

BASE_IRIS = {
    "terms": TERM_BASE_IRI,
    "references": REFERENCE_BASE_IRI,
    "properties": PROPERTY_BASE_IRI,
}


def load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"  ✗ {path.name}: invalid JSON — {e}")
        return None


def collect_reference_uris(data_dir: Path) -> set[str]:
    """Return the set of all @id URIs declared in the references directory."""
    uris: set[str] = set()
    if not data_dir.exists():
        return uris
    for file_path in data_dir.glob("*.json"):
        data = load_json(file_path)
        if data is None:
            continue
        # Accept @id if present, otherwise derive from filename stem as fallback
        uri = data.get("@id") or (REFERENCE_BASE_IRI + file_path.stem)
        uris.add(uri)
    return uris


UUID_SUFFIX_RE = re.compile(r"-[0-9a-f]{16}$")
DOUBLE_UUID_RE = re.compile(r"-[0-9a-f]{16}-[0-9a-f]{16}$")
SE3_STEM_RE = re.compile(r"-3se$")


def stem_to_concept_name(stem: str) -> str:
    """
    Derive the expected concept name from a 3SE file stem.
    e.g. "enabling-physical-element-3se-069b9d2c8d5375f6"
      -> strip UUID suffix  -> "enabling-physical-element-3se"
      -> strip "-3se" suffix -> "enabling-physical-element"
      -> replace hyphens    -> "enabling physical element"
    """
    s = UUID_SUFFIX_RE.sub("", stem)
    s = SE3_STEM_RE.sub("", s)
    return s.replace("-", " ").lower()


def _words_match(title_words: list[str], stem_words: list[str]) -> bool:
    """
    Return True if stem_words is a word-level prefix match of title_words,
    where each stem word may be an abbreviation (prefix) of the corresponding
    title word.

    Examples:
      ["stakeholder", "requirements", "analysis"] vs ["stakeholder", "req", "analysis"]
        -> True  ("req" is a prefix of "requirements")
      ["enabling", "physical", "element"] vs ["enabling", "physical", "element"]
        -> True  (exact match)
      ["system", "function"] vs ["system", "functional"]
        -> False ("function" is not a prefix of "functional" — it is the other
                  way around; the stem word must be the shorter one)

    The match is anchored to the start: stem_words must not be longer than
    title_words, and every stem word must be a prefix of its paired title word.
    """
    if len(stem_words) > len(title_words):
        return False
    return all(
        t_word.startswith(s_word)
        for s_word, t_word in zip(stem_words, title_words)
    )


def validate_title_vs_stem(data: dict, stem: str) -> list[str]:
    """
    Check that the concept name in the title is consistent with the concept
    name derived from the file stem. Only applies to 3SE terms (title ending
    with '- 3SE') where the naming convention is strictly enforced.

    Also detects double UUID suffixes in the stem, which should never occur.

    Matching rules (applied in order, first match wins):
      1. String-prefix match: title_concept.startswith(stem_concept)
         e.g. stem "enabling physical element" matches title "enabling physical element"
      2. Word-level abbreviation match: each stem word is a prefix of the
         corresponding title word.
         e.g. stem "stakeholder req analysis" matches title
         "stakeholder requirements analysis" because "req" is a prefix of
         "requirements".

    Returns a list of error messages (empty if consistent).
    """
    errors: list[str] = []
    title = data.get("title", "")
    if not title.endswith("- 3SE"):
        return errors

    # Check for double UUID suffix
    if DOUBLE_UUID_RE.search(stem):
        errors.append(
            f"stem \"{stem}\" contains two UUID suffixes — "
            f"only one is expected; please rename the file"
        )
        return errors  # no point checking title consistency on a malformed stem

    title_concept = title.split(" - ", maxsplit=1)[0].strip().lower()
    # Normalise hyphens to spaces in the title concept to match stem format
    # (e.g. "Non-functional" -> "non functional")
    title_concept = title_concept.replace("-", " ")
    stem_concept = stem_to_concept_name(stem)

    if not stem_concept:
        return errors

    # Rule 1: plain string-prefix match (covers exact and trailing-word cases)
    if title_concept.startswith(stem_concept):
        return errors

    # Rule 2: word-level abbreviation match — each stem word may be a prefix
    # of the corresponding title word (e.g. "req" matches "requirements")
    if _words_match(title_concept.split(), stem_concept.split()):
        return errors

    errors.append(
        f"title concept name \"{title_concept}\" does not match "
        f"stem concept name \"{stem_concept}\" — "
        f"expected title to start with \"{stem_concept.title()}\""
    )

    return errors


def _camel_to_kebab(name: str) -> str:
    """
    Convert a camelCase or PascalCase identifier to kebab-case.
    e.g. "isAccountableFor" -> "is-accountable-for"
         "wasAssociatedWith" -> "was-associated-with"
    """
    # Insert a hyphen before every uppercase letter that follows a lowercase letter
    # or before an uppercase letter that is followed by a lowercase letter (handles
    # sequences like "XMLParser" -> "xml-parser", though not expected here).
    s = re.sub(r"([a-z])([A-Z])", r"\1-\2", name)
    return s.lower()


def validate_property_title_vs_stem(data: dict, stem: str) -> list[str]:
    """
    Check that the concept name in a property title is consistent with the
    concept name derived from the file stem.  Only applies to 3SE properties
    (title ending with '- 3SE') where the naming convention is strictly
    enforced.

    Property titles use camelCase (e.g. "isAccountableFor - 3SE") while stems
    use kebab-case (e.g. "is-accountable-for-3se-<uuid>").  Both sides are
    normalised to kebab-case before comparison.

    Also detects double UUID suffixes in the stem.
    Returns a list of error messages (empty if consistent).
    """
    errors: list[str] = []
    title = data.get("title", "")
    if not title.endswith("- 3SE"):
        return errors

    if DOUBLE_UUID_RE.search(stem):
        errors.append(
            f"stem \"{stem}\" contains two UUID suffixes — "
            f"only one is expected; please rename the file"
        )
        return errors

    # Derive expected kebab-case name from title: take the part before " - 3SE"
    # and convert camelCase to kebab-case.
    title_concept_camel = title.split(" - ", maxsplit=1)[0].strip()
    title_concept_kebab = _camel_to_kebab(title_concept_camel)

    # Derive expected kebab-case name from stem: strip UUID suffix and "-3se"
    stem_concept = UUID_SUFFIX_RE.sub("", stem)
    stem_concept = SE3_STEM_RE.sub("", stem_concept)

    if not stem_concept:
        return errors

    if not stem_concept.startswith(title_concept_kebab):
        errors.append(
            f"title concept name \"{title_concept_camel}\" (kebab: \"{title_concept_kebab}\") "
            f"does not match stem concept name \"{stem_concept}\" — "
            f"expected stem to start with \"{title_concept_kebab}\""
        )
    return errors


def validate_is_referenced_by(
        data: dict,
        file_name: str,
        known_reference_uris: set[str],
) -> list[str]:
    """
    Check that every URI in isReferencedBy resolves to a known reference entry.
    Returns a list of error messages (empty if all are valid).
    """
    errors: list[str] = []
    is_referenced_by = data.get("isReferencedBy")
    if not is_referenced_by:
        return errors

    for uri in is_referenced_by:
        if uri not in known_reference_uris:
            errors.append(
                f"isReferencedBy: URI \"{uri}\" does not match any known reference entry"
            )
    return errors


def validate_id_base_iri(
        data: dict,
        file_name: str,
        type_name: str,
) -> list[str]:
    """
    Check that @id, if present, starts with the expected base IRI for
    the entry's folder type (terms, references, or properties).
    """
    errors: list[str] = []
    entry_id = data.get("@id")
    if not entry_id:
        return errors
    expected_base = BASE_IRIS.get(type_name)
    if expected_base and not entry_id.startswith(expected_base):
        errors.append(
            f"@id \"{entry_id}\" does not start with the expected "
            f"base IRI \"{expected_base}\" for folder '{type_name}/'"
        )
    return errors


def collect_cited_reference_uris(terms_dir: Path) -> set[str]:
    """Return the set of all reference URIs cited by at least one term."""
    cited: set[str] = set()
    if not terms_dir.exists():
        return cited
    for file_path in terms_dir.glob("*.json"):
        data = load_json(file_path)
        if data is None:
            continue
        for uri in data.get("isReferencedBy", []):
            cited.add(uri)
    return cited


SKOS_RELATION_FIELDS = [
    "broader", "narrower", "related",
    "exactMatch", "closeMatch", "broadMatch", "narrowMatch", "relatedMatch",
]

BREAKDOWN_STEM_RE = re.compile(r"-breakdown-structure-3se(?:-[0-9a-f]{16})?$")


def validate_breakdown_structure(
        data: dict,
        file_name: str,
        terms_index: dict[str, dict],
) -> list[str]:
    """
    For breakdown structure terms: verify that at least one of the related
    concepts declares an isComposedOf relation (composition is mandatory),
    and that every related concept declares at least one structural relation
    (isComposedOf).
    Returns a list of error messages.
    """
    errors: list[str] = []
    term_id = data.get("@id", file_name)

    # Detect breakdown structure by @id stem
    stem = term_id.rstrip("/").rsplit("/", 1)[-1]
    if not BREAKDOWN_STEM_RE.search(stem):
        return errors

    related_uris = data.get("related", [])
    if isinstance(related_uris, str):
        related_uris = [related_uris]

    if not related_uris:
        errors.append("breakdown structure has no related concepts")
        return errors

    any_composed = False
    for uri in related_uris:
        related_data = terms_index.get(uri)
        if related_data is None:
            errors.append(f"related URI \"{uri}\" not found in terms index")
            continue
        if related_data.get("isComposedOf"):
            any_composed = True

    if not any_composed:
        errors.append(
            "no related concept declares isComposedOf — "
            "at least one composition relation is required in a breakdown structure"
        )

    return errors


ANALYSIS_BASE_URI = "https://www.3se.info/3se-onto/terms/analysis-3se-069b5a9129c37ebe"


def validate_breakdown_analysis_link(
        data: dict,
        file_name: str,
        terms_index: dict[str, dict],
) -> list[str]:
    """
    For breakdown structure terms: verify that at least one URI in the
    'related' field points to an analysis term (a term whose subClassOf
    includes analysis-3se-069b5a9129c37ebe).

    Every breakdown structure must be linked to at least one analysis —
    this is the mirror of the check that an analysis must link back to
    a breakdown structure via its own related field.
    Returns a list of error messages.
    """
    errors: list[str] = []
    term_id = data.get("@id", file_name)

    stem = term_id.rstrip("/").rsplit("/", 1)[-1]
    if not BREAKDOWN_STEM_RE.search(stem):
        return errors

    related_uris = data.get("related", [])
    if isinstance(related_uris, str):
        related_uris = [related_uris]

    for uri in related_uris:
        related_data = terms_index.get(uri)
        if related_data is None:
            continue
        subclass_of = related_data.get("subClassOf", [])
        if isinstance(subclass_of, str):
            subclass_of = [subclass_of]
        if ANALYSIS_BASE_URI in subclass_of:
            return errors  # found at least one — valid

    errors.append(
        "breakdown structure has no related analysis — "
        "at least one subclass of analysis-3se must appear in the related field"
    )
    return errors


def collect_unrelated_non_se3_terms(terms_dir: Path) -> list[tuple[str, str]]:
    """
    Return (filename, title) for non-3SE terms that are not referenced by any
    SKOS relation field on any 3SE term.

    Logic:
      1. Collect the @id URI of every non-3SE term.
      2. Scan every 3SE term's SKOS relation fields and collect all referenced URIs.
      3. Return non-3SE terms whose URI does not appear in any 3SE relation.
    """
    if not terms_dir.exists():
        return []

    # Pass 1: collect URI -> (filename, title) for all non-3SE terms
    non_se3: dict[str, tuple[str, str]] = {}  # uri -> (filename, title)
    for file_path in sorted(terms_dir.glob("*.json")):
        data = load_json(file_path)
        if data is None:
            continue
        title = data.get("title", "")
        if title.endswith("- 3SE"):
            continue
        uri = data.get("@id") or (TERM_BASE_IRI + file_path.stem)
        non_se3[uri] = (file_path.name, title)

    # Pass 2: collect all URIs referenced by any SKOS field on any 3SE term
    referenced_uris: set[str] = set()
    for file_path in sorted(terms_dir.glob("*.json")):
        data = load_json(file_path)
        if data is None:
            continue
        if not data.get("title", "").endswith("- 3SE"):
            continue
        for field in SKOS_RELATION_FIELDS:
            values = data.get(field, [])
            if isinstance(values, str):
                values = [values]
            for val in values:
                uri = val if isinstance(val, str) else val.get("@id", "")
                referenced_uris.add(uri)

    # Pass 3: non-3SE terms whose URI is never referenced by a 3SE term
    return [
        (filename, title)
        for uri, (filename, title) in non_se3.items()
        if uri not in referenced_uris
    ]


def main() -> int:
    total_errors = 0

    # Collect all known reference URIs upfront so term validation can use them
    reference_dir = Path(DIRS["references"]["dir"])
    known_reference_uris = collect_reference_uris(reference_dir)

    # Build a URI -> data index for all terms (needed for breakdown validation).
    # Terms are indexed by @id if present, and also by the URI derived from
    # the filename stem — so new terms that have not yet been through
    # inject_uuids.py (no @id) can still be resolved by their stem URI.
    terms_index: dict[str, dict] = {}
    terms_data_dir = Path(DIRS["terms"]["dir"])
    if terms_data_dir.exists():
        for fp in sorted(terms_data_dir.glob("*.json")):
            d = load_json(fp)
            if d is None:
                continue
            # Index by @id if present
            if d.get("@id"):
                terms_index[d["@id"]] = d
            # Always also index by derived stem URI as fallback
            stem_uri = TERM_BASE_IRI + fp.stem
            terms_index.setdefault(stem_uri, d)

    # Build URI -> data index for properties
    properties_index: dict[str, dict] = {}
    properties_data_dir = Path(DIRS["properties"]["dir"])
    if properties_data_dir.exists():
        for fp in sorted(properties_data_dir.glob("*.json")):
            d = load_json(fp)
            if d is None:
                continue
            if d.get("@id"):
                properties_index[d["@id"]] = d
            stem_uri = PROPERTY_BASE_IRI + fp.stem
            properties_index.setdefault(stem_uri, d)

    for type_name, cfg in DIRS.items():
        schema_path = Path(cfg["schema"])
        data_dir = Path(cfg["dir"])

        schema = load_json(schema_path)
        if schema is None:
            print(f"✗ Could not load schema {schema_path}, aborting.")
            return 1

        validator = Draft202012Validator(schema)

        if not data_dir.exists():
            print(f"\n⚠️  Directory '{data_dir}/' not found, skipping.")
            continue

        files = sorted(data_dir.glob("*.json"))
        print(f"\n── Validating {type_name} ({len(files)} files) ──")

        for file_path in files:
            data = load_json(file_path)

            if data is None:
                total_errors += 1
                continue

            file_errors = []

            # Schema validation
            for err in sorted(validator.iter_errors(data), key=lambda e: e.path):
                path = ".".join(str(p) for p in err.absolute_path) or "root"
                file_errors.append(f"{path}: {err.message}")

            # @id base IRI validation (all folder types)
            file_errors.extend(
                validate_id_base_iri(data, file_path.name, type_name)
            )

            # Cross-reference and naming validations (terms only)
            if type_name == "terms":
                file_errors.extend(
                    validate_is_referenced_by(data, file_path.name, known_reference_uris)
                )
                file_errors.extend(
                    validate_title_vs_stem(data, file_path.stem)
                )
                file_errors.extend(
                    validate_breakdown_structure(data, file_path.name, terms_index)
                )
                file_errors.extend(
                    validate_breakdown_analysis_link(data, file_path.name, terms_index)
                )

            # Naming validation (properties only)
            if type_name == "properties":
                file_errors.extend(
                    validate_property_title_vs_stem(data, file_path.stem)
                )

            if file_errors:
                print(f"  ✗ {file_path.name}:")
                for e in file_errors:
                    print(f"      • {e}")
                total_errors += len(file_errors)
            else:
                print(f"  ✓ {file_path.name}")

    # ── Warn about unreferenced references ───────────────────────────────────
    terms_dir = Path(DIRS["terms"]["dir"])
    cited_reference_uris_terms = collect_cited_reference_uris(terms_dir)

    properties_dir = Path(DIRS["properties"]["dir"])
    cited_reference_uris_properties = collect_cited_reference_uris(properties_dir)

    unreferenced = sorted(known_reference_uris - cited_reference_uris_terms - cited_reference_uris_properties)
    if unreferenced:
        print(f"\n── Unreferenced references ({len(unreferenced)}) ──")
        for uri in unreferenced:
            print(f"  ⚠️  {uri}")
    else:
        print("\n── All references are cited by at least one term ✓ ──")

    # ── Warn about non-3SE terms unrelated to any 3SE term ───────────────────
    unrelated_terms = collect_unrelated_non_se3_terms(terms_dir)
    if unrelated_terms:
        print(f"\n── Non-3SE terms with no relation to any 3SE term ({len(unrelated_terms)}) ──")
        for filename, title in unrelated_terms:
            print(f"  ⚠️  {filename}  ({title})")
    else:
        print("\n── All non-3SE terms are related to at least one 3SE term ✓ ──")

    print(f"\n{'─' * 40}")
    if total_errors > 0:
        print(f"\n❌ Validation failed with {total_errors} error(s).")
        return 1

    print("\n✅ All files are valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
