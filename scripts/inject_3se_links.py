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
# Requires: inflect, nltk (with punkt_tab and averaged_perceptron_tagger_eng data)

import json
import re
import sys
from pathlib import Path

import inflect
import nltk

# Ensure required NLTK data is available (downloaded once, cached locally)
for _pkg in ("punkt_tab", "averaged_perceptron_tagger_eng"):
    try:
        nltk.data.find(f"tokenizers/{_pkg}" if "punkt" in _pkg else f"taggers/{_pkg}")
    except LookupError:
        nltk.download(_pkg, quiet=True)


def is_noun_in_context(word: str, sentence: str) -> bool:
    """
    Return True if `word` appears in `sentence` tagged as a noun (NN*) and
    not in a verbal context. Used to disambiguate single-word concept names
    that are also common verbs (e.g. 'exchange', 'flow', 'change', 'test').

    Rejects the match if:
    - The token is tagged as a verb (VB*), OR
    - It is preceded by a coordinating conjunction ('and', 'or', 'and/or'),
      which signals a coordinated verb phrase (e.g. 'meet and exchange flows')
    """
    tokens = nltk.word_tokenize(sentence)
    tags = nltk.pos_tag(tokens)
    for i, (token, tag) in enumerate(tags):
        if token.lower() != word.lower():
            continue
        # Reject if tagged as a verb
        if tag.startswith("VB"):
            return False
        # Reject if immediately preceded by a coordinating conjunction
        # (covers "meet and exchange", "interact and/or exchange")
        if i > 0:
            prev_token = tags[i - 1][0].lower()
            if prev_token in ("and", "or", "and/or", "/"):
                return False
        # Accept only if tagged as a noun
        if tag.startswith("NN"):
            return True
    return False


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
    Note: inflect is called with the lowercased last word to ensure correct
    pluralisation (e.g. 'Activity' -> 'activities', not 'Activitys').
    """
    variants = {name}
    words = name.split()
    last_lower = words[-1].lower()
    plural_last = _inflect.plural(last_lower)
    if plural_last and plural_last.lower() != last_lower:
        variants.add(" ".join(words[:-1] + [plural_last]) if len(words) > 1 else plural_last)
    singular_last = _inflect.singular_noun(last_lower)
    if singular_last:
        variants.add(" ".join(words[:-1] + [singular_last]) if len(words) > 1 else singular_last)
    return list(variants)


def extract_qualifier_words(se3_concepts: dict[str, str]) -> tuple[set[str], set[str]]:
    """
    Build two sets of qualifier words from multi-word 3SE concept names:
    - prefix_qualifiers: first words (e.g. 'enabling' from 'enabling physical element')
      A match is rejected when one of these precedes the concept name.
    - suffix_qualifiers: last words and their plurals (e.g. 'case'/'cases' from
      'test case', 'run' from 'test run').
      A match is rejected when one of these follows the concept name.
    Only words from multi-word concept names are included.
    """
    prefix_qualifiers: set[str] = set()
    suffix_qualifiers: set[str] = set()
    for name in se3_concepts.values():
        words = name.split()
        if len(words) > 1:
            prefix_qualifiers.add(words[0].lower())
            last = words[-1].lower()
            suffix_qualifiers.add(last)
            # Add naive plural so "cases" matches "case", "elements" matches "element"
            for plural in name_variants(last):
                suffix_qualifiers.add(plural.lower())
    return prefix_qualifiers, suffix_qualifiers


def name_in_description(name: str, description: str,
                        prefix_qualifiers: set[str] | None = None,
                        suffix_qualifiers: set[str] | None = None) -> bool:
    """
    Return True if concept name (or its plural/singular form) appears as a
    whole phrase in description, and is NOT part of a longer compound concept.

    Two compound-concept guards are applied:
    - Prefix guard: rejects a match if the word immediately before it is a
      known prefix qualifier (e.g. 'enabling' before 'physical element').
    - Suffix guard: rejects a match if the word immediately after it is a
      known suffix qualifier (e.g. 'case' after 'test', 'run' after 'test').

    For single-word concept names, an additional POS guard is applied:
    the matched word must be tagged as a noun (NN*) in context, rejecting
    verb usages (e.g. 'exchange flows' where 'exchange' is a verb).
    """
    is_single_word = len(name.split()) == 1

    for variant in name_variants(name):
        # Only apply the POS guard to the base form of the concept name.
        # Inflected forms (plurals, singulars) are almost never verbs —
        # e.g. "activities", "functions", "states" — so tagging them is
        # unreliable and causes false negatives.
        apply_pos_guard = is_single_word and variant.lower() == name.lower()

        pattern = r"(?<![a-zA-Z0-9])" + re.escape(variant) + r"(?![a-zA-Z0-9])"
        for m in re.finditer(pattern, description, re.IGNORECASE):
            start, end = m.start(), m.end()

            # Prefix guard: check the word immediately before the match
            if prefix_qualifiers:
                preceding_text = description[:start].rstrip()
                if preceding_text:
                    preceding_words = preceding_text.split()
                    if preceding_words:
                        last_word = preceding_words[-1].lower().rstrip(".,;:")
                        if last_word in prefix_qualifiers:
                            continue  # compound concept — skip

            # Suffix guard: check the word immediately after the match
            if suffix_qualifiers:
                following_text = description[end:].lstrip()
                if following_text:
                    following_words = following_text.split()
                    if following_words:
                        first_word = following_words[0].lower().lstrip(".,;:")
                        if first_word in suffix_qualifiers:
                            continue  # compound concept — skip

            # POS guard: for the base form of single-word names, reject verb usages
            if apply_pos_guard:
                # Find the sentence containing the match using character offsets
                sentences = nltk.sent_tokenize(description)
                containing = description  # fallback to full description
                offset = 0
                for s in sentences:
                    s_start = description.find(s, offset)
                    if s_start != -1 and s_start <= start < s_start + len(s):
                        containing = s
                        break
                    if s_start != -1:
                        offset = s_start + len(s)
                if not is_noun_in_context(variant, containing):
                    continue  # verb usage — skip

            return True
    return False


def uri_for_stem(stem: str) -> str:
    return BASE_IRI + stem


def stem_for_uri(uri: str) -> str | None:
    if uri.startswith(BASE_IRI):
        return uri[len(BASE_IRI):]
    return None


def subclass_uris(data: dict) -> set[str]:
    """Return the set of URIs declared as subClassOf on a term."""
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

    # Build qualifier words from multi-word 3SE concept names
    prefix_qualifiers, suffix_qualifiers = extract_qualifier_words(se3_concepts)

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

            if name_in_description(name, description, prefix_qualifiers, suffix_qualifiers):
                tgt_uri = uri_for_stem(tgt_stem)
                tgt_title = tgt_data.get("title", "")

                # Only justify links to other 3SE terms
                if not tgt_title.endswith("- 3SE"):
                    continue

                # Skip if source is already a subclass of target or vice versa
                tgt_subclass_uris = subclass_uris(tgt_data)
                if tgt_uri in src_subclass_uris or src_uri in tgt_subclass_uris:
                    continue

                # Skip if source or target already has a structural breakdown
                # relation (isComposedOf / isDescribedBy / canBe) linking them —
                # those relations supersede skos:related
                src_structural = set()
                tgt_structural = set()
                for field in ("isComposedOf", "isDescribedBy", "canBe"):
                    for uri in (src_data.get(field) or []):
                        src_structural.add(uri)
                    for uri in (tgt_data.get(field) or []):
                        tgt_structural.add(uri)
                if tgt_uri in src_structural or src_uri in tgt_structural:
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
    # Build a set of all 3SE term URIs that are referenced by any subClassOf
    # field — these are superclasses and are never truly standalone
    superclass_uris: set[str] = set()
    for stem2, (_, data2) in index.items():
        for uri in subclass_uris(data2):
            superclass_uris.add(uri)

    for stem, name in se3_concepts.items():
        working = changes.get(stem, index[stem][1])
        existing = working.get("related", [])
        if isinstance(existing, str):
            existing = [existing]
        if not existing:
            term_uri = uri_for_stem(stem)
            # Not standalone if it declares subClassOf (is itself a subclass)
            if subclass_uris(working):
                continue
            # Not standalone if other terms declare it as subClassOf (is a superclass)
            if term_uri in superclass_uris:
                continue
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
