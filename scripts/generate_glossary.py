#!/usr/bin/env python3
# Generates glossary.md from the terms/ and references/ directories.
# Intended to be called by the GitHub Actions workflow generate_glossary.yml.
#
# Output structure:
#   - Header with generation timestamp
#   - Terms section: alphabetically sorted, with all available fields
#   - References section: alphabetically sorted, with all available fields

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

TERMS_DIR      = Path("terms")
REFERENCES_DIR = Path("references")
OUTPUT_FILE    = Path("glossary.md")

REFERENCE_BASE_IRI = "https://github.com/3se-framework/3se-glossary/references/"

# Human-readable labels for bibo: types
BIBO_TYPE_LABELS: dict[str, str] = {
    "bibo:AcademicArticle":    "Academic Article",
    "bibo:Article":            "Article",
    "bibo:AudioDocument":      "Audio Document",
    "bibo:AudioVisualDocument":"Audiovisual Document",
    "bibo:Book":               "Book",
    "bibo:BookSection":        "Book Section",
    "bibo:Chapter":            "Chapter",
    "bibo:Collection":         "Collection",
    "bibo:CollectedDocument":  "Collected Document",
    "bibo:Conference":         "Conference",
    "bibo:Document":           "Document",
    "bibo:EditedBook":         "Edited Book",
    "bibo:Image":              "Image",
    "bibo:Issue":              "Issue",
    "bibo:Journal":            "Journal",
    "bibo:LegalCaseDocument":  "Legal Case Document",
    "bibo:LegalDocument":      "Legal Document",
    "bibo:Legislation":        "Legislation",
    "bibo:Manuscript":         "Manuscript",
    "bibo:Map":                "Map",
    "bibo:MultiVolumeBook":    "Multi-Volume Book",
    "bibo:Newspaper":          "Newspaper",
    "bibo:Note":               "Note",
    "bibo:Patent":             "Patent",
    "bibo:Periodical":         "Periodical",
    "bibo:Proceedings":        "Proceedings",
    "bibo:ReferenceSource":    "Reference Source",
    "bibo:Report":             "Report",
    "bibo:Series":             "Series",
    "bibo:Slideshow":          "Slideshow",
    "bibo:Standard":           "Standard",
    "bibo:Statute":            "Statute",
    "bibo:TechnicalDocument":  "Technical Document",
    "bibo:Thesis":             "Thesis",
    "bibo:Webpage":            "Webpage",
    "bibo:Website":            "Website",
}

