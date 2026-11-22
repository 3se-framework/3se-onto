#!/usr/bin/env python3
# Generates axioms/facts.pl, the SWI-Prolog fact base of the 3SE ontology, from
# the terms/ directory.
#
# Output
# ──────
# For every term T (atom = file stem without its UUIDv7 suffix, e.g.
# 'functional-element-3se'):
#   term(T).
#   title(T, "Functional element - 3SE").
#   status(T, draft).
#
# For every term field whose values are term URIs (subClassOf, allocates,
# isComposedOf, isAccountableFor, closeMatch, related, ...), one binary
# predicate named after the field in snake_case:
#   sub_class_of(Child, Parent).
#   allocates(Source, Target).
#   is_accountable_for(Role, Analysis).
#
# Fields holding anything else (dates, creators, reference URIs) are skipped,
# as are URIs that do not resolve to a term in terms/ (reported on stderr).
#
# SHACL shapes declared in a term's `hasShape` field become
#   shape_count(Owner, Shape, Target, Exempt, Path, Classes, Except, Min, Max).
# where Owner is the declaring term, Shape the fragment of the shape's @id (its
# position in hasShape when it has none), Target the sh:targetClass, Exempt the
# classes of an sh:or alternative that exempts an instance, Path is
# direct(Relation) or inverse(Relation), Classes the alternative classes of the
# sh:qualifiedValueShape (its sh:class, or the sh:class entries of its sh:or), Except the classes its sh:not excludes (a leaf goal is
# a goal that is not a high level goal) and Min/Max the qualified counts (Max =
# none when unbounded). Only that subset is supported; anything else is an error.
#
# The rules and axioms that reason over these facts live next to the output in
# axioms/core/ and axioms/domain/; axioms/load.pl loads everything.
#
# The output is deterministic (sorted) and is overwritten on every run.

import json
import re
import sys
from pathlib import Path

