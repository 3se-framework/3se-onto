#!/usr/bin/env python3
# Propagates typed role relations derived from existing role→analysis typed
# relations to the concepts that are linked to each analysis.
#
# Two propagation rules are applied, both using the same relation P
# (isResponsibleFor | isAccountableFor | isSupporting):
#
# Rule 1 — Breakdown structures:
#   If a role R has relation P pointing at an analysis A, and A has a
#   breakdown structure BS in its related field, then R must also have
#   relation P pointing at BS.
#
# Rule 2 — Conceptual models:
#   If a role R has relation P pointing at an analysis A, and A has a
#   conceptual model CM in its related field, then R must also have
#   relation P pointing at CM.
#
# Both rules are idempotent: running this script multiple times produces the
# same result. Only role files that actually change are written back to disk.
#
# Run this script after inject_uris.py and before validate_glossary.py.

import json
import sys
from pathlib import Path

TERMS_DIR = Path("terms")
BASE_IRI = "https://www.3se.info/3se-onto/terms/"

ROLE_BASE_URI = BASE_IRI + "role-3se-069c451bef157773"
ANALYSIS_BASE_URI = BASE_IRI + "analysis-3se-069b5a9129c37ebe"
BREAKDOWN_BASE_URI = BASE_IRI + "breakdown-structure-3se-069d166fa9037b67"
CONCEPTUAL_MODEL_BASE_URI = BASE_IRI + "conceptual-model-3se-069d3d5560bf7635"

# Typed relation fields on role terms that are propagated
ROLE_RELATION_FIELDS = ("isResponsibleFor", "isAccountableFor", "isSupporting")


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

    # ── Build breakdown structure URI set ────────────────────────────────────
    # Collect every term that declares subClassOf BREAKDOWN_BASE_URI.
    breakdown_uris: set[str] = {
        BASE_IRI + stem
        for stem, (_, data) in index.items()
        if is_subclass_of(data, BREAKDOWN_BASE_URI)
    }

    # ── Build conceptual model URI set ───────────────────────────────────────
    # Collect every term that declares subClassOf CONCEPTUAL_MODEL_BASE_URI.
    conceptual_model_uris: set[str] = {
        BASE_IRI + stem
        for stem, (_, data) in index.items()
        if is_subclass_of(data, CONCEPTUAL_MODEL_BASE_URI)
    }

    # ── Build analysis URI → [breakdown structure URIs, conceptual model URIs] index
    # For every analysis term (subclass of analysis-3se), collect the breakdown
    # structure URIs and conceptual model URIs present in its related field.
    # Warn when either kind is absent.
    analysis_to_targets: dict[str, list[str]] = {}
    for stem, (_, data) in index.items():
        if not is_subclass_of(data, ANALYSIS_BASE_URI):
            continue
        related = ensure_list(data.get("related"))
        bs_found = [uri for uri in related if uri in breakdown_uris]
        cm_found = [uri for uri in related if uri in conceptual_model_uris]
        if not bs_found:
            print(
                f"  ⚠️  no breakdown structure: {stem}",
                file=sys.stderr,
            )
        if not cm_found:
            print(
                f"  ⚠️  no conceptual model: {stem}",
                file=sys.stderr,
            )
        targets = bs_found + cm_found
        if targets:
            analysis_to_targets[BASE_IRI + stem] = targets

    # ── Build inverse index: BS/CM URI → set of analysis URIs that reference it
    # Used by the removal pass to check whether a backing analysis still exists.
    target_to_analyses: dict[str, set[str]] = {}
    for analysis_uri, targets in analysis_to_targets.items():
        for target_uri in targets:
            target_to_analyses.setdefault(target_uri, set()).add(analysis_uri)

    # ── Propagate to role terms ───────────────────────────────────────────────
    changes: dict[str, dict] = {}

    def get_working(stem: str) -> dict:
        if stem not in changes:
            changes[stem] = dict(index[stem][1])
        return changes[stem]

    for stem, (_, data) in index.items():
        if not is_subclass_of(data, ROLE_BASE_URI):
            continue

        for field in ROLE_RELATION_FIELDS:
            current = ensure_list(data.get(field))
            current_set = set(current)

            # ── Addition pass ────────────────────────────────────────────
            # For each analysis A in the field, add its linked BS and CM
            # targets when they are not already present.
            additions: list[str] = []
            for analysis_uri in current:
                for target_uri in analysis_to_targets.get(analysis_uri, []):
                    if target_uri not in current_set and target_uri not in additions:
                        additions.append(target_uri)
                        target_stem = stem_for_uri(target_uri) or target_uri
                        print(f"  + {field}: {stem} -> {target_stem}")

            # ── Removal pass ─────────────────────────────────────────────
            # For each BS/CM target T in the field, check whether at least
            # one analysis that references T is also present in the same
            # field. If not, T is stale and must be removed.
            analyses_in_field = {
                uri for uri in current if uri in analysis_to_targets
            }
            removals: list[str] = []
            for uri in current:
                # Only consider URIs that are a BS or CM (i.e. appear in
                # the inverse index) — analyses and other URIs are left alone.
                backing_analyses = target_to_analyses.get(uri)
                if backing_analyses is None:
                    continue
                if not backing_analyses & analyses_in_field:
                    removals.append(uri)
                    target_stem = stem_for_uri(uri) or uri
                    print(f"  - {field}: {stem} -> {target_stem}")

            if additions or removals:
                working = get_working(stem)
                removal_set = set(removals)
                kept = [u for u in current if u not in removal_set]
                working[field] = kept + additions

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