STATUS_BADGES: dict[str, str] = {
    "draft":            "![draft](https://img.shields.io/badge/status-draft-lightgrey)",
    "under review":     "![under review](https://img.shields.io/badge/status-under%20review-yellow)",
    "reviewed":         "![reviewed](https://img.shields.io/badge/status-reviewed-blue)",
    "under approval":   "![under approval](https://img.shields.io/badge/status-under%20approval-orange)",
    "approved":         "![approved](https://img.shields.io/badge/status-approved-green)",
    "standard":         "![standard](https://img.shields.io/badge/status-standard-brightgreen)",
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


def build_reference_index(references: list[dict]) -> dict[str, dict]:
    """Build a mapping from @id URI → reference entry for fast lookup."""
    return {r["@id"]: r for r in references if "@id" in r}


# ---------------------------------------------------------------------------
# Term rendering
# ---------------------------------------------------------------------------

def render_term(term: dict, ref_index: dict[str, dict]) -> list[str]:
    lines: list[str] = []

    title      = term.get("title", "*(untitled)*")
    status     = term.get("status", "")
    deprecated = term.get("deprecated", False)

    # Heading
    heading = f"### {title}"
    if deprecated:
        heading += " *(deprecated)*"
    lines.append(heading)
    lines.append("")

    # Status badge
    if status and status in STATUS_BADGES:
        lines.append(STATUS_BADGES[status])
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
        lines.append(f"**Superseded by:** [{anchor}](#{anchor})")
        lines.append("")

    # Hierarchical relations
    relation_rows: list[tuple[str, str]] = []
    for field, label in [
        ("broader",  "Broader"),
        ("narrower", "Narrower"),
        ("related",  "Related"),
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
            anchor = uri_to_anchor(uri)
            links.append(f"[{display}](#{anchor})")
        relation_rows.append((label, ", ".join(links)))

    # Mapping relations
    for field, label in [
        ("exactMatch",   "Exact match"),
        ("closeMatch",   "Close match"),
        ("broadMatch",   "Broad match"),
        ("narrowMatch",  "Narrow match"),
        ("relatedMatch", "Related match"),
    ]:
        items = term.get(field, [])
        if not items:
            continue
        links = [f"[{uri}]({uri})" for uri in items]
        relation_rows.append((label, ", ".join(links)))

    if relation_rows:
        lines.append("| Relation | Terms |")
        lines.append("|---|---|")
        for label, value in relation_rows:
            lines.append(f"| {label} | {value} |")
        lines.append("")

    # References
    is_referenced_by = term.get("isReferencedBy", [])
    if is_referenced_by:
        ref_links = []
        for uri in is_referenced_by:
            ref = ref_index.get(uri)
            ref_title = ref.get("title", uri_to_anchor(uri)) if ref else uri_to_anchor(uri)
            anchor = uri_to_anchor(uri)
            ref_links.append(f"[{ref_title}](#{anchor})")
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

    title    = ref.get("title", "*(untitled)*")
    bib_type = bibo_type_label(ref.get("@type"))
    anchor   = uri_to_anchor(ref.get("@id", ""))

    # Heading — use anchor as the HTML id target for inbound links from terms
    lines.append(f"### {title}")
    lines.append("")

    # Type badge
    if bib_type:
        lines.append(f"*{bib_type}*")
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
        ("doi",    "DOI"),
        ("isbn13", "ISBN-13"),
        ("isbn10", "ISBN-10"),
        ("issn",   "ISSN"),
        ("eissn",  "eISSN"),
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
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    terms      = load_directory(TERMS_DIR)
    references = load_directory(REFERENCES_DIR)
    ref_index  = build_reference_index(references)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    md: list[str] = []

    # ── Header ──────────────────────────────────────────────────────────────
    md.append("# 3SE Glossary")
    md.append("")
    md.append(f"*Generated on {now}*")
    md.append("")
    md.append(
        f"This glossary contains **{len(terms)} term(s)** "
        f"and **{len(references)} reference(s)**."
    )
    md.append("")

    # ── Table of contents ───────────────────────────────────────────────────
    md.append("## Contents")
    md.append("")
    md.append("- [Terms](#terms)")
    for term in terms:
        title  = term.get("title", "")
        anchor = title.lower().replace(" ", "-").replace("/", "").replace("(", "").replace(")", "")
        if term.get("deprecated"):
            anchor += "-deprecated"
        md.append(f"  - [{title}](#{anchor})")
    md.append("- [References](#references)")
    for ref in references:
        title  = ref.get("title", "")
        anchor = title.lower().replace(" ", "-").replace("/", "").replace(".", "").replace(":", "")
        md.append(f"  - [{title}](#{anchor})")
    md.append("")

    # ── Terms ────────────────────────────────────────────────────────────────
    md.append("---")
    md.append("")
    md.append("## Terms")
    md.append("")

    if terms:
        for term in terms:
            md.extend(render_term(term, ref_index))
            md.append("---")
            md.append("")
    else:
        md.append("*No terms found.*")
        md.append("")

    # ── References ───────────────────────────────────────────────────────────
    md.append("## References")
    md.append("")

    if references:
        for ref in references:
            md.extend(render_reference(ref))
            md.append("---")
            md.append("")
    else:
        md.append("*No references found.*")
        md.append("")

    # ── Write output ─────────────────────────────────────────────────────────
    OUTPUT_FILE.write_text("\n".join(md), encoding="utf-8")
    print(f"✅ Generated {OUTPUT_FILE} ({len(terms)} term(s), {len(references)} reference(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