TERMS_DIR = Path("terms")
CONTEXT = Path("contexts") / "term.context.jsonld"
OUTPUT = Path("axioms") / "facts.pl"
BASE_IRI = "https://www.3se.info/3se-onto/terms/"
PROPERTIES_BASE_IRI = "https://www.3se.info/3se-onto/properties/"
UUID_SUFFIX_RE = re.compile(r"-[0-9a-f]{16}$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_index(terms_dir: Path) -> dict[str, dict]:
    """Return mapping of stem -> data for all JSON files."""
    index: dict[str, dict] = {}
    for fp in sorted(terms_dir.glob("*.json")):
        try:
            index[fp.stem] = json.loads(fp.read_text(encoding="utf-8"))
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


def slug_of(stem: str) -> str:
    return UUID_SUFFIX_RE.sub("", stem)


def atom(slug: str) -> str:
    """Quoted Prolog atom; slugs contain only [a-z0-9-] so no escaping is needed."""
    return f"'{slug}'"


def string(text: str) -> str:
    """Prolog double-quoted string literal."""
    escaped = (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
    )
    return f'"{escaped}"'


def predicate_name(field: str) -> str:
    """camelCase JSON field -> snake_case predicate name."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", field).lower()


def stem_for_uri(uri: str) -> str | None:
    if isinstance(uri, str) and uri.startswith(BASE_IRI):
        return uri[len(BASE_IRI):]
    return None


class ShapeError(Exception):
    """A hasShape entry uses SHACL outside the supported subset."""


def load_property_names(context_path: Path) -> dict[str, str]:
    """Return mapping of property IRI -> predicate name, from the term context."""
    context = json.loads(context_path.read_text(encoding="utf-8"))["@context"]
    names: dict[str, str] = {}
    for field, definition in context.items():
        if isinstance(definition, dict) and definition.get("@id", "").startswith(PROPERTIES_BASE_IRI):
            names[definition["@id"]] = predicate_name(field)
    return names


def iri(node, what: str) -> str:
    if not isinstance(node, dict) or not isinstance(node.get("@id"), str):
        raise ShapeError(f"{what} must be an object with an @id")
    return node["@id"]


def term_slug(uri: str, index: dict[str, dict], what: str) -> str:
    stem = stem_for_uri(uri)
    if stem is None or stem not in index:
        raise ShapeError(f"{what} {uri} is not a term")
    return slug_of(stem)


def shape_path(path, property_names: dict[str, str]) -> str:
    """Prolog term for an sh:path: direct(Rel) or inverse(Rel)."""
    if isinstance(path, dict) and "sh:inversePath" in path:
        uri, kind = iri(path["sh:inversePath"], "sh:inversePath"), "inverse"
    else:
        uri, kind = iri(path, "sh:path"), "direct"
    if uri not in property_names:
        raise ShapeError(f"sh:path {uri} is not a property of the term context")
    return f"{kind}({property_names[uri]})"


def translate_counted_shape(owner: str, label: str, shape: dict, index: dict[str, dict],
                            property_names: dict[str, str]) -> str:
    """Translate a node shape with a qualified count into a shape_count/9 fact."""
    target = term_slug(iri(shape.get("sh:targetClass"), "sh:targetClass"), index, "sh:targetClass")

    exempt: list[str] = []
    property_shape = shape.get("sh:property")
    if "sh:or" in shape:
        if property_shape is not None:
            raise ShapeError("sh:or next to sh:property is not supported")
        alternatives = shape["sh:or"].get("@list") if isinstance(shape["sh:or"], dict) else None
        if not alternatives:
            raise ShapeError("sh:or must be an @list of node shapes")
        for alternative in alternatives:
            if "sh:class" in alternative and "sh:property" not in alternative:
                exempt.append(term_slug(iri(alternative["sh:class"], "sh:class"), index, "sh:class"))
            elif "sh:property" in alternative and property_shape is None:
                property_shape = alternative["sh:property"]
            else:
                raise ShapeError("sh:or alternatives must be one sh:class or one sh:property")
    if not isinstance(property_shape, dict):
        raise ShapeError("a shape needs exactly one sh:property")

    path = shape_path(property_shape.get("sh:path"), property_names)
    value_shape = property_shape.get("sh:qualifiedValueShape")
    if not isinstance(value_shape, dict):
        raise ShapeError("only qualified counts are supported (sh:qualifiedValueShape)")
    value_classes: list[str] = []
    if "sh:or" in value_shape:
        if "sh:class" in value_shape:
            raise ShapeError("sh:or next to sh:class in a sh:qualifiedValueShape is not supported")
        alternatives = value_shape["sh:or"].get("@list") if isinstance(value_shape["sh:or"], dict) else None
        if not alternatives:
            raise ShapeError("sh:or in a sh:qualifiedValueShape must be a non-empty @list")
        for alternative in alternatives:
            if not isinstance(alternative, dict) or set(alternative) != {"sh:class"}:
                raise ShapeError("sh:or alternatives in a sh:qualifiedValueShape must each be a single sh:class")
            value_classes.append(term_slug(iri(alternative["sh:class"], "sh:class"), index, "sh:class"))
    else:
        value_classes.append(term_slug(iri(value_shape.get("sh:class"), "sh:class"), index, "sh:class"))
    excluded: list[str] = []
    if "sh:not" in value_shape:
        negated = value_shape["sh:not"]
        if not isinstance(negated, dict) or set(negated) != {"sh:class"}:
            raise ShapeError("sh:not in a sh:qualifiedValueShape must be a single sh:class")
        excluded.append(term_slug(iri(negated["sh:class"], "sh:class"), index, "sh:class"))
    minimum = property_shape.get("sh:qualifiedMinCount", 0)
    maximum = property_shape.get("sh:qualifiedMaxCount", "none")

    exempt_list = "[" + ", ".join(atom(e) for e in exempt) + "]"
    class_list = "[" + ", ".join(atom(c) for c in value_classes) + "]"
    except_list = "[" + ", ".join(atom(e) for e in excluded) + "]"
    return (
        f"shape_count({atom(owner)}, {label}, {atom(target)}, {exempt_list}, "
        f"{path}, {class_list}, {except_list}, {minimum}, {maximum})."
    )


def shape_label(stem: str, position: int, shape: dict) -> str:
    """Prolog identifier of a shape: its @id fragment, else its position in hasShape."""
    shape_id = shape.get("@id")
    if shape_id is None:
        return str(position)
    prefix = f"{BASE_IRI}{stem}#"
    if not shape_id.startswith(prefix) or len(shape_id) == len(prefix):
        raise ShapeError(f"@id must be {prefix}<slug>")
    return atom(shape_id[len(prefix):])


def translate_shape(stem: str, owner: str, position: int, shape: dict, index: dict[str, dict],
                    property_names: dict[str, str]) -> str:
    """Translate one node shape into a shape_count/9 fact."""
    if shape.get("@type") != "sh:NodeShape":
        raise ShapeError("hasShape entries must be sh:NodeShape")
    label = shape_label(stem, position, shape)
    return translate_counted_shape(owner, label, shape, index, property_names)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    index = load_index(TERMS_DIR)
    if not index:
        print("⚠️  No terms found — nothing to do.")
        return 0

    slugs = {stem: slug_of(stem) for stem in index}
    if len(set(slugs.values())) != len(slugs):
        print("ERROR: two terms share the same slug once the UUID suffix is removed.")
        return 1

    property_names = load_property_names(CONTEXT)

    # predicate name -> sorted set of (source slug, target slug)
    relations: dict[str, set[tuple[str, str]]] = {}
    dangling: list[tuple[str, str, str]] = []
    shape_facts: list[str] = []

    for stem, data in index.items():
        for field, value in data.items():
            if field.startswith("@"):
                continue
            if field == "hasShape":
                for position, shape in enumerate(ensure_list(value), start=1):
                    try:
                        shape_facts.append(
                            translate_shape(stem, slugs[stem], position, shape, index, property_names)
                        )
                    except ShapeError as error:
                        print(f"ERROR: {stem}.hasShape[{position}]: {error}")
                        return 1
                continue
            for item in ensure_list(value):
                target_stem = stem_for_uri(item)
                if target_stem is None:
                    continue
                if target_stem not in index:
                    dangling.append((stem, field, target_stem))
                    continue
                relations.setdefault(predicate_name(field), set()).add(
                    (slugs[stem], slugs[target_stem])
                )

    lines: list[str] = [
        "% Generated by scripts/generate_prolog.py from terms/ — do not edit by hand.",
        "% Rules over these facts: core/ (generic) and domain/ (3SE axioms), loaded by load.pl.",
        "",
        ":- discontiguous term/1, title/2, status/2.",
    ]
    for name in sorted(relations):
        lines.append(f":- dynamic {name}/2.")
    lines.append("")

    lines.append("% ── Terms " + "─" * 60)
    for stem in sorted(index, key=lambda s: slugs[s]):
        slug = slugs[stem]
        data = index[stem]
        lines.append(f"term({atom(slug)}).")
        if "title" in data:
            lines.append(f"title({atom(slug)}, {string(data['title'])}).")
        if "status" in data:
            status = re.sub(r"[^a-z0-9]+", "_", data["status"].lower()).strip("_")
            lines.append(f"status({atom(slug)}, {status}).")
    lines.append("")

    lines.append("% ── Shapes (hasShape) " + "─" * 47)
    lines.append(":- dynamic shape_count/9.")
    lines.extend(sorted(shape_facts))
    lines.append("")

    for name in sorted(relations):
        lines.append(f"% ── {name}/2 " + "─" * 50)
        for source, target in sorted(relations[name]):
            lines.append(f"{name}({atom(source)}, {atom(target)}).")
        lines.append("")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(lines), encoding="utf-8", newline="\n")

    for stem, field, target_stem in dangling:
        print(f"  ⚠️  {stem}.{field} -> {target_stem} (no such term, skipped)", file=sys.stderr)

    total = sum(len(pairs) for pairs in relations.values())
    print(f"Done — {len(index)} term(s), {total} relation fact(s) in {len(relations)} predicate(s), "
          f"{len(shape_facts)} shape(s) -> {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
