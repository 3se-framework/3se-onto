#!/usr/bin/env python3

import json
import sys
from pathlib import Path
import jsonschema
from jsonschema import validate, Draft202012Validator

DIRS = {
    "terms": {"dir": "terms", "schema": "schemas/term.schema.json"},
    "references": {"dir": "references", "schema": "schemas/reference.schema.json"},
}

REFERENCE_BASE_IRI = "https://www.3se.info/3se-onto/references/"


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

SE3_TERM_BASE_IRI = "https://www.3se.info/3se-onto/terms/"


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
        uri = data.get("@id") or (SE3_TERM_BASE_IRI + file_path.stem)
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

            # Cross-reference validation: isReferencedBy URIs (terms only)
            if type_name == "terms":
                file_errors.extend(
                    validate_is_referenced_by(data, file_path.name, known_reference_uris)
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
    cited_reference_uris = collect_cited_reference_uris(terms_dir)

    unreferenced = sorted(known_reference_uris - cited_reference_uris)
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
