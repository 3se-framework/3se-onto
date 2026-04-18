#!/usr/bin/env python3
# Generates glossary.md from the terms/, references/ and properties/ directories.
# Intended to be called by the GitHub Actions workflow generate_glossary.yml.
#
# Output structure:
#   - Header with generation timestamp
#   - Terms section: alphabetically sorted, with all available fields
#   - References section: alphabetically sorted, with all available fields
#   - Properties section: alphabetically sorted, with all available fields

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

TERMS_DIR = Path("terms")
REFERENCES_DIR = Path("references")
PROPERTIES_DIR = Path("properties")
OUTPUT_FILE = Path("glossary.md")

REFERENCE_BASE_IRI = "https://www.3se.info/3se-onto/references/"

# Human-readable labels for bibo: types
BIBO_TYPE_LABELS: dict[str, str] = {
    "bibo:AcademicArticle": "Academic Article",
    "bibo:Article": "Article",
    "bibo:AudioDocument": "Audio Document",
    "bibo:AudioVisualDocument": "Audiovisual Document",
    "bibo:Book": "Book",
    "bibo:BookSection": "Book Section",
    "bibo:Chapter": "Chapter",
    "bibo:Collection": "Collection",
    "bibo:CollectedDocument": "Collected Document",
    "bibo:Conference": "Conference",
    "bibo:Document": "Document",
    "bibo:EditedBook": "Edited Book",
    "bibo:Image": "Image",
    "bibo:Issue": "Issue",
    "bibo:Journal": "Journal",
    "bibo:LegalCaseDocument": "Legal Case Document",
    "bibo:LegalDocument": "Legal Document",
    "bibo:Legislation": "Legislation",
    "bibo:Manuscript": "Manuscript",
    "bibo:Map": "Map",
    "bibo:MultiVolumeBook": "Multi-Volume Book",
    "bibo:Newspaper": "Newspaper",
    "bibo:Note": "Note",
    "bibo:Patent": "Patent",
    "bibo:Periodical": "Periodical",
    "bibo:Proceedings": "Proceedings",
    "bibo:ReferenceSource": "Reference Source",
    "bibo:Report": "Report",
    "bibo:Series": "Series",
    "bibo:Slideshow": "Slideshow",
    "bibo:Standard": "Standard",
    "bibo:Statute": "Statute",
    "bibo:TechnicalDocument": "Technical Document",
    "bibo:Thesis": "Thesis",
    "bibo:Webpage": "Webpage",
    "bibo:Website": "Website",
}

# 3SE editorial status — used on term and property entries (plain string values)
TERM_STATUS_BADGES: dict[str, str] = {
    "draft": "![draft](https://img.shields.io/badge/status-draft-lightgrey)",
    "under review": "![under review](https://img.shields.io/badge/status-under%20review-yellow)",
    "reviewed": "![reviewed](https://img.shields.io/badge/status-reviewed-blue)",
    "under approval": "![under approval](https://img.shields.io/badge/status-under%20approval-orange)",
    "approved": "![approved](https://img.shields.io/badge/status-approved-green)",
    "standard": "![standard](https://img.shields.io/badge/status-standard-brightgreen)",
}

