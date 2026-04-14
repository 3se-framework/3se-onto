#!/usr/bin/env python3
# Propagates isResponsibleFor targets on role terms derived from the role's
# isAccountableFor targets.
#
# Algorithm
# ─────────
# For every role term R:
#
#   Addition pass
#   ─────────────
#   1. Collect every URI T listed in R's isAccountableFor that is a breakdown
#      structure (BS), a conceptual model (CM), or an analysis (A).
#      Call this set accountable_bca.
#   2. For each such T, gather the URIs in T's own related field that are
#      NOT themselves a BS, CM, or analysis.
#      Call their union the "content terms" derived from isAccountableFor.
#   3. Add each content term to R's isResponsibleFor if not already present.
#
#   Removal pass
#   ────────────
#   For each URI U currently in R's isResponsibleFor:
#   if U does not appear as a related-content term of ANY BS/CM/analysis in
#   R's isAccountableFor, remove U from isResponsibleFor.
#
# Both passes are idempotent: running this script multiple times produces the
# same result. Only role files that actually change are written back to disk.
#
# Run this script after inject_analysis_roles.py and before
# validate_glossary.py.

import json
import sys
from pathlib import Path

TERMS_DIR = Path("terms")
BASE_IRI = "https://www.3se.info/3se-onto/terms/"

ROLE_BASE_URI = BASE_IRI + "role-3se-069c451bef157773"
ANALYSIS_BASE_URI = BASE_IRI + "analysis-3se-069b5a9129c37ebe"
BREAKDOWN_BASE_URI = BASE_IRI + "breakdown-structure-3se-069d166fa9037b67"
CONCEPTUAL_MODEL_BASE_URI = BASE_IRI + "conceptual-model-3se-069d3d5560bf7635"


# ---------------------------------------------------------------------------
# Helpers  (mirrors inject_analysis_roles.py)
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


def ensure_list(value) -> list:
    """Normalise a JSON field that may be absent, a string, or a list."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def is_subclass_of(data: dict, parent_uri: str) -> bool:
    """Return True if data declares subClassOf the given parent URI."""
    val = data.get("subClassOf")
    if not val:
        return False
    uris = [val] if isinstance(val, str) else val
    return parent_uri in uris


def stem_for_uri(uri: str) -> str | None:
    if uri.startswith(BASE_IRI):
        return uri[len(BASE_IRI):]
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    index = load_index(TERMS_DIR)
    if not index:
        print("⚠️  No terms found — nothing to do.")
        return 0

    # ── Build classifier sets ─────────────────────────────────────────────────
    # URIs of every term that is a BS, CM, or analysis — used to filter them
    # out when collecting content terms from a BCA's related field.
    breakdown_uris: set[str] = {
        BASE_IRI + stem
        for stem, (_, data) in index.items()
        if is_subclass_of(data, BREAKDOWN_BASE_URI)
    }
    conceptual_model_uris: set[str] = {
        BASE_IRI + stem
        for stem, (_, data) in index.items()
        if is_subclass_of(data, CONCEPTUAL_MODEL_BASE_URI)
    }
    analysis_uris: set[str] = {
        BASE_IRI + stem
        for stem, (_, data) in index.items()
        if is_subclass_of(data, ANALYSIS_BASE_URI)
    }
    # Combined set of URIs that are BS, CM, or analysis
    bca_uris: set[str] = breakdown_uris | conceptual_model_uris | analysis_uris

    # Build a URI-keyed lookup for all terms
    uri_to_data: dict[str, dict] = {
        BASE_IRI + stem: data
        for stem, (_, data) in index.items()
    }

    # ── Helper: content terms reachable from a single BCA URI ────────────────
    def content_terms_of(bca_uri: str) -> list[str]:
        """
        Return the related URIs of bca_uri that are not themselves BS/CM/analysis.
        Preserves order and deduplicates.
        """
        bca_data = uri_to_data.get(bca_uri)
        if bca_data is None:
            return []
        seen: set[str] = set()
        result: list[str] = []
        for uri in ensure_list(bca_data.get("related")):
            if uri not in bca_uris and uri not in seen:
                seen.add(uri)
                result.append(uri)
        return result

    # ── Process role terms ────────────────────────────────────────────────────
    changes: dict[str, dict] = {}

    def get_working(stem: str) -> dict:
        if stem not in changes:
            changes[stem] = dict(index[stem][1])
        return changes[stem]

    for stem, (_, data) in index.items():
        if not is_subclass_of(data, ROLE_BASE_URI):
            continue

        # Collect the BCA entries from isAccountableFor
        accountable = ensure_list(data.get("isAccountableFor"))
        accountable_bca = [uri for uri in accountable if uri in bca_uris]

        if not accountable_bca:
            # No BS/CM/analysis in isAccountableFor — nothing to derive
            continue

        # Build the full set of content terms derivable from isAccountableFor,
        # preserving a stable insertion order (BCA order, then related order).
        derived_content: list[str] = []
        derived_set: set[str] = set()
        for bca_uri in accountable_bca:
            for uri in content_terms_of(bca_uri):
                if uri not in derived_set:
                    derived_set.add(uri)
                    derived_content.append(uri)

        current_responsible = ensure_list(data.get("isResponsibleFor"))
        current_set = set(current_responsible)

        # ── Addition pass ─────────────────────────────────────────────────────
        additions: list[str] = []
        for uri in derived_content:
            if uri not in current_set:
                additions.append(uri)
                target_stem = stem_for_uri(uri) or uri
                print(f"  + isResponsibleFor: {stem} -> {target_stem}")

        # ── Removal pass ──────────────────────────────────────────────────────
        # A URI in isResponsibleFor is stale if it does not belong to the
        # derived content of any BCA entry in isAccountableFor.
        removals: list[str] = []
        for uri in current_responsible:
            if uri not in derived_set:
                removals.append(uri)
                target_stem = stem_for_uri(uri) or uri
                print(f"  - isResponsibleFor: {stem} -> {target_stem}")

        if additions or removals:
            working = get_working(stem)
            removal_set = set(removals)
            kept = [u for u in current_responsible if u not in removal_set]
            working["isResponsibleFor"] = kept + additions

    # ── Write changed files ───────────────────────────────────────────────────
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