# BIBO publication status — used on reference entries (bibo: CURIE values)
BIBO_STATUS_BADGES: dict[str, str] = {
    "bibo:draft": "![draft](https://img.shields.io/badge/status-draft-lightgrey)",
    "bibo:forthcoming": "![forthcoming](https://img.shields.io/badge/status-forthcoming-yellow)",
    "bibo:peerReviewed": "![peer reviewed](https://img.shields.io/badge/status-peer%20reviewed-blue)",
    "bibo:published": "![published](https://img.shields.io/badge/status-published-brightgreen)",
    "bibo:rejected": "![rejected](https://img.shields.io/badge/status-rejected-red)",
    "bibo:unpublished": "![unpublished](https://img.shields.io/badge/status-unpublished-lightgrey)",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        print(f"  warning: could not load {path}, skipping.", file=sys.stderr)
        return None


def load_directory(directory: Path) -> list[dict]:
    """Load and return all valid JSON entries from a directory, sorted by title."""
    if not directory.exists():
        return []
    entries = []
    for file_path in sorted(directory.glob("*.json")):
        data = load_json(file_path)
        if data is not None:
            entries.append(data)
    return sorted(entries, key=lambda e: e.get("title", "").lower())


def agent_names(agent_field) -> list[str]:
    """Extract display names from an agentOrList field."""
    if not agent_field:
        return []
    if isinstance(agent_field, dict):
        agent_field = [agent_field]
    return [a.get("name", "") for a in agent_field if isinstance(a, dict) and a.get("name")]


def uri_to_anchor(uri: str) -> str:
    """Convert a full @id URI to the fragment used in the References section anchor."""
    # Strip trailing slash then take the last path segment
    return uri.rstrip("/").rsplit("/", 1)[-1]


def title_to_anchor(title: str) -> str:
    """
    Convert a heading title to a GitHub Markdown anchor fragment.
    GitHub's algorithm: lowercase, strip everything that is not a unicode
    word character (letter/digit/underscore), space, or hyphen, then replace
    spaces with hyphens. Consecutive hyphens are NOT collapsed — ' - '
    (space-hyphen-space) correctly produces '---'.
    """
    anchor = title.lower()
    anchor = re.sub(r"[^\w\s\-]", "", anchor)
    anchor = anchor.replace(" ", "-")
    return anchor


def bibo_type_label(type_field) -> str:
    """Return a human-readable label for a bibo: type value or list."""
    if not type_field:
        return ""
    types = [type_field] if isinstance(type_field, str) else type_field
    # Pick the most specific bibo: type (skip bibo:Document if others present)
    bibo_types = [t for t in types if t.startswith("bibo:")]
    if not bibo_types:
        return ""
    specific = [t for t in bibo_types if t != "bibo:Document"] or bibo_types
    return BIBO_TYPE_LABELS.get(specific[0], specific[0].replace("bibo:", ""))


def md_inline_code(value: str) -> str:
    return f"`{value}`"


def split_terms(terms: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split terms into 3SE-defined terms and other (external) terms.
    A term is considered a 3SE term if its title ends with '- 3SE'.
    """
    se3_terms = [t for t in terms if t.get("title", "").endswith("- 3SE")]
    other_terms = [t for t in terms if not t.get("title", "").endswith("- 3SE")]
    return se3_terms, other_terms


def split_properties(properties: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split properties into 3SE properties and other (external) properties.
    A 3SE property has a title ending with '- 3SE', mirroring split_terms().
    """
    se3 = [p for p in properties if p.get("title", "").endswith("- 3SE")]
    other = [p for p in properties if not p.get("title", "").endswith("- 3SE")]
    return se3, other


def build_reference_index(references: list[dict]) -> dict[str, dict]:
    """Build a mapping from @id URI → reference entry for fast lookup."""
    return {r["@id"]: r for r in references if "@id" in r}


def build_superclass_index(terms: list[dict]) -> dict[str, list[dict]]:
    """
    Return a mapping of URI -> list of term entries that declare that URI
    as their subClassOf. Used to compute the inverse superClassOf relation.
    """
    index: dict[str, list[dict]] = {}
    for term in terms:
        val = term.get("subClassOf")
        if not val:
            continue
        uris = [val] if isinstance(val, str) else val
        for uri in uris:
            index.setdefault(uri, []).append(term)
    return index


def build_represents_index(terms: list[dict]) -> dict[str, list[dict]]:
    """
    Return a mapping of URI -> list of term entries that declare that URI
    as their isRepresentedBy target. Used to compute the inverse 'represents'
    relation: if A isRepresentedBy B, then B represents A.
    """
    index: dict[str, list[dict]] = {}
    for term in terms:
        val = term.get("isRepresentedBy")
        if not val:
            continue
        uris = [val] if isinstance(val, str) else val
        for uri in uris:
            index.setdefault(uri, []).append(term)
    return index


def build_allocated_by_index(terms: list[dict]) -> dict[str, list[dict]]:
    """
    Return a mapping of URI -> list of term entries that declare that URI
    as an allocates target. Used to compute the inverse 'allocated by'
    relation: if A allocates B, then B is allocated by A.
    """
    index: dict[str, list[dict]] = {}
    for term in terms:
        val = term.get("allocates")
        if not val:
            continue
        uris = [val] if isinstance(val, str) else val
        for uri in uris:
            index.setdefault(uri, []).append(term)
    return index


def build_terms_index(terms: list[dict]) -> dict[str, dict]:
    """Return a mapping of @id URI -> term data for all terms."""
    return {t["@id"]: t for t in terms if "@id" in t}


BREAKDOWN_STEM_RE = re.compile(r"-breakdown-structure-3se(?:-[0-9a-f]{16})?$")


def is_breakdown_structure(term: dict) -> bool:
    """Return True if this term is a breakdown structure term."""
    term_id = term.get("@id", "")
    stem = term_id.rstrip("/").rsplit("/", 1)[-1]
    return bool(BREAKDOWN_STEM_RE.search(stem))


def render_breakdown_diagram_md(term: dict, terms_index: dict[str, dict],
                                represents_index: dict[str, list[dict]] | None = None) -> list[str]:
    """
    Render a breakdown structure Mermaid diagram as Markdown lines.
    Returns a fenced mermaid code block, or empty list if not applicable.

    Mirrors render_breakdown_diagram in generate_site.py:
    - Primary pass: isComposedOf / isRepresentedBy / allocates / canBe / represents (inverse)
    - Secondary pass: subClassOf / exposes / allocates-to-registered, run after the
      primary pass so that registered_uris is complete. Covers both terms that only
      carry subClassOf/exposes (e.g. system-feature) and target-only nodes that carry
      further allocates relations (e.g. activity).
    """
    if not is_breakdown_structure(term):
        return []

    related_uris = term.get("related", [])
    if isinstance(related_uris, str):
        related_uris = [related_uris]
    if not related_uris:
        return []

    node_ids: dict[str, str] = {}
    node_labels: dict[str, str] = {}
    counter = [0]

    def node_id(uri: str) -> str:
        if uri not in node_ids:
            counter[0] += 1
            node_ids[uri] = f"N{counter[0]}"
        return node_ids[uri]

    def label_for(uri: str) -> str:
        if uri in node_labels:
            return node_labels[uri]
        entry = terms_index.get(uri)
        if entry:
            title = entry.get("title", "")
            lbl = title.split(" - ", 1)[0].strip() if " - " in title else title
        else:
            stem = uri.rstrip("/").rsplit("/", 1)[-1]
            stem = re.sub(r"-[0-9a-f]{16}$", "", stem)
            stem = re.sub(r"-3se$", "", stem)
            lbl = stem.replace("-", " ").title()
        node_labels[uri] = lbl
        return lbl

    edges: list[tuple[str, str, str]] = []

    # Primary pass: structural relations declared directly on each related term
    for rel_uri in related_uris:
        rel_term = terms_index.get(rel_uri)
        if rel_term is None:
            continue
        for obj_uri in (rel_term.get("isComposedOf") or []):
            node_id(rel_uri)
            label_for(rel_uri)
            node_id(obj_uri)
            label_for(obj_uri)
            edges.append((rel_uri, "composition", obj_uri))
        for obj_uri in (rel_term.get("isRepresentedBy") or []):
            node_id(rel_uri)
            label_for(rel_uri)
            node_id(obj_uri)
            label_for(obj_uri)
            edges.append((rel_uri, "representation", obj_uri))
        for obj_uri in (rel_term.get("allocates") or []):
            node_id(rel_uri)
            label_for(rel_uri)
            node_id(obj_uri)
            label_for(obj_uri)
            edges.append((rel_uri, "allocation", obj_uri))
        for obj_uri in (rel_term.get("canBe") or []):
            node_id(rel_uri)
            label_for(rel_uri)
            node_id(obj_uri)
            label_for(obj_uri)
            edges.append((rel_uri, "recursion", obj_uri))
        # represents: inverse of isRepresentedBy — other terms that declare
        # isRepresentedBy pointing at rel_uri are "represented by" rel_uri,
        # so rel_uri "represents" those terms.
        if represents_index:
            for represented_term in (represents_index.get(rel_uri) or []):
                represented_uri = represented_term.get("@id", "")
                if represented_uri:
                    node_id(rel_uri)
                    label_for(rel_uri)
                    node_id(represented_uri)
                    label_for(represented_uri)
                    edges.append((represented_uri, "representation", rel_uri))

    # Secondary pass: run once after the primary pass so registered_uris is complete.
    # Candidates = related_uris union already-registered nodes, to cover:
    #   (a) terms in related with only subClassOf/exposes/allocates (e.g. system-feature)
    #   (b) target-only nodes that carry further relations (e.g. activity)
    registered_uris = set(node_ids.keys())
    related_set = set(related_uris)
    candidates = list(dict.fromkeys(list(related_uris) + list(registered_uris)))
    for child_uri in candidates:
        child_term = terms_index.get(child_uri)
        if child_term is None:
            continue
        subclass_of = child_term.get("subClassOf") or []
        if isinstance(subclass_of, str):
            subclass_of = [subclass_of]
        for parent_uri in subclass_of:
            if parent_uri in registered_uris:
                node_id(child_uri)
                label_for(child_uri)
                edges.append((child_uri, "subclassof", parent_uri))
        exposes = child_term.get("exposes") or []
        if isinstance(exposes, str):
            exposes = [exposes]
        for iface_uri in exposes:
            if iface_uri in registered_uris:
                node_id(child_uri)
                label_for(child_uri)
                edges.append((child_uri, "exposes", iface_uri))
        for obj_uri in (child_term.get("allocates") or []):
            if obj_uri in registered_uris or obj_uri in related_set:
                node_id(child_uri)
                label_for(child_uri)
                node_id(obj_uri)
                label_for(obj_uri)
                edges.append((child_uri, "allocation", obj_uri))

    if not edges:
        return []

    # Deduplicate edges
    edges = list(dict.fromkeys(edges))

    # Deduplicate nodes by label (case-insensitive)
    label_to_primary: dict[str, str] = {}
    uri_remap: dict[str, str] = {}
    for uri in list(node_ids.keys()):
        lbl_lower = node_labels.get(uri, "").lower()
        if lbl_lower in label_to_primary:
            uri_remap[uri] = label_to_primary[lbl_lower]
        else:
            label_to_primary[lbl_lower] = uri
    if uri_remap:
        edges = [(uri_remap.get(s, s), rel, uri_remap.get(o, o)) for s, rel, o in edges]
        edges = list(dict.fromkeys(edges))
        for uri in uri_remap:
            node_ids.pop(uri, None)
            node_labels.pop(uri, None)

    mermaid_lines = ["```mermaid", "graph TD"]
    for uri, nid in node_ids.items():
        lbl = node_labels.get(uri, nid).replace('"', "'")
        mermaid_lines.append(f'    {nid}["{lbl}"]')
    mermaid_lines.append("")
    for subj_uri, rel, obj_uri in edges:
        s, o = node_id(subj_uri), node_id(obj_uri)
        if rel == "composition":
            mermaid_lines.append(f"    {s} -->|composed of| {o}")
        elif rel == "representation":
            mermaid_lines.append(f"    {s} -.->|represented by| {o}")
        elif rel == "allocation":
            mermaid_lines.append(f"    {s} -.->|allocates| {o}")
        elif rel == "subclassof":
            mermaid_lines.append(f"    {s} -->|subclass of| {o}")
        elif rel == "exposes":
            mermaid_lines.append(f"    {s} -.->|exposes| {o}")
        else:
            mermaid_lines.append(f"    {s} -.->|can be| {o}")
    mermaid_lines.append("```")

    return ["**Structure**", ""] + mermaid_lines + [""]


ANALYSIS_BASE_URI = "https://www.3se.info/3se-onto/terms/analysis-3se-069b5a9129c37ebe"


def is_analysis_subclass(term: dict) -> bool:
    """Return True if this term declares subClassOf analysis-3se."""
    subclass = term.get("subClassOf")
    if not subclass:
        return False
    uris = [subclass] if isinstance(subclass, str) else subclass
    return ANALYSIS_BASE_URI in uris


def render_analysis_allocates_diagram_md(term: dict,
                                         terms_index: dict[str, dict]) -> list[str]:
    """
    Render an Allocations Mermaid diagram for analysis terms as Markdown lines.
    Returns a fenced mermaid code block, or empty list if not applicable.

    Mirrors render_analysis_allocates_diagram in generate_site.py:
    - Primary pass: for each related term, collect its allocates targets.
    - Secondary pass: collect subClassOf edges using the union of related_uris
      and already-registered nodes, so terms carrying only subClassOf (and no
      allocates of their own) are still included when their parent is registered.

    Only rendered when the term is a direct subclass of analysis-3se.
    """
    if not is_analysis_subclass(term):
        return []

    related_uris = term.get("related", [])
    if isinstance(related_uris, str):
        related_uris = [related_uris]
    if not related_uris:
        return []

    node_ids: dict[str, str] = {}
    node_labels: dict[str, str] = {}
    counter = [0]

    def node_id(uri: str) -> str:
        if uri not in node_ids:
            counter[0] += 1
            node_ids[uri] = f"N{counter[0]}"
        return node_ids[uri]

    def label_for(uri: str) -> str:
        if uri in node_labels:
            return node_labels[uri]
        entry = terms_index.get(uri)
        if entry:
            title = entry.get("title", "")
            lbl = title.split(" - ", 1)[0].strip() if " - " in title else title
        else:
            stem = uri.rstrip("/").rsplit("/", 1)[-1]
            stem = re.sub(r"-[0-9a-f]{16}$", "", stem)
            stem = re.sub(r"-3se$", "", stem)
            lbl = stem.replace("-", " ").title()
        node_labels[uri] = lbl
        return lbl

    # Primary pass: collect allocates edges from each related term
    allocates_edges = []  # (subj_uri, obj_uri)
    for rel_uri in related_uris:
        rel_term = terms_index.get(rel_uri)
        if rel_term is None:
            continue
        allocates = rel_term.get("allocates") or []
        if isinstance(allocates, str):
            allocates = [allocates]
        for obj_uri in allocates:
            node_id(rel_uri)
            label_for(rel_uri)
            node_id(obj_uri)
            label_for(obj_uri)
            allocates_edges.append((rel_uri, obj_uri))

    if not allocates_edges:
        return []

    # Second pass: for every URI that appears in the allocates edges
    # (both subjects and targets), follow its subClassOf relation and
    # emit a subclass-of edge to its parent.
    # Strictly limited to nodes registered by the first pass — no other
    # candidates are considered, preventing unrelated terms from appearing.
    subclassof_edges = []  # (child_uri, parent_uri)
    allocates_nodes = set(node_ids.keys())  # all nodes from the first pass
    for child_uri in list(allocates_nodes):
        child_term = terms_index.get(child_uri)
        if child_term is None:
            continue
        subclass_of = child_term.get("subClassOf") or []
        if isinstance(subclass_of, str):
            subclass_of = [subclass_of]
        for parent_uri in subclass_of:
            node_id(child_uri)
            label_for(child_uri)
            node_id(parent_uri)
            label_for(parent_uri)
            subclassof_edges.append((child_uri, parent_uri))

    # Third pass: for each parent registered in the second pass, follow its
    # allocates relation and collect the targeted URIs as new allocates edges.
    parent_uris = set(node_ids.keys())
    for parent_uri in list(parent_uris):
        parent_term = terms_index.get(parent_uri)
        if parent_term is None:
            continue
        parent_allocates = parent_term.get("allocates") or []
        if isinstance(parent_allocates, str):
            parent_allocates = [parent_allocates]
        for obj_uri in parent_allocates:
            node_id(parent_uri)
            label_for(parent_uri)
            node_id(obj_uri)
            label_for(obj_uri)
            allocates_edges.append((parent_uri, obj_uri))

    # Deduplicate
    allocates_edges = list(dict.fromkeys(allocates_edges))
    subclassof_edges = list(dict.fromkeys(subclassof_edges))

    # Deduplicate nodes by label (case-insensitive)
    label_to_primary: dict[str, str] = {}
    uri_remap: dict[str, str] = {}
    for uri in list(node_ids.keys()):
        lbl_lower = node_labels.get(uri, "").lower()
        if lbl_lower in label_to_primary:
            uri_remap[uri] = label_to_primary[lbl_lower]
        else:
            label_to_primary[lbl_lower] = uri
    if uri_remap:
        allocates_edges = [
            (uri_remap.get(s, s), uri_remap.get(o, o))
            for s, o in allocates_edges
        ]
        allocates_edges = list(dict.fromkeys(allocates_edges))
        subclassof_edges = [
            (uri_remap.get(s, s), uri_remap.get(o, o))
            for s, o in subclassof_edges
        ]
        subclassof_edges = list(dict.fromkeys(subclassof_edges))
        for uri in uri_remap:
            node_ids.pop(uri, None)
            node_labels.pop(uri, None)

    mermaid_lines = ["```mermaid", "graph TD"]
    for uri, nid in node_ids.items():
        lbl = node_labels.get(uri, nid).replace('"', "'")
        mermaid_lines.append(f'    {nid}["{lbl}"]')
    mermaid_lines.append("")
    for subj_uri, obj_uri in allocates_edges:
        s, o = node_id(subj_uri), node_id(obj_uri)
        mermaid_lines.append(f"    {s} -.->|allocates| {o}")
    for child_uri, parent_uri in subclassof_edges:
        c, p = node_id(child_uri), node_id(parent_uri)
        mermaid_lines.append(f"    {c} -->|subclass of| {p}")
    mermaid_lines.append("```")

    return ["**Allocations**", ""] + mermaid_lines + [""]


# ---------------------------------------------------------------------------
# Term rendering
# ---------------------------------------------------------------------------

def render_term(term: dict, ref_index: dict[str, dict],
                superclass_index: dict[str, list[dict]] | None = None,
                terms_index: dict[str, dict] | None = None,
                represents_index: dict[str, list[dict]] | None = None,
                allocated_by_index: dict[str, list[dict]] | None = None) -> list[str]:
    lines: list[str] = []

    title = term.get("title", "*(untitled)*")
    status = term.get("status", "")
    deprecated = term.get("deprecated", False)

    # Heading
    heading = f"### {title}"
    if deprecated:
        heading += " *(deprecated)*"
    lines.append(heading)
    lines.append("")

    # Status badge
    if status and status in TERM_STATUS_BADGES:
        lines.append(TERM_STATUS_BADGES[status])
        lines.append("")

    # Definition
    if description := term.get("description"):
        lines.append(f"> {description}")
        lines.append("")

    # Scope note
    if notes := term.get("notes"):
        lines.append(notes)
        lines.append("")

    # Aliases
    if aliases := term.get("aliases"):
        lines.append(f"**Aliases:** {', '.join(f'*{a}*' for a in aliases)}")
        lines.append("")

    # Superseded by
    if superseded_by := term.get("superseded_by"):
        anchor = uri_to_anchor(superseded_by)
        lines.append(f"**Superseded by:** [{anchor}]({superseded_by})")
        lines.append("")

    # Hierarchical relations
    relation_rows: list[tuple[str, str]] = []
    for field, label in [
        ("broader", "Broader"),
        ("narrower", "Narrower"),
        ("related", "Related"),
    ]:
        items = term.get(field, [])
        if not items:
            continue
        links = []
        for item in items:
            uri = item if isinstance(item, str) else item.get("@id", "")
            display = (
                          item.get("prefLabel") if isinstance(item, dict) else None
                      ) or uri_to_anchor(uri)
            links.append(f"[{display}]({uri})")
        relation_rows.append((label, ", ".join(links)))

    # BFO subclass relation
    subclass = term.get("subClassOf")
    if subclass:
        uris = [subclass] if isinstance(subclass, str) else subclass
        links = [f"[{uri_to_anchor(uri)}]({uri})" for uri in uris]
        relation_rows.append(("Subclass of", ", ".join(links)))

    # superClassOf (computed inverse)
    if superclass_index:
        term_id = term.get("@id", "")
        subclasses = superclass_index.get(term_id, [])
        if subclasses:
            links = [
                f"[{uri_to_anchor(t.get('@id', ''))}]({t.get('@id', '')})"
                for t in subclasses
            ]
            relation_rows.append(("Superclass of", ", ".join(links)))

    # Represents (computed inverse of isRepresentedBy)
    if represents_index:
        term_id = term.get("@id", "")
        represented_terms = represents_index.get(term_id, [])
        if represented_terms:
            links = [
                f"[{uri_to_anchor(t.get('@id', ''))}]({t.get('@id', '')})"
                for t in represented_terms
            ]
            relation_rows.append(("Represents", ", ".join(links)))

    # Mapping relations (SKOS — cross-vocabulary alignment, non-BFO)
    for field, label in [
        ("exactMatch", "Exact match"),
        ("closeMatch", "Close match"),
        ("broadMatch", "Broad match"),
        ("narrowMatch", "Narrow match"),
        ("relatedMatch", "Related match"),
    ]:
        items = term.get(field, [])
        if not items:
            continue
        links = [f"[{uri_to_anchor(uri)}]({uri})" for uri in items]
        relation_rows.append((label, ", ".join(links)))

    # Breakdown structure constituent relations
    for field, label in [
        ("isComposedOf", "Composed of"),
        ("isRepresentedBy", "Represented by"),
        ("allocates", "Allocates"),
        ("canBe", "Can be"),
        ("exposes", "Exposes"),
    ]:
        items = term.get(field, [])
        if not items:
            continue
        links = [f"[{uri_to_anchor(uri)}]({uri})" for uri in items]
        relation_rows.append((label, ", ".join(links)))

    # Allocated by (computed inverse of allocates)
    if allocated_by_index:
        term_id = term.get("@id", "")
        allocating_terms = allocated_by_index.get(term_id, [])
        if allocating_terms:
            links = [
                f"[{uri_to_anchor(t.get('@id', ''))}]({t.get('@id', '')})"
                for t in allocating_terms
            ]
            relation_rows.append(("Allocated by", ", ".join(links)))

    if relation_rows:
        lines.append("| Relation | Terms |")
        lines.append("|---|---|")
        for label, value in relation_rows:
            lines.append(f"| {label} | {value} |")
        lines.append("")

    # Breakdown structure diagram
    if terms_index:
        lines.extend(render_breakdown_diagram_md(term, terms_index, represents_index))

    # Allocations diagram (analysis terms only)
    if terms_index:
        lines.extend(render_analysis_allocates_diagram_md(term, terms_index))

    # References
    is_referenced_by = term.get("isReferencedBy", [])
    if is_referenced_by:
        ref_links = []
        for uri in is_referenced_by:
            ref = ref_index.get(uri)
            ref_title = ref.get("title", uri_to_anchor(uri)) if ref else uri_to_anchor(uri)
            ref_links.append(f"[{ref_title}]({uri})")
        lines.append(f"**References:** {', '.join(ref_links)}")
        lines.append("")

    # Provenance
    provenance: list[str] = []
    if created := term.get("entryCreated"):
        provenance.append(f"Created: {created}")
    if modified := term.get("entryModified"):
        provenance.append(f"Modified: {modified}")
    creators = agent_names(term.get("entryCreator"))
    if creators:
        provenance.append(f"Creator: {', '.join(creators)}")
    contributors = agent_names(term.get("entryContributor"))
    if contributors:
        provenance.append(f"Contributors: {', '.join(contributors)}")
    if provenance:
        lines.append(f"*{' · '.join(provenance)}*")
        lines.append("")

    return lines


# ---------------------------------------------------------------------------
# Reference rendering
# ---------------------------------------------------------------------------

def render_reference(ref: dict) -> list[str]:
    lines: list[str] = []

    title = ref.get("title", "*(untitled)*")
    bib_type = bibo_type_label(ref.get("@type"))

    # Heading
    lines.append(f"### {title}")
    lines.append("")

    # Type badge
    if bib_type:
        lines.append(f"*{bib_type}*")
        lines.append("")

    # Status badge (bibo:status CURIE values)
    if status := ref.get("status"):
        if status in BIBO_STATUS_BADGES:
            lines.append(BIBO_STATUS_BADGES[status])
            lines.append("")

    # Abstract
    if abstract := ref.get("abstract"):
        lines.append(f"> {abstract}")
        lines.append("")

    # Bibliographic details table
    bib_rows: list[tuple[str, str]] = []

    authors = agent_names(ref.get("authorList") or ref.get("creator"))
    if authors:
        bib_rows.append(("Authors", ", ".join(authors)))

    editors = agent_names(ref.get("editorList"))
    if editors:
        bib_rows.append(("Editors", ", ".join(editors)))

    if publisher := ref.get("publisher"):
        name = publisher.get("name", publisher) if isinstance(publisher, dict) else publisher
        bib_rows.append(("Publisher", str(name)))

    if issued := ref.get("issued"):
        bib_rows.append(("Issued", issued))
    elif date := ref.get("date"):
        bib_rows.append(("Date", date))

    if edition := ref.get("edition"):
        bib_rows.append(("Edition", edition))

    if number := ref.get("number"):
        bib_rows.append(("Number", number))

    for field, label in [("volume", "Volume"), ("issue", "Issue")]:
        if value := ref.get(field):
            bib_rows.append((label, str(value)))

    pages = ref.get("pageStart")
    if pages:
        page_end = ref.get("pageEnd")
        bib_rows.append(("Pages", f"{pages}–{page_end}" if page_end else str(pages)))

    for field, label in [
        ("doi", "DOI"),
        ("isbn13", "ISBN-13"),
        ("isbn10", "ISBN-10"),
        ("issn", "ISSN"),
        ("eissn", "eISSN"),
    ]:
        if value := ref.get(field):
            bib_rows.append((label, md_inline_code(value)))

    if uri := ref.get("uri") or ref.get("url"):
        bib_rows.append(("URL", f"[{uri}]({uri})"))

    if license_uri := ref.get("license"):
        bib_rows.append(("License", f"[{license_uri}]({license_uri})"))

    if language := ref.get("language"):
        lang = ", ".join(language) if isinstance(language, list) else language
        bib_rows.append(("Language", lang))

    if bib_rows:
        lines.append("| Attribute | Value |")
        lines.append("|---|---|")
        for label, value in bib_rows:
            lines.append(f"| **{label}** | {value} |")
        lines.append("")

    # Provenance
    provenance: list[str] = []
    if created := ref.get("entryCreated"):
        provenance.append(f"Created: {created}")
    if modified := ref.get("entryModified"):
        provenance.append(f"Modified: {modified}")
    entry_creators = agent_names(ref.get("entryCreator"))
    if entry_creators:
        provenance.append(f"Creator: {', '.join(entry_creators)}")
    entry_contributors = agent_names(ref.get("entryContributor"))
    if entry_contributors:
        provenance.append(f"Contributors: {', '.join(entry_contributors)}")
    if provenance:
        lines.append(f"*{' · '.join(provenance)}*")
        lines.append("")

    return lines


# ---------------------------------------------------------------------------
# Property rendering
# ---------------------------------------------------------------------------

def render_property(prop: dict, ref_index: dict[str, dict]) -> list[str]:
    lines: list[str] = []

    title = prop.get("title", "*(untitled)*")
    status = prop.get("status", "")

    # Heading
    lines.append(f"### {title}")
    lines.append("")

    # Status badge (same plain-string values as terms)
    if status and status in TERM_STATUS_BADGES:
        lines.append(TERM_STATUS_BADGES[status])
        lines.append("")

    # Definition
    if description := prop.get("description"):
        lines.append(f"> {description}")
        lines.append("")

    # Relations table: domain, range, subPropertyOf
    relation_rows: list[tuple[str, str]] = []

    if domain := prop.get("domain"):
        relation_rows.append(("Domain", md_inline_code(domain)))

    if range_val := prop.get("range"):
        relation_rows.append(("Range", md_inline_code(range_val)))

    sub_of = prop.get("subPropertyOf", [])
    if isinstance(sub_of, str):
        sub_of = [sub_of]
    if sub_of:
        links = [f"[{uri_to_anchor(uri)}]({uri})" for uri in sub_of]
        relation_rows.append(("Sub-property of", ", ".join(links)))

    if relation_rows:
        lines.append("| Relation | Value |")
        lines.append("|---|---|")
        for label, value in relation_rows:
            lines.append(f"| {label} | {value} |")
        lines.append("")

    # Source references
    is_ref_by = prop.get("isReferencedBy", [])
    if isinstance(is_ref_by, str):
        is_ref_by = [is_ref_by]
    if is_ref_by:
        ref_links = []
        for uri in is_ref_by:
            ref = ref_index.get(uri)
            ref_title = ref.get("title", uri_to_anchor(uri)) if ref else uri_to_anchor(uri)
            ref_links.append(f"[{ref_title}]({uri})")
        lines.append(f"**References:** {', '.join(ref_links)}")
        lines.append("")

    # Provenance
    provenance: list[str] = []
    if created := prop.get("entryCreated"):
        provenance.append(f"Created: {created}")
    if modified := prop.get("entryModified"):
        provenance.append(f"Modified: {modified}")
    creators = agent_names(prop.get("entryCreator"))
    if creators:
        provenance.append(f"Creator: {', '.join(creators)}")
    contributors = agent_names(prop.get("entryContributor"))
    if contributors:
        provenance.append(f"Contributors: {', '.join(contributors)}")
    if provenance:
        lines.append(f"*{' · '.join(provenance)}*")
        lines.append("")

    return lines


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    terms = load_directory(TERMS_DIR)
    references = load_directory(REFERENCES_DIR)
    properties = load_directory(PROPERTIES_DIR)
    ref_index = build_reference_index(references)
    superclass_index = build_superclass_index(terms)
    represents_index = build_represents_index(terms)
    allocated_by_index = build_allocated_by_index(terms)
    terms_index = build_terms_index(terms)

    se3_terms, other_terms = split_terms(terms)
    se3_properties, other_properties = split_properties(properties)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    md: list[str] = ["# 3SE Glossary", "", f"*Generated on {now}*", "",
                     f"This glossary contains **{len(se3_terms)} 3SE term(s)**, "
                     f"**{len(other_terms)} other term(s)**, "
                     f"**{len(se3_properties)} 3SE property(ies)**, "
                     f"**{len(other_properties)} other property(ies)**, "
                     f"and **{len(references)} reference(s)**.", "", "## Contents", "",
                     "- [3SE Terms](#3se-terms)"]

    # ── Header ──────────────────────────────────────────────────────────────

    # ── Table of contents ───────────────────────────────────────────────────
    for term in se3_terms:
        title = term.get("title", "")
        anchor = title_to_anchor(title)
        if term.get("deprecated"):
            anchor += "-deprecated"
        md.append(f"  - [{title}](#{anchor})")
    md.append("- [Other Terms](#other-terms)")
    for term in other_terms:
        title = term.get("title", "")
        anchor = title_to_anchor(title)
        if term.get("deprecated"):
            anchor += "-deprecated"
        md.append(f"  - [{title}](#{anchor})")
    md.append("- [References](#references)")
    for ref in references:
        title = ref.get("title", "")
        anchor = title_to_anchor(title)
        md.append(f"  - [{title}](#{anchor})")
    md.append("- [3SE Properties](#3se-properties)")
    for prop in se3_properties:
        title = prop.get("title", "")
        anchor = title_to_anchor(title)
        md.append(f"  - [{title}](#{anchor})")
    md.append("- [Other Properties](#other-properties)")
    for prop in other_properties:
        title = prop.get("title", "")
        anchor = title_to_anchor(title)
        md.append(f"  - [{title}](#{anchor})")
    md.append("")

    # ── 3SE Terms ────────────────────────────────────────────────────────────
    md.append("---")
    md.append("")
    md.append("## 3SE Terms")
    md.append("")
    md.append(f"*{len(se3_terms)} term(s) defined by the 3SE framework.*")
    md.append("")

    if se3_terms:
        for term in se3_terms:
            md.extend(render_term(term, ref_index, superclass_index, terms_index,
                                  represents_index, allocated_by_index))
            md.append("---")
            md.append("")
    else:
        md.append("*No 3SE terms found.*")
        md.append("")

    # ── Other Terms ──────────────────────────────────────────────────────────
    md.append("## Other Terms")
    md.append("")
    md.append(f"*{len(other_terms)} term(s) sourced from external standards and frameworks.*")
    md.append("")

    if other_terms:
        for term in other_terms:
            md.extend(render_term(term, ref_index, superclass_index, terms_index,
                                  represents_index, allocated_by_index))
            md.append("---")
            md.append("")
    else:
        md.append("*No other terms found.*")
        md.append("")

    # ── References ───────────────────────────────────────────────────────────
    md.append("## References")
    md.append("")
    md.append(f"*{len(references)} reference(s).*")
    md.append("")

    if references:
        for ref in references:
            md.extend(render_reference(ref))
            md.append("---")
            md.append("")
    else:
        md.append("*No references found.*")
        md.append("")

    # ── 3SE Properties ───────────────────────────────────────────────────────
    md.append("## 3SE Properties")
    md.append("")
    md.append(f"*{len(se3_properties)} propert(ies) defined by the 3SE framework.*")
    md.append("")

    if se3_properties:
        for prop in se3_properties:
            md.extend(render_property(prop, ref_index))
            md.append("---")
            md.append("")
    else:
        md.append("*No 3SE properties found.*")
        md.append("")

    # ── Other Properties ─────────────────────────────────────────────────────
    md.append("## Other Properties")
    md.append("")
    md.append(f"*{len(other_properties)} propert(ies) sourced from external standards and frameworks.*")
    md.append("")

    if other_properties:
        for prop in other_properties:
            md.extend(render_property(prop, ref_index))
            md.append("---")
            md.append("")
    else:
        md.append("*No other properties found.*")
        md.append("")

    # ── Write output ─────────────────────────────────────────────────────────
    OUTPUT_FILE.write_text("\n".join(md), encoding="utf-8")
    print(
        f"✅ Generated {OUTPUT_FILE} "
        f"({len(se3_terms)} 3SE term(s), "
        f"{len(other_terms)} other term(s), "
        f"{len(references)} reference(s), "
        f"{len(se3_properties)} 3SE propert(ies), "
        f"{len(other_properties)} other propert(ies))."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
