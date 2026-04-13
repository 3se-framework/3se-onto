#!/usr/bin/env python3
# Generates a static HTML site for the 3SE ontology under _site/.
#
# Output structure:
#   _site/
#     index.html                          — searchable index of all terms & references
#     terms/<stem>/index.html             — HTML page for each term
#     terms/<stem>/index.jsonld           — raw JSON-LD for linked data clients
#     references/<stem>/index.html        — HTML page for each reference
#     references/<stem>/index.jsonld      — raw JSON-LD for linked data clients
#
# Content negotiation:
#   Each HTML page embeds a <script type="application/ld+json"> block and a
#   JS snippet that redirects non-browser user-agents to index.jsonld.

import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

TERMS_DIR = Path("terms")
REFERENCES_DIR = Path("references")
PROPERTIES_DIR = Path("properties")
SITE_DIR = Path("_site")

SEP = " &nbsp;&middot;&nbsp; "  # separator used between inline link lists

BASE_IRIS: dict[str, str] = {
    "terms": "https://www.3se.info/3se-onto/terms/",
    "references": "https://www.3se.info/3se-onto/references/",
    "properties": "https://www.3se.info/3se-onto/properties/",
}

TERM_STATUS_LABELS: dict[str, tuple[str, str]] = {
    "draft": ("Draft", "#9ca3af"),
    "under review": ("Under Review", "#f59e0b"),
    "reviewed": ("Reviewed", "#3b82f6"),
    "under approval": ("Under Approval", "#8b5cf6"),
    "approved": ("Approved", "#10b981"),
    "standard": ("Standard", "#059669"),
}

# Property entries share the same plain-string status values as terms.
# They are intentionally resolved via TERM_STATUS_LABELS in resolve_status().

BIBO_STATUS_LABELS: dict[str, tuple[str, str]] = {
    "bibo:draft": ("Draft", "#9ca3af"),
    "bibo:forthcoming": ("Forthcoming", "#f59e0b"),
    "bibo:peerReviewed": ("Peer Reviewed", "#3b82f6"),
    "bibo:published": ("Published", "#059669"),
    "bibo:rejected": ("Rejected", "#ef4444"),
    "bibo:unpublished": ("Unpublished", "#9ca3af"),
}

SKOS_MATCH_LABELS: dict[str, str] = {
    "exactMatch": "Exact match",
    "closeMatch": "Close match",
    "broadMatch": "Broad match",
    "narrowMatch": "Narrow match",
    "relatedMatch": "Related match",
}

BIBO_TYPE_LABELS: dict[str, str] = {
    "bibo:Book": "Book",
    "bibo:AcademicArticle": "Academic Article",
    "bibo:Article": "Article",
    "bibo:Standard": "Standard",
    "bibo:Report": "Report",
    "bibo:Webpage": "Webpage",
    "bibo:Website": "Website",
    "bibo:Thesis": "Thesis",
    "bibo:Proceedings": "Proceedings",
    "bibo:TechnicalDocument": "Technical Document",
}

# Human-readable labels for structural breakdown relation fields rendered on term pages.
BREAKDOWN_RELATION_LABELS: dict[str, str] = {
    "isComposedOf": "Composed of",
    "isRepresentedBy": "Represented by",
    "allocates": "Allocates",
    "canBe": "Can be",
}

# Human-readable labels for role relation fields rendered on term pages.
ROLE_RELATION_LABELS: dict[str, str] = {
    "isResponsibleFor": "Responsible for",
    "isAccountableFor": "Accountable for",
    "isSupporting": "Supporting",
}

# Human-readable labels for exposure relation fields rendered on term pages.
EXPOSURE_RELATION_LABELS: dict[str, str] = {
    "exposes": "Exposes",
}


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        print(f"  warning: could not load {path}, skipping.", file=sys.stderr)
        return None


def load_directory(directory: Path) -> list[dict]:
    if not directory.exists():
        return []
    entries = []
    for fp in sorted(directory.glob("*.json")):
        data = load_json(fp)
        if data is not None:
            data["_stem"] = fp.stem
            entries.append(data)
    return sorted(entries, key=lambda e: e.get("title", "").lower())


def split_terms(terms: list[dict]) -> tuple[list[dict], list[dict]]:
    se3 = [t for t in terms if t.get("title", "").endswith("- 3SE")]
    other = [t for t in terms if not t.get("title", "").endswith("- 3SE")]
    return se3, other


def agent_names(field) -> list[str]:
    if not field:
        return []
    if isinstance(field, dict):
        field = [field]
    return [a.get("name", "") for a in field if isinstance(a, dict) and a.get("name")]


def stem_from_uri(uri: str) -> str:
    return uri.rstrip("/").rsplit("/", 1)[-1]


def href_for_uri(uri: str) -> str:
    for dir_name, base in BASE_IRIS.items():
        if uri.startswith(base):
            stem = uri[len(base):]
            return f"/3se-onto/{dir_name}/{stem}/"
    return uri


def is_internal_uri(uri: str) -> bool:
    return any(uri.startswith(b) for b in BASE_IRIS.values())


def bibo_type_label(type_field) -> str:
    if not type_field:
        return ""
    types = [type_field] if isinstance(type_field, str) else type_field
    bibo = [t for t in types if t.startswith("bibo:")]
    if not bibo:
        return ""
    specific = [t for t in bibo if t != "bibo:Document"] or bibo
    return BIBO_TYPE_LABELS.get(specific[0], specific[0].replace("bibo:", ""))


def resolve_status(entry: dict) -> tuple[str, str, str]:
    """Return (raw_key, display_label, color) for a term, property, or reference entry.

    Terms and properties use plain string status values (e.g. "draft", "approved").
    References use bibo:status CURIE values (e.g. "bibo:published").
    Both cases are resolved here so callers need no special-casing.
    """
    status = entry.get("status", "")
    # Plain-string status — covers terms AND properties
    if status and status in TERM_STATUS_LABELS:
        label, color = TERM_STATUS_LABELS[status]
        return status, label, color
    # bibo:status CURIE — covers references
    if status and status in BIBO_STATUS_LABELS:
        label, color = BIBO_STATUS_LABELS[status]
        return status, label, color
    return status, "", ""


def build_reference_index(references: list[dict]) -> dict[str, dict]:
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
    as their isRepresentedBy target.  Used to compute the inverse 'represents'
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


def split_properties(properties: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split properties into 3SE properties and other (external) properties.

    A 3SE property has a title ending with '- 3SE', mirroring split_terms().
    """
    se3 = [p for p in properties if p.get("title", "").endswith("- 3SE")]
    other = [p for p in properties if not p.get("title", "").endswith("- 3SE")]
    return se3, other


def clean_jsonld(entry: dict) -> dict:
    return {k: v for k, v in entry.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Shared CSS — matches www.3se.info visual language
# ---------------------------------------------------------------------------

SHARED_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;0,900;1,400&family=DM+Sans:wght@300;400;500&display=swap');

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --white:     #ffffff;
  --bg:        #f4f7fb;
  --bg2:       #e8f0f9;
  --border:    #c5d5e8;
  --border2:   #b0c4de;
  --text:      #0d1b2a;
  --text2:     #2e4057;
  --muted:     #6b7f96;
  --muted2:    #9ca3af;
  --accent:    #1a5faa;
  --link:      #1a5faa;
  --link-h:    #134d8c;
  --green:     #059669;
  --amber:     #d97706;
  --mono:      'JetBrains Mono', 'Courier New', monospace;
  --sans:      'DM Sans', system-ui, sans-serif;
  --radius:    4px;
  --max-w:     1080px;
  --ink:       #0d1b2a;
  --ink-mid:   #2e4057;
  --ink-light: #6b7f96;
  --rule:      #c5d5e8;
}

html { font-size: 16px; scroll-behavior: smooth; }

body {
  background: var(--white);
  color: var(--text);
  font-family: var(--sans);
  font-weight: 400;
  line-height: 1.7;
  -webkit-font-smoothing: antialiased;
}

a { color: var(--link); text-decoration: none; }
a:hover { color: var(--link-h); text-decoration: underline; }

/* ── Nav — matches www.3se.info exactly ── */
header {
  position: fixed;
  top: 0; left: 0; right: 0;
  z-index: 100;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1.2rem 4rem;
  background: rgba(244, 247, 251, 0.92);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--rule);
}
.header-inner { display: contents; }
.logo {
  font-family: 'Playfair Display', serif;
  font-size: 1.4rem;
  font-weight: 900;
  letter-spacing: -0.02em;
  color: var(--ink);
  text-decoration: none !important;
  align-items: center;
}
.logo span { color: var(--accent); }
header nav {
  display: flex;
  gap: 2.5rem;
  list-style: none;
  align-items: center;
}
header nav a {
  text-decoration: none;
  font-size: 0.85rem;
  font-weight: 500;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--ink-mid);
  transition: color 0.2s;
}
header nav a:hover { color: var(--accent); text-decoration: none; }

/* ── Main ── */
main {
  max-width: var(--max-w);
  margin: 0 auto;
  padding: 5rem 2rem 5rem;
}

@media (max-width: 900px) {
  header { padding: 1rem 1.5rem; }
  header nav { display: none; }
}

/* ── Breadcrumb ── */
.breadcrumb {
  font-size: .8rem;
  color: var(--muted);
  margin-bottom: 2rem;
  display: flex;
  align-items: center;
  gap: .5rem;
}
.breadcrumb a { color: var(--muted); }
.breadcrumb a:hover { color: var(--text); text-decoration: none; }
.breadcrumb span { color: var(--muted2); }

/* ── Typography ── */
h1 { font-family: 'Playfair Display', serif; font-size: 2rem; font-weight: 700; letter-spacing: -.02em; line-height: 1.2; }
h2 { font-size: 1.1rem; font-weight: 600; letter-spacing: -.01em; }
h3 { font-size: .75rem; font-weight: 600; text-transform: uppercase;
     letter-spacing: .08em; color: var(--muted); }

/* ── Badge ── */
.badge {
  display: inline-flex;
  align-items: center;
  padding: .15rem .55rem;
  border-radius: 999px;
  font-family: var(--mono);
  font-size: .68rem;
  font-weight: 500;
  letter-spacing: .04em;
  text-transform: uppercase;
  border: 1px solid currentColor;
}

/* ── Section divider ── */
.section-label {
  font-size: 0.7rem;
  font-weight: 500;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: var(--accent);
  margin-bottom: 1.2rem;
  display: flex;
  align-items: center;
  gap: 0.8rem;
}
.section-label::before {
  content: '';
  display: inline-block;
  width: 1.5rem;
  height: 1px;
  background: var(--accent);
}

/* ── Blockquote definition ── */
.definition {
  font-size: 1.1rem;
  line-height: 1.75;
  color: var(--text2);
  border-left: 3px solid var(--text);
  padding-left: 1.25rem;
  margin: 1.5rem 0;
}

/* ── Relations table ── */
.relations-table { width: 100%; border-collapse: collapse; }
.relations-table td {
  padding: .5rem .75rem;
  border-bottom: 1px solid var(--border);
  font-size: .9rem;
  vertical-align: top;
}
.relations-table td:first-child {
  font-family: var(--mono);
  font-size: .75rem;
  color: var(--muted);
  white-space: nowrap;
  width: 130px;
  padding-top: .6rem;
}
.relations-table tr:last-child td { border-bottom: none; }

/* ── Bib table ── */
.bib-table { width: 100%; border-collapse: collapse; }
.bib-table td {
  padding: .45rem .75rem;
  border-bottom: 1px solid var(--border);
  font-size: .88rem;
  vertical-align: top;
}
.bib-table td:first-child {
  font-family: var(--mono);
  font-size: .72rem;
  color: var(--muted);
  white-space: nowrap;
  width: 110px;
  padding-top: .55rem;
}
.bib-table tr:last-child td { border-bottom: none; }

/* ── Code block ── */
.code-block {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1.25rem 1.5rem;
  overflow-x: auto;
  font-family: var(--mono);
  font-size: .78rem;
  line-height: 1.7;
  color: var(--text2);
}

/* ── Card ── */
.card {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1.5rem 1.75rem;
  margin-top: 1.5rem;
}

/* ── Search / filter bar ── */
.filter-bar {
  display: flex;
  gap: .75rem;
  flex-wrap: wrap;
  align-items: center;
  margin-bottom: 1.5rem;
}
.filter-bar input,
.filter-bar select {
  background: var(--white);
  border: 1px solid var(--border2);
  border-radius: var(--radius);
  padding: .5rem .85rem;
  font-family: var(--sans);
  font-size: .88rem;
  color: var(--text);
  outline: none;
  transition: border-color .15s;
}
.filter-bar input { flex: 1; min-width: 220px; }
.filter-bar input:focus,
.filter-bar select:focus { border-color: var(--text); }
.filter-bar select { cursor: pointer; }

/* ── Index table ── */
.index-table { width: 100%; border-collapse: collapse; }
.index-table thead tr {
  border-bottom: 2px solid var(--text);
}
.index-table thead th {
  text-align: left;
  padding: .5rem .75rem;
  font-family: var(--mono);
  font-size: .7rem;
  font-weight: 600;
  color: var(--muted);
  letter-spacing: .08em;
  text-transform: uppercase;
  white-space: nowrap;
}
.index-table tbody tr {
  border-bottom: 1px solid var(--border);
  transition: background .1s;
}
.index-table tbody tr:hover { background: var(--bg); }
.index-table tbody td {
  padding: .65rem .75rem;
  font-size: .9rem;
  vertical-align: top;
}
.index-table tbody td.desc {
  color: var(--muted);
  font-size: .83rem;
  max-width: 360px;
}

/* ── Entry listing ── */
.entry-list { list-style: none; }
.entry-list li {
  padding: 1rem 0;
  border-bottom: 1px solid var(--border);
}
.entry-list li:last-child { border-bottom: none; }
.entry-list .entry-title { font-weight: 500; font-size: .95rem; }
.entry-list .entry-desc {
  color: var(--muted);
  font-size: .85rem;
  margin-top: .15rem;
}

/* ── Provenance ── */
.provenance {
  margin-top: 2rem;
  padding-top: 1rem;
  border-top: 1px solid var(--border);
  font-family: var(--mono);
  font-size: .73rem;
  color: var(--muted2);
}

/* ── Footer — matches www.3se.info ── */
footer {
  background: var(--ink);
  color: rgba(255,255,255,0.4);
  text-align: center;
  padding: 2rem 4rem;
  font-family: 'DM Sans', sans-serif;
  font-size: 0.82rem;
  letter-spacing: 0.04em;
}
footer a { color: rgba(255,255,255,0.5); text-decoration: none; }
footer a:hover { color: var(--white); text-decoration: none; }
"""

CONNEG_SCRIPT = """
<script>
(function() {
  var ua = (navigator && navigator.userAgent) ? navigator.userAgent : '';
  if (ua && !ua.includes('Mozilla') && !ua.includes('AppleWebKit')) {
    window.location.replace('./index.jsonld');
  }
})();
</script>
"""


def html_shell(title: str, body: str, jsonld: dict | None = None,
               description: str = "") -> str:
    meta_desc = f'<meta name="description" content="{description}">' if description else ""
    ld_script = ""
    if jsonld:
        ld_script = (
                '<script type="application/ld+json">'
                + json.dumps(jsonld, ensure_ascii=False)
                + "</script>"
        )
    conneg = CONNEG_SCRIPT if jsonld else ""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>3SE — Ontology — {title}</title>
  {meta_desc}
  <style>{SHARED_CSS}</style>
  <script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
  <script>mermaid.initialize({{startOnLoad:true, theme:'neutral'}});</script>
  {ld_script}
</head>
<body>
{conneg}
<header>
  <div class="header-inner">
    <a class="logo" href="https://www.3se.info/index.html">
      <svg width="28" height="28" viewBox="0 0 340 340" fill="none" xmlns="http://www.w3.org/2000/svg" style="display:inline-block;vertical-align:middle;margin-right:8px;">
          <!-- Outer edges -->
          <g stroke="#1a5faa" stroke-width="14" stroke-linejoin="round">
            <line x1="170" y1="30" x2="50"  y2="270"/>
            <line x1="170" y1="30" x2="290" y2="270"/>
            <line x1="170" y1="30" x2="170" y2="220"/>
            <line x1="50"  y1="270" x2="290" y2="270"/>
            <line x1="50"  y1="270" x2="170" y2="220"/>
            <line x1="290" y1="270" x2="170" y2="220"/>
          </g>
          <!-- Inner depth edges (dashed) -->
          <g stroke="#1a5faa" stroke-width="8" stroke-dasharray="18 12" opacity="0.45">
            <line x1="170" y1="148" x2="50"  y2="270"/>
            <line x1="170" y1="148" x2="290" y2="270"/>
            <line x1="170" y1="148" x2="170" y2="220"/>
          </g>
          <!-- Nodes -->
          <circle cx="170" cy="30"  r="14" fill="#1a5faa"/>
          <circle cx="50"  cy="270" r="10" fill="#1a5faa" opacity="0.7"/>
          <circle cx="290" cy="270" r="10" fill="#1a5faa" opacity="0.7"/>
          <circle cx="170" cy="220" r="10" fill="#1a5faa" opacity="0.7"/>
        </svg>3<span>SE</span>
    </a>
    <nav>
      <a href="/3se-onto/">Index</a>
      <a href="/3se-onto/terms/">Terms</a>
      <a href="/3se-onto/references/">References</a>
      <a href="/3se-onto/properties/">Properties</a>
    </nav>
  </div>
</header>
<main>
{body}
</main>
<footer>
  <p>
    © 2022 3SE — System, Safety &amp; Security Engineering &nbsp;·&nbsp;
    <a href="https://www.3se.info/">www.3se.info</a> &nbsp;·&nbsp;
    Generated {now}
  </p>
</footer>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Index page — searchable table
# ---------------------------------------------------------------------------

def render_index(se3_terms: list[dict], other_terms: list[dict],
                 references: list[dict],
                 se3_properties: list[dict], other_properties: list[dict]) -> str:
    all_entries: list[dict] = []
    for t in se3_terms:
        all_entries.append({
            "title": t.get("title", ""),
            "type": "3SE Term",
            "status": t.get("status", ""),
            "stem": t["_stem"],
            "dir": "terms",
            "desc": t.get("description", ""),
        })
    for t in other_terms:
        all_entries.append({
            "title": t.get("title", ""),
            "type": "Term",
            "status": t.get("status", ""),
            "stem": t["_stem"],
            "dir": "terms",
            "desc": t.get("description", ""),
        })
    for r in references:
        raw_status, _, _ = resolve_status(r)
        all_entries.append({
            "title": r.get("title", ""),
            "type": "Reference",
            "status": raw_status,
            "stem": r["_stem"],
            "dir": "references",
            "desc": r.get("abstract", ""),
        })
    for p in se3_properties:
        raw_status, _, _ = resolve_status(p)
        all_entries.append({
            "title": p.get("title", ""),
            "type": "3SE Property",
            "status": raw_status,
            "stem": p["_stem"],
            "dir": "properties",
            "desc": p.get("description", ""),
        })
    for p in other_properties:
        raw_status, _, _ = resolve_status(p)
        all_entries.append({
            "title": p.get("title", ""),
            "type": "Property",
            "status": raw_status,
            "stem": p["_stem"],
            "dir": "properties",
            "desc": p.get("description", ""),
        })

    rows = ""
    for e in all_entries:
        status_cell = ""
        if e["status"]:
            # Build a temporary dict to reuse resolve_status
            _tmp = {"status": e["status"], "bibo:status": e["status"]}
            _, s_label, s_color = resolve_status(_tmp)
            if s_label:
                status_cell = (
                    f'<span class="badge" style="color:{s_color};border-color:{s_color}">'
                    f'{s_label}</span>'
                )
        type_style = {
            "3SE Term": "color:var(--text);font-weight:500",
            "Term": "color:var(--text2)",
            "Reference": "color:var(--green)",
            "3SE Property": "color:var(--accent);font-weight:500",
            "Property": "color:var(--muted)",
        }.get(e["type"], "")
        desc = e["desc"][:100] + ("…" if len(e["desc"]) > 100 else "")
        safe_title = e["title"].replace('"', "&quot;")
        safe_desc = e["desc"].replace('"', "&quot;")
        safe_type = e["type"].lower()
        safe_status = e["status"].lower()
        rows += (
            f'<tr data-q="{safe_title.lower()} {safe_desc.lower()}"'
            f' data-type="{safe_type}" data-status="{safe_status}">'
            f'<td><a href="/3se-onto/{e["dir"]}/{e["stem"]}/">{e["title"]}</a></td>'
            f'<td><span style="font-family:var(--mono);font-size:.75rem;{type_style}">'
            f'{e["type"]}</span></td>'
            f'<td>{status_cell}</td>'
            f'<td class="desc">{desc}</td>'
            f'</tr>\n'
        )

    total = len(all_entries)
    body = f"""
<div style="margin-top:3rem; margin-bottom:3rem">
  <p class="section-label">
    The Ontology
  </p>
  <h1>3SE Ontology</h1>
  <p style="margin-top:.75rem;color:var(--muted);font-size:.95rem;max-width:560px">
    A formal, shared vocabulary that aligns concepts across system, safety,
    and security engineering.<br><br>
    {len(se3_terms)} 3SE terms &nbsp;·&nbsp;
    {len(other_terms)} other terms &nbsp;·&nbsp;
    {f'{len(se3_properties)} 3SE properties &nbsp;·&nbsp;' if se3_properties else ''}
    {f'{len(other_properties)} other properties &nbsp;·&nbsp;<br>' if other_properties else ''}
    {len(references)} references.
  </p>
</div>

<div class="filter-bar">
  <input id="search" type="search" placeholder="Search by title or description…">
  <select id="filter-type">
    <option value="">All types</option>
    <option value="3se term">3SE Terms</option>
    <option value="term">Other Terms</option>
    <option value="3se property">3SE Properties</option>
    <option value="property">Other Properties</option>
    <option value="reference">References</option>
  </select>
  <select id="filter-status">
    <option value="">All statuses</option>
    <optgroup label="Term & Property statuses">
      <option value="draft">Draft</option>
      <option value="reviewed">Under Review</option>
      <option value="reviewed">Reviewed</option>
      <option value="approved">Approved</option>
      <option value="reviewed">Under Approval</option>
      <option value="standard">Standard</option>
    </optgroup>
    <optgroup label="Reference statuses">
      <option value="bibo:draft">Draft (bibo)</option>
      <option value="bibo:published">Published</option>
      <option value="bibo:peerReviewed">Peer Reviewed</option>
      <option value="bibo:forthcoming">Forthcoming</option>
      <option value="bibo:unpublished">Unpublished</option>
    </optgroup>
  </select>
  <span id="count" style="font-family:var(--mono);font-size:.75rem;
        color:var(--muted);white-space:nowrap">{total} entries</span>
</div>

<table class="index-table" id="main-table">
  <thead>
    <tr>
      <th>Title</th>
      <th>Type</th>
      <th>Status</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody id="tbody">{rows}</tbody>
</table>
<p id="empty" style="display:none;padding:3rem;text-align:center;
   color:var(--muted);font-family:var(--mono);font-size:.85rem">
  No entries match your search.
</p>

<script>
const rows   = Array.from(document.querySelectorAll('#tbody tr'));
const search = document.getElementById('search');
const fType  = document.getElementById('filter-type');
const fStat  = document.getElementById('filter-status');
const count  = document.getElementById('count');
const empty  = document.getElementById('empty');
const table  = document.getElementById('main-table');

function filter() {{
  const q = search.value.toLowerCase().trim();
  const t = fType.value;
  const s = fStat.value;
  let n = 0;
  rows.forEach(r => {{
    const show = (!q || r.dataset.q.includes(q))
              && (!t || r.dataset.type === t)
              && (!s || r.dataset.status === s);
    r.style.display = show ? '' : 'none';
    if (show) n++;
  }});
  count.textContent = n + (n === 1 ? ' entry' : ' entries');
  empty.style.display = n === 0 ? 'block' : 'none';
  table.style.display  = n === 0 ? 'none'  : '';
}}

search.addEventListener('input', filter);
fType.addEventListener('change', filter);
fStat.addEventListener('change', filter);
</script>
"""
    return html_shell("Index", body,
                      description="3SE Ontology — formal vocabulary for system, safety and security engineering.")


# ---------------------------------------------------------------------------
# Term page
# ---------------------------------------------------------------------------

def render_uri_link(uri: str, label: str | None = None) -> str:
    display = label or stem_from_uri(uri)
    href = href_for_uri(uri)
    if is_internal_uri(uri):
        return f'<a href="{href}">{display}</a>'
    return f'<a href="{uri}" target="_blank" rel="noopener">{display} ↗</a>'


BREAKDOWN_STEM_RE = re.compile(r"^(.+?)-breakdown-structure-3se(?:-[0-9a-f]{16})?$")


def is_breakdown_structure(term: dict) -> str | None:
    """
    Return the decomposed concept name if this term is a breakdown structure,
    or None otherwise. Detection is based on the @id stem.
    e.g. ".../system-breakdown-structure-3se-<UUID>" -> "System"
    """
    term_id = term.get("@id", "")
    stem = term_id.rstrip("/").rsplit("/", 1)[-1]
    m = BREAKDOWN_STEM_RE.match(stem)
    if m:
        return m.group(1).replace("-", " ").title()
    return None


def render_breakdown_diagram(term: dict, terms_index: dict,
                             represents_index: dict | None = None) -> str:
    """
    Render a breakdown structure diagram as a Mermaid flowchart.

    Traverses the breakdown structure's 'related' list, collects
    isComposedOf / isRepresentedBy / allocates / canBe from each related term, and
    also adds the computed inverse 'represents' relation (derived from other terms'
    isRepresentedBy fields via represents_index).

    Emits a Mermaid flowchart TD definition.
    """
    if not is_breakdown_structure(term):
        return ""

    related_uris = term.get("related", [])
    if isinstance(related_uris, str):
        related_uris = [related_uris]
    if not related_uris:
        return ""

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

    edges = []  # (subj_uri, rel, obj_uri)

    for rel_uri in related_uris:
        rel_term = terms_index.get(rel_uri)
        if rel_term is None:
            continue
        # Do NOT pre-register rel_uri as a node — only register it if it
        # actually has structural relations (i.e. appears in at least one edge)
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
        return ""

    # Deduplicate edges (same subject, relation, object may appear from multiple sources)
    edges = list(dict.fromkeys(edges))

    # Deduplicate nodes by label — if two URIs resolve to the same display label,
    # keep only the first one and remap all references to it
    label_to_primary_uri: dict[str, str] = {}  # lower(label) -> first URI seen
    uri_remap: dict[str, str] = {}  # duplicate URI -> primary URI

    for uri in list(node_ids.keys()):
        lbl_lower = node_labels.get(uri, "").lower()
        if lbl_lower in label_to_primary_uri:
            uri_remap[uri] = label_to_primary_uri[lbl_lower]
        else:
            label_to_primary_uri[lbl_lower] = uri

    # Apply remap to edges
    if uri_remap:
        edges = [
            (uri_remap.get(s, s), rel, uri_remap.get(o, o))
            for s, rel, o in edges
        ]
        edges = list(dict.fromkeys(edges))  # deduplicate again after remap
        # Remove remapped URIs from node_ids
        for uri in uri_remap:
            node_ids.pop(uri, None)
            node_labels.pop(uri, None)

    lines = ["flowchart TD"]
    for uri, nid in node_ids.items():
        lbl = node_labels.get(uri, nid).replace('"', "'")
        lines.append(f'    {nid}["{lbl}"]')
    lines.append("")
    for subj_uri, rel, obj_uri in edges:
        s, o = node_id(subj_uri), node_id(obj_uri)
        if rel == "composition":
            lines.append(f"    {s} -->|composed of| {o}")
        elif rel == "representation":
            lines.append(f"    {s} -.->|represented by| {o}")
        elif rel == "allocation":
            lines.append(f"    {s} -.->|allocates| {o}")
        elif rel == "subclassof":
            lines.append(f"    {s} -->|subclass of| {o}")
        elif rel == "exposes":
            lines.append(f"    {s} -.->|exposes| {o}")
        else:
            lines.append(f"    {s} -.->|can be| {o}")

    mermaid_src = "\n".join(lines)
    return (
        '<div class="card" style="margin-top:1.5rem">'
        '<h3 style="margin-bottom:1rem">Structure</h3>'
        f'<div class="mermaid">{mermaid_src}</div>'
        '</div>'
    )


ANALYSIS_BASE_URI = "https://www.3se.info/3se-onto/terms/analysis-3se-069b5a9129c37ebe"
ROLE_BASE_URI = "https://www.3se.info/3se-onto/terms/role-3se-069c451bef157773"
BREAKDOWN_BASE_URI = "https://www.3se.info/3se-onto/terms/breakdown-structure-3se-069d166fa9037b67"
CONCEPTUAL_MODEL_BASE_URI = "https://www.3se.info/3se-onto/terms/conceptual-model-3se-069d3d5560bf7635"


def is_analysis_subclass(term: dict) -> bool:
    """Return True if this term declares subClassOf analysis-3se-069b5a9129c37ebe."""
    subclass = term.get("subClassOf")
    if not subclass:
        return False
    uris = [subclass] if isinstance(subclass, str) else subclass
    return ANALYSIS_BASE_URI in uris


def render_analysis_allocates_diagram(
        term: dict,
        terms_index: dict) -> str:
    """
    Render a Mermaid flowchart showing the allocates relation of the elements
    related to an analysis term (any subclass of analysis-3se).

    For each URI in the term's 'related' list, look up the term in terms_index
    and collect its 'allocates' targets. Emit one node per subject and one node
    per allocated target, connected by a labelled dashed arrow.

    Only rendered when the term is a direct subclass of analysis-3se.
    Returns an empty string when there is nothing to show.
    """
    if not is_analysis_subclass(term):
        return ""

    related_uris = term.get("related", [])
    if isinstance(related_uris, str):
        related_uris = [related_uris]
    if not related_uris:
        return ""

    # -- Node registry (mirrors render_breakdown_diagram) --------------------
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
        return ""

    # Collect subClassOf edges: iterate over the union of related_uris and
    # already-registered nodes so that terms carrying only subClassOf — and
    # no allocates relation of their own — are still included when their
    # parent is registered by the primary allocates pass.
    # The parent guard admits two cases:
    #   (a) parent already registered by the primary pass (e.g. registered
    #       as a subject of its own allocates edges), OR
    #   (b) parent is explicitly in related_uris (e.g. attribute, the direct
    #       superclass of system-attribute, listed as a related term of the
    #       analysis but not itself carrying any allocates edges).
    # The child must be in related_uris or already registered (primary pass).
    # The parent is always admitted — no guard — because the expansion is
    # already bounded by the child being in candidates. This handles the case
    # where the parent (e.g. 'attribute') is neither in related_uris nor
    # registered by the primary pass, but is the direct superclass of a
    # related term (e.g. 'system-attribute') that is registered.
    subclassof_edges = []  # (child_uri, parent_uri)
    registered_uris = set(node_ids.keys())
    candidates = list(dict.fromkeys(list(related_uris) + list(registered_uris)))
    for child_uri in candidates:
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

    # Deduplicate
    allocates_edges = list(dict.fromkeys(allocates_edges))
    subclassof_edges = list(dict.fromkeys(subclassof_edges))

    # Deduplicate nodes by label (same logic as render_breakdown_diagram)
    label_to_primary_uri: dict[str, str] = {}
    uri_remap: dict[str, str] = {}

    for uri in list(node_ids.keys()):
        lbl_lower = node_labels.get(uri, "").lower()
        if lbl_lower in label_to_primary_uri:
            uri_remap[uri] = label_to_primary_uri[lbl_lower]
        else:
            label_to_primary_uri[lbl_lower] = uri

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

    lines = ["flowchart TD"]
    for uri, nid in node_ids.items():
        lbl = node_labels.get(uri, nid).replace('"', "'")
        lines.append(f'    {nid}["{lbl}"]')
    lines.append("")
    for subj_uri, obj_uri in allocates_edges:
        s = node_id(subj_uri)
        o = node_id(obj_uri)
        lines.append(f"    {s} -.->|allocates| {o}")
    for child_uri, parent_uri in subclassof_edges:
        c = node_id(child_uri)
        p = node_id(parent_uri)
        lines.append(f"    {c} -->|subclass of| {p}")

    mermaid_src = "\n".join(lines)
    return (
        '<div class="card" style="margin-top:1.5rem">'
        '<h3 style="margin-bottom:1rem">Allocations</h3>'
        f'<div class="mermaid">{mermaid_src}</div>'
        '</div>'
    )


def render_classification_diagram(
        term: dict,
        superclass_index: dict[str, list[dict]],
        terms_index: dict,
        represents_index: dict | None = None) -> str:
    """
    Render a Mermaid flowchart showing the classification of the considered term.

    The diagram contains:
    1. All terms that declare subClassOf the considered term (direct subclasses),
       each linked to the considered term with a 'subclass of' arrow.
    2. For each subclass found in (1), and for the considered term itself,
       any allocates targets, each linked with an 'allocates' arrow.
    3. For each subclass found in (1), and for the considered term itself,
       any isRepresentedBy targets AND their computed inverse 'represents' relations,
       each linked with a 'represented by' / 'represents' arrow.

    Only rendered when at least one subclass exists.
    Returns an empty string when there is nothing to show.
    """
    term_uri = term.get("@id", "")
    if not term_uri:
        return ""

    subclasses = superclass_index.get(term_uri, [])
    if not subclasses:
        return ""

    # ── Node registry (mirrors existing diagram helpers) ──────────────────
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

    # Pre-register the considered term as the root node
    node_id(term_uri)
    label_for(term_uri)

    subclass_edges = []  # (child_uri, parent_uri)
    allocation_edges = []  # (subject_uri, target_uri)
    representation_edges = []  # (subject_uri, target_uri) — isRepresentedBy

    # ── (1) Subclass edges ────────────────────────────────────────────────
    for subclass_term in sorted(subclasses, key=lambda t: t.get("title", "")):
        child_uri = subclass_term.get("@id", "")
        if not child_uri:
            continue
        node_id(child_uri)
        label_for(child_uri)
        subclass_edges.append((child_uri, term_uri))

    # ── (2) Allocates edges — from considered term and all its subclasses ─
    for subject_uri in [term_uri] + [s.get("@id", "") for s in subclasses]:
        if not subject_uri:
            continue
        subject_data = terms_index.get(subject_uri) or term
        allocates = subject_data.get("allocates") or []
        if isinstance(allocates, str):
            allocates = [allocates]
        for obj_uri in allocates:
            node_id(subject_uri)
            label_for(subject_uri)
            node_id(obj_uri)
            label_for(obj_uri)
            allocation_edges.append((subject_uri, obj_uri))

    # ── (3) Representation edges — isRepresentedBy (direct) and its inverse ─
    # (a) Direct: subject isRepresentedBy target
    for subject_uri in [term_uri] + [s.get("@id", "") for s in subclasses]:
        if not subject_uri:
            continue
        subject_data = terms_index.get(subject_uri) or term
        is_rep_by = subject_data.get("isRepresentedBy") or []
        if isinstance(is_rep_by, str):
            is_rep_by = [is_rep_by]
        for obj_uri in is_rep_by:
            node_id(subject_uri)
            label_for(subject_uri)
            node_id(obj_uri)
            label_for(obj_uri)
            representation_edges.append((subject_uri, obj_uri))
    # (b) Inverse: any term that declares isRepresentedBy pointing at
    #     the considered term or one of its subclasses is "represented by"
    #     that node — so we add an edge (represented_term → representer)
    if represents_index:
        for representer_uri in [term_uri] + [s.get("@id", "") for s in subclasses]:
            if not representer_uri:
                continue
            for represented_term in (represents_index.get(representer_uri) or []):
                represented_uri = represented_term.get("@id", "")
                if represented_uri:
                    node_id(represented_uri)
                    label_for(represented_uri)
                    node_id(representer_uri)
                    label_for(representer_uri)
                    representation_edges.append((represented_uri, representer_uri))

    if not subclass_edges and not allocation_edges and not representation_edges:
        return ""

    # Deduplicate
    subclass_edges = list(dict.fromkeys(subclass_edges))
    allocation_edges = list(dict.fromkeys(allocation_edges))
    representation_edges = list(dict.fromkeys(representation_edges))

    # Deduplicate nodes by label (same logic as existing diagram functions)
    label_to_primary_uri: dict[str, str] = {}
    uri_remap: dict[str, str] = {}

    for uri in list(node_ids.keys()):
        lbl_lower = node_labels.get(uri, "").lower()
        if lbl_lower in label_to_primary_uri:
            uri_remap[uri] = label_to_primary_uri[lbl_lower]
        else:
            label_to_primary_uri[lbl_lower] = uri

    if uri_remap:
        subclass_edges = [
            (uri_remap.get(s, s), uri_remap.get(o, o))
            for s, o in subclass_edges
        ]
        allocation_edges = [
            (uri_remap.get(s, s), uri_remap.get(o, o))
            for s, o in allocation_edges
        ]
        representation_edges = [
            (uri_remap.get(s, s), uri_remap.get(o, o))
            for s, o in representation_edges
        ]
        subclass_edges = list(dict.fromkeys(subclass_edges))
        allocation_edges = list(dict.fromkeys(allocation_edges))
        representation_edges = list(dict.fromkeys(representation_edges))
        for uri in uri_remap:
            node_ids.pop(uri, None)
            node_labels.pop(uri, None)

    lines = ["flowchart TD"]
    for uri, nid in node_ids.items():
        lbl = node_labels.get(uri, nid).replace('"', "'")
        lines.append(f'    {nid}["{lbl}"]')
    lines.append("")
    for child_uri, parent_uri in subclass_edges:
        c, p = node_id(child_uri), node_id(parent_uri)
        lines.append(f"    {c} -->|subclass of| {p}")
    for subj_uri, obj_uri in allocation_edges:
        s, o = node_id(subj_uri), node_id(obj_uri)
        lines.append(f"    {s} -.->|allocates| {o}")
    for subj_uri, obj_uri in representation_edges:
        s, o = node_id(subj_uri), node_id(obj_uri)
        lines.append(f"    {s} -.->|represented by| {o}")

    mermaid_src = "\n".join(lines)
    return (
        '<div class="card" style="margin-top:1.5rem">'
        '<h3 style="margin-bottom:1rem">Classification</h3>'
        f'<div class="mermaid">{mermaid_src}</div>'
        '</div>'
    )


def render_architecture_diagram(term: dict, terms_index: dict) -> str:
    """
    Render a Mermaid flowchart for terms whose title contains 'architecture'
    (case-insensitive, e.g. 'Functional architecture', 'Physical architecture').

    For each URI in the term's 'related' list, look up the related term and
    collect three kinds of structural relations it carries:

    - 'exposes': source element exposes an interface
          related_term -.->|exposes| interface_target
    - 'allocates': source element allocates a target (direct, or via interface)
          related_term -.->|allocates| target
    - 'isComposedOf': source element is composed of a component
          related_term -->|composed of| component

    The architecture term itself is NOT included as a node — the diagram shows
    the elements related to this architecture and their structural relations.

    Only rendered when at least one related term carries one of these fields.
    Returns an empty string otherwise.
    """
    title = term.get("title", "")
    if "architecture" not in title.lower():
        return ""

    term_uri = term.get("@id", "")
    if not term_uri:
        return ""

    related_uris = term.get("related", [])
    if isinstance(related_uris, str):
        related_uris = [related_uris]
    if not related_uris:
        return ""

    # ── Node registry (mirrors existing diagram helpers) ──────────────────
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
            t = entry.get("title", "")
            lbl = t.split(" - ", 1)[0].strip() if " - " in t else t
        else:
            stem = uri.rstrip("/").rsplit("/", 1)[-1]
            stem = re.sub(r"-[0-9a-f]{16}$", "", stem)
            stem = re.sub(r"-3se$", "", stem)
            lbl = stem.replace("-", " ").title()
        node_labels[uri] = lbl
        return lbl

    exposes_edges = []  # (source_uri, interface_uri)
    allocates_edges = []  # (source_uri, allocated_uri)
    composed_edges = []  # (source_uri, component_uri)

    # ── Scan related terms for exposes, allocates, and isComposedOf ───────
    for rel_uri in related_uris:
        rel_term = terms_index.get(rel_uri)
        if rel_term is None:
            continue

        # exposes: related_term -.->|exposes| interface
        exposes = rel_term.get("exposes") or []
        if isinstance(exposes, str):
            exposes = [exposes]
        for interface_uri in exposes:
            node_id(rel_uri)
            label_for(rel_uri)
            node_id(interface_uri)
            label_for(interface_uri)
            exposes_edges.append((rel_uri, interface_uri))

            # allocates from the interface term: interface -.->|allocates| target
            iface_term = terms_index.get(interface_uri)
            if iface_term:
                iface_allocates = iface_term.get("allocates") or []
                if isinstance(iface_allocates, str):
                    iface_allocates = [iface_allocates]
                for alloc_uri in iface_allocates:
                    node_id(interface_uri)
                    label_for(interface_uri)
                    node_id(alloc_uri)
                    label_for(alloc_uri)
                    allocates_edges.append((interface_uri, alloc_uri))

        # allocates: related_term -.->|allocates| target
        allocates = rel_term.get("allocates") or []
        if isinstance(allocates, str):
            allocates = [allocates]
        for alloc_uri in allocates:
            node_id(rel_uri)
            label_for(rel_uri)
            node_id(alloc_uri)
            label_for(alloc_uri)
            allocates_edges.append((rel_uri, alloc_uri))

        # isComposedOf: related_term -->|composed of| component
        composed = rel_term.get("isComposedOf") or []
        if isinstance(composed, str):
            composed = [composed]
        for comp_uri in composed:
            node_id(rel_uri)
            label_for(rel_uri)
            node_id(comp_uri)
            label_for(comp_uri)
            composed_edges.append((rel_uri, comp_uri))

    if not exposes_edges and not allocates_edges and not composed_edges:
        return ""

    # Deduplicate
    exposes_edges = list(dict.fromkeys(exposes_edges))
    allocates_edges = list(dict.fromkeys(allocates_edges))
    composed_edges = list(dict.fromkeys(composed_edges))

    # Deduplicate nodes by label (same logic as existing diagram functions)
    label_to_primary_uri: dict[str, str] = {}
    uri_remap: dict[str, str] = {}

    for uri in list(node_ids.keys()):
        lbl_lower = node_labels.get(uri, "").lower()
        if lbl_lower in label_to_primary_uri:
            uri_remap[uri] = label_to_primary_uri[lbl_lower]
        else:
            label_to_primary_uri[lbl_lower] = uri

    if uri_remap:
        exposes_edges = [
            (uri_remap.get(s, s), uri_remap.get(o, o))
            for s, o in exposes_edges
        ]
        allocates_edges = [
            (uri_remap.get(s, s), uri_remap.get(o, o))
            for s, o in allocates_edges
        ]
        composed_edges = [
            (uri_remap.get(s, s), uri_remap.get(o, o))
            for s, o in composed_edges
        ]
        exposes_edges = list(dict.fromkeys(exposes_edges))
        allocates_edges = list(dict.fromkeys(allocates_edges))
        composed_edges = list(dict.fromkeys(composed_edges))
        for uri in uri_remap:
            node_ids.pop(uri, None)
            node_labels.pop(uri, None)

    lines = ["flowchart TD"]
    for uri, nid in node_ids.items():
        lbl = node_labels.get(uri, nid).replace('"', "'")
        lines.append(f'    {nid}["{lbl}"]')
    lines.append("")
    for src_uri, comp_uri in composed_edges:
        s, c = node_id(src_uri), node_id(comp_uri)
        lines.append(f"    {s} -->|composed of| {c}")
    for src_uri, iface_uri in exposes_edges:
        s, i = node_id(src_uri), node_id(iface_uri)
        lines.append(f"    {s} -.->|exposes| {i}")
    for src_uri, alloc_uri in allocates_edges:
        s, a = node_id(src_uri), node_id(alloc_uri)
        lines.append(f"    {s} -.->|allocates| {a}")

    mermaid_src = "\n".join(lines)
    return (
        '<div class="card" style="margin-top:1.5rem">'
        '<h3 style="margin-bottom:1rem">Architecture</h3>'
        f'<div class="mermaid">{mermaid_src}</div>'
        '</div>'
    )


def render_role_analysis_matrix(
        term: dict,
        superclass_index: dict[str, list[dict]]
) -> str:
    """
    Render a responsibility matrix on four pages:

    Role - 3SE
        rows  = child roles   (subclasses of role-3se)
        cols  = child analyses (subclasses of analysis-3se)
               + child breakdown structures (subclasses of breakdown-structure-3se)
               + child conceptual models   (subclasses of conceptual-model-3se)
               with a column-group separator between each set

    Analysis - 3SE
        rows  = child analyses (subclasses of analysis-3se)
        cols  = child roles    (subclasses of role-3se)

    Breakdown structure - 3SE
        rows  = child breakdown structures (subclasses of breakdown-structure-3se)
        cols  = child roles                (subclasses of role-3se)

    Conceptual model - 3SE
        rows  = child conceptual models (subclasses of conceptual-model-3se)
        cols  = child roles             (subclasses of role-3se)

    Cell values are drawn from the role's isResponsibleFor / isAccountableFor /
    isSupporting fields.

    Cell values:
      R  — isResponsibleFor
      A  — isAccountableFor
      S  — isSupporting
      —  — no relation
    """
    term_id = term.get("@id", "")
    title = term.get("title", "")

    is_role_page = title.startswith("Role - 3SE")
    is_analysis_page = title.startswith("Analysis - 3SE")
    is_breakdown_page = title.startswith("Breakdown structure - 3SE")
    is_model_page = title.startswith("Conceptual model - 3SE")

    if not (is_role_page or is_analysis_page or is_breakdown_page or is_model_page):
        return ""

    # ── Collect child roles ──────────────────────────────────────────────
    if is_role_page:
        child_roles = superclass_index.get(term_id, [])
    else:
        child_roles = superclass_index.get(ROLE_BASE_URI, [])

    if not child_roles:
        return ""
    child_roles = sorted(child_roles, key=lambda t: t.get("title", ""))

    # ── Collect child analyses ───────────────────────────────────────────
    if is_analysis_page:
        child_analyses = superclass_index.get(term_id, [])
    else:
        child_analyses = superclass_index.get(ANALYSIS_BASE_URI, [])
    child_analyses = sorted(child_analyses or [], key=lambda t: t.get("title", ""))

    # ── Collect child breakdown structures ───────────────────────────────
    if is_breakdown_page:
        child_breakdowns = superclass_index.get(term_id, [])
    else:
        child_breakdowns = superclass_index.get(BREAKDOWN_BASE_URI, [])
    child_breakdowns = sorted(child_breakdowns or [], key=lambda t: t.get("title", ""))

    # ── Collect child conceptual models ──────────────────────────────────
    if is_model_page:
        child_models = superclass_index.get(term_id, [])
    else:
        child_models = superclass_index.get(CONCEPTUAL_MODEL_BASE_URI, [])
    child_models = sorted(child_models or [], key=lambda t: t.get("title", ""))

    # Guard: each page needs the columns it is responsible for
    if is_role_page and not child_analyses and not child_breakdowns and not child_models:
        return ""
    if is_analysis_page and not child_analyses:
        return ""
    if is_breakdown_page and not child_breakdowns:
        return ""
    if is_model_page and not child_models:
        return ""

    # ── Shared helpers ────────────────────────────────────────────────────
    def short_label(t: str) -> str:
        return t.split(" - ")[0].strip()

    def cell_html(val: str, first_in_group: bool = False) -> str:
        border = "border-left:2px solid var(--border2);" if first_in_group else ""
        if val == "R":
            return (
                f'<td style="text-align:center;padding:.4rem .5rem;{border}">'
                '<span style="font-family:var(--mono);font-size:.8rem;'
                'font-weight:700;color:var(--text)">R</span></td>'
            )
        if val == "A":
            return (
                f'<td style="text-align:center;padding:.4rem .5rem;{border}">'
                '<span style="font-family:var(--mono);font-size:.8rem;'
                'color:var(--text2)">A</span></td>'
            )
        if val == "S":
            return (
                f'<td style="text-align:center;padding:.4rem .5rem;{border}">'
                '<span style="font-family:var(--mono);font-size:.8rem;'
                'color:var(--muted)">S</span></td>'
            )
        return f'<td style="text-align:center;padding:.4rem .5rem;{border}color:var(--border2)">—</td>'

    def col_header(entry: dict) -> str:
        return (
            f'<th style="font-family:var(--mono);font-size:.65rem;font-weight:600;'
            f'color:var(--muted);letter-spacing:.06em;text-transform:uppercase;'
            f'padding:.4rem .5rem;white-space:nowrap;'
            f'writing-mode:vertical-rl;transform:rotate(180deg);min-width:2rem">'
            f'<a href="{href_for_uri(entry.get("@id", ""))}" '
            f'style="color:inherit;text-decoration:none">'
            f'{short_label(entry.get("title", ""))}</a></th>'
        )

    def group_header_th(label: str, span: int, first: bool = False) -> str:
        border = "border-left:2px solid var(--border2);" if not first else ""
        return (
            f'<th colspan="{span}" style="{border}font-family:var(--mono);'
            f'font-size:.6rem;font-weight:600;color:var(--accent);'
            f'letter-spacing:.1em;text-transform:uppercase;'
            f'padding:.2rem .5rem;text-align:center;'
            f'border-bottom:1px solid var(--border2)">{label}</th>'
        )

    # ── Build lookup: role_uri → {col_uri: "R"|"A"|"S"|""} ───────────────
    def build_role_matrix(col_uris: set[str]) -> dict[str, dict[str, str]]:
        matrix: dict[str, dict[str, str]] = {}
        for role in child_roles:
            role_uri = role.get("@id", "")
            row: dict[str, str] = {u: "" for u in col_uris}
            for u in role.get("isResponsibleFor", []):
                if u in col_uris:
                    row[u] = "R"
            for u in role.get("isAccountableFor", []):
                if u in col_uris:
                    row[u] = "A"
            for u in role.get("isSupporting", []):
                if u in col_uris:
                    row[u] = "S"
            matrix[role_uri] = row
        return matrix

    # ── Build lookup: row_uri → {role_uri: "R"|"A"|"S"|""} ──────────────
    # Used for Analysis, Breakdown structure and Conceptual model pages where
    # row items are looked up against each role's typed fields.
    def build_row_matrix(row_uris: list[str]) -> dict[str, dict[str, str]]:
        roles_uris = {r.get("@id", "") for r in child_roles}
        matrix: dict[str, dict[str, str]] = {}
        for row_uri in row_uris:
            row: dict[str, str] = {r_uri: "" for r_uri in roles_uris}
            for role in child_roles:
                role_id = role.get("@id", "")
                for u in role.get("isResponsibleFor", []):
                    if u == row_uri:
                        row[role_id] = "R"
                for u in role.get("isAccountableFor", []):
                    if u == row_uri:
                        row[role_id] = "A"
                for u in role.get("isSupporting", []):
                    if u == row_uri:
                        row[role_id] = "S"
            matrix[row_uri] = row
        return matrix

    # ── PAGE: Role - 3SE ─────────────────────────────────────────────────
    # rows = roles, cols = analyses | breakdown structures | conceptual models
    if is_role_page:
        analysis_uris = {a.get("@id", "") for a in child_analyses}
        breakdown_uris = {b.get("@id", "") for b in child_breakdowns}
        model_uris = {m.get("@id", "") for m in child_models}
        all_col_uris = analysis_uris | breakdown_uris | model_uris
        matrix = build_role_matrix(all_col_uris)

        table_rows = ""
        for role in child_roles:
            role_uri = role.get("@id", "")
            role_href = href_for_uri(role_uri)
            role_name = short_label(role.get("title", ""))
            row_data = matrix[role_uri]

            analysis_cells = "".join(
                cell_html(row_data.get(a.get("@id", ""), ""), first_in_group=(i == 0 and False))
                for i, a in enumerate(child_analyses)
            )
            breakdown_cells = "".join(
                cell_html(row_data.get(b.get("@id", ""), ""), first_in_group=(i == 0 and bool(child_analyses)))
                for i, b in enumerate(child_breakdowns)
            )
            model_cells = "".join(
                cell_html(row_data.get(m.get("@id", ""), ""),
                          first_in_group=(i == 0 and bool(child_analyses or child_breakdowns)))
                for i, m in enumerate(child_models)
            )

            table_rows += (
                f'<tr style="border-bottom:1px solid var(--border)">'
                f'<td style="padding:.4rem .75rem;font-size:.88rem;white-space:nowrap;'
                f'position:sticky;left:0;z-index:2;background:var(--white)">'
                f'<a href="{role_href}">{role_name}</a></td>'
                f'{analysis_cells}{breakdown_cells}{model_cells}</tr>'
            )

        # Column-group labels above the rotated column headers
        group_row = '<tr>'
        group_row += '<th style="position:sticky;left:0;z-index:3;background:var(--white)"></th>'
        if child_analyses:
            group_row += group_header_th("Analyses", len(child_analyses), first=True)
        if child_breakdowns:
            group_row += group_header_th("Breakdown structures", len(child_breakdowns),
                                         first=not child_analyses)
        if child_models:
            group_row += group_header_th("Models", len(child_models),
                                         first=not child_analyses and not child_breakdowns)
        group_row += '</tr>'

        col_heads_html = (
                "".join(col_header(a) for a in child_analyses)
                + "".join(col_header(b) for b in child_breakdowns)
                + "".join(col_header(m) for m in child_models)
        )
        thead_html = (
            f'{group_row}'
            f'<tr><th style="padding:.4rem .75rem;text-align:left;font-family:var(--mono);'
            f'font-size:.65rem;font-weight:600;color:var(--muted);letter-spacing:.06em;'
            f'text-transform:uppercase;position:sticky;left:0;z-index:3;'
            f'background:var(--white)">Role</th>{col_heads_html}</tr>'
        )
        matrix_title = "Role × Analysis / Breakdown structure / Model responsibility matrix"

    # ── PAGE: Analysis - 3SE ─────────────────────────────────────────────
    # rows = analyses, cols = roles
    elif is_analysis_page:
        if not child_analyses:
            return ""
        matrix = build_row_matrix([a.get("@id", "") for a in child_analyses])
        col_heads_html = "".join(col_header(r) for r in child_roles)
        table_rows = ""
        for analysis in child_analyses:
            analysis_uri = analysis.get("@id", "")
            analysis_href = href_for_uri(analysis_uri)
            analysis_name = short_label(analysis.get("title", ""))
            cells = "".join(cell_html(matrix[analysis_uri].get(r.get("@id", ""), ""))
                            for r in child_roles)
            table_rows += (
                f'<tr style="border-bottom:1px solid var(--border)">'
                f'<td style="padding:.4rem .75rem;font-size:.88rem;white-space:nowrap;'
                f'position:sticky;left:0;z-index:2;background:var(--white)">'
                f'<a href="{analysis_href}">{analysis_name}</a></td>'
                f'{cells}</tr>'
            )
        thead_html = (
            f'<tr><th style="padding:.4rem .75rem;text-align:left;font-family:var(--mono);'
            f'font-size:.65rem;font-weight:600;color:var(--muted);letter-spacing:.06em;'
            f'text-transform:uppercase;position:sticky;left:0;z-index:3;'
            f'background:var(--white)">Analysis</th>{col_heads_html}</tr>'
        )
        matrix_title = "Analysis × Role responsibility matrix"

    # ── PAGE: Breakdown structure - 3SE ──────────────────────────────────
    # rows = breakdown structures, cols = roles
    elif is_breakdown_page:
        if not child_breakdowns:
            return ""
        matrix = build_row_matrix([b.get("@id", "") for b in child_breakdowns])
        col_heads_html = "".join(col_header(r) for r in child_roles)
        table_rows = ""
        for bd in child_breakdowns:
            bd_uri = bd.get("@id", "")
            bd_href = href_for_uri(bd_uri)
            bd_name = short_label(bd.get("title", ""))
            cells = "".join(cell_html(matrix[bd_uri].get(r.get("@id", ""), ""))
                            for r in child_roles)
            table_rows += (
                f'<tr style="border-bottom:1px solid var(--border)">'
                f'<td style="padding:.4rem .75rem;font-size:.88rem;white-space:nowrap;'
                f'position:sticky;left:0;z-index:2;background:var(--white)">'
                f'<a href="{bd_href}">{bd_name}</a></td>'
                f'{cells}</tr>'
            )
        thead_html = (
            f'<tr><th style="padding:.4rem .75rem;text-align:left;font-family:var(--mono);'
            f'font-size:.65rem;font-weight:600;color:var(--muted);letter-spacing:.06em;'
            f'text-transform:uppercase;position:sticky;left:0;z-index:3;'
            f'background:var(--white)">Breakdown structure</th>{col_heads_html}</tr>'
        )
        matrix_title = "Breakdown structure × Role responsibility matrix"

    # ── PAGE: Conceptual model - 3SE ─────────────────────────────────────
    # rows = conceptual models, cols = roles
    else:
        if not child_models:
            return ""
        matrix = build_row_matrix([m.get("@id", "") for m in child_models])
        col_heads_html = "".join(col_header(r) for r in child_roles)
        table_rows = ""
        for model in child_models:
            model_uri = model.get("@id", "")
            model_href = href_for_uri(model_uri)
            model_name = short_label(model.get("title", ""))
            cells = "".join(cell_html(matrix[model_uri].get(r.get("@id", ""), ""))
                            for r in child_roles)
            table_rows += (
                f'<tr style="border-bottom:1px solid var(--border)">'
                f'<td style="padding:.4rem .75rem;font-size:.88rem;white-space:nowrap;'
                f'position:sticky;left:0;z-index:2;background:var(--white)">'
                f'<a href="{model_href}">{model_name}</a></td>'
                f'{cells}</tr>'
            )
        thead_html = (
            f'<tr><th style="padding:.4rem .75rem;text-align:left;font-family:var(--mono);'
            f'font-size:.65rem;font-weight:600;color:var(--muted);letter-spacing:.06em;'
            f'text-transform:uppercase;position:sticky;left:0;z-index:3;'
            f'background:var(--white)">Model</th>{col_heads_html}</tr>'
        )
        matrix_title = "Model × Role responsibility matrix"

    # ── Legend & wrapper ─────────────────────────────────────────────────
    legend = (
        '<p style="margin-top:.75rem;font-family:var(--mono);font-size:.72rem;'
        'color:var(--muted)">'
        '<strong style="color:var(--text)">R</strong> responsible &nbsp;·&nbsp; '
        '<strong style="color:var(--text2)">A</strong> accountable &nbsp;·&nbsp; '
        '<strong style="color:var(--muted)">S</strong> supporting'
        '</p>'
    )

    return f"""
<div class="card" style="margin-top:1.5rem">
  <h3 style="margin-bottom:1rem">{matrix_title}</h3>
  <div style="overflow-x:auto">
    <table style="border-collapse:collapse;min-width:100%">
      <thead>{thead_html}</thead>
      <tbody>{table_rows}</tbody>
    </table>
  </div>
  {legend}
</div>"""


def render_term_page(term: dict, ref_index: dict, superclass_index: dict | None = None,
                     terms_index: dict[str, dict] | None = None,
                     represents_index: dict[str, list[dict]] | None = None,
                     allocated_by_index: dict[str, list[dict]] | None = None) -> str:
    title = term.get("title", "*(untitled)*")
    status = term.get("status", "")
    deprecated = term.get("deprecated", False)
    jsonld = clean_jsonld(term)

    # Status + deprecated badges
    badges = ""
    _, s_label, s_color = resolve_status(term)
    if s_label:
        badges += (f'<span class="badge" style="color:{s_color};border-color:{s_color}'
                   f';margin-left:.75rem">{s_label}</span>')
    if deprecated:
        badges += ('<span class="badge" style="color:#ef4444;border-color:#ef4444'
                   ';margin-left:.5rem">Deprecated</span>')

    superseded = term.get("superseded_by", "")
    superseded_html = ""
    if superseded:
        superseded_html = (
            f'<p style="margin-top:.75rem;font-size:.88rem;color:var(--muted)">'
            f'Superseded by {render_uri_link(superseded)}</p>'
        )

    aliases = term.get("aliases", [])
    aliases_html = ""
    if aliases:
        aliases_html = (
            f'<p style="margin-top:.5rem;font-size:.85rem;color:var(--muted)">'
            f'Also known as: {", ".join(aliases)}</p>'
        )

    id_uri = term.get("@id", "")
    id_html = (
        f'<p style="margin-top:.35rem;font-family:var(--mono);font-size:.72rem;'
        f'color:var(--muted2)">{id_uri}</p>'
    ) if id_uri else ""

    description_html = ""
    if desc := term.get("description"):
        desc_escaped = desc.replace("\n", "<br>")
        description_html = f'<blockquote class="definition">{desc_escaped}</blockquote>'

    # Breakdown structure diagram (only for breakdown structure terms)
    diagram_html = render_breakdown_diagram(term, terms_index or {},
                                            represents_index or {})

    # Allocates diagram (only for subclasses of analysis-3se)
    analysis_allocates_html = render_analysis_allocates_diagram(
        term, terms_index or {})

    # Classification diagram (subclasses + their allocates targets)
    classification_html = render_classification_diagram(
        term, superclass_index or {}, terms_index or {},
              represents_index or {})

    # Architecture diagram (for terms containing 'Architecture')
    architecture_html = render_architecture_diagram(
        term, terms_index or {})

    # Role × Analysis matrix (only for the Role - 3SE page)
    role_matrix_html = render_role_analysis_matrix(
        term, superclass_index or {})

    notes_html = ""
    if notes := term.get("notes"):
        notes_html = f"""
        <div class="card" style="border-left:3px solid var(--text);border-top:none;
             border-right:none;border-bottom:none;border-radius:0;
             background:var(--bg);padding:1rem 1.25rem;margin-top:1.5rem">
          <p class="section-label" style="margin-bottom:.4rem">Notes</p>
          <p style="font-size:.92rem;color:var(--text2)">{notes}</p>
        </div>"""

    # Hierarchical relations
    def rel_rows(fields_labels):
        out = ""
        for field, label in fields_labels:
            items = term.get(field, [])
            if not items:
                continue
            links = []
            for item in items:
                if isinstance(item, str):
                    uri = item
                    display = None
                else:
                    uri = item.get("@id", "")
                    display = item.get("prefLabel")
                links.append(render_uri_link(uri, display))
            out += (
                f'<tr>'
                f'<td>{label}</td>'
                f'<td>{SEP.join(links)}</td>'
                f'</tr>'
            )
        return out

    hier = rel_rows([("broader", "Broader"), ("narrower", "Narrower"), ("related", "Related")])

    # BFO subclass relation
    bfo_html = ""
    subclass = term.get("subClassOf")
    if subclass:
        uris = [subclass] if isinstance(subclass, str) else subclass
        links = [render_uri_link(uri) for uri in uris]
        bfo_html += (
            f'<tr>'
            f'<td>Subclass of</td>'
            f'<td>{SEP.join(links)}</td>'
            f'</tr>'
        )

    # superClassOf (computed inverse)
    if superclass_index:
        term_id = term.get("@id", "")
        subclasses = superclass_index.get(term_id, [])
        if subclasses:
            links = [render_uri_link(t.get("@id", "")) for t in subclasses]
            bfo_html += (
                f'<tr>'
                f'<td>Superclass of</td>'
                f'<td>{SEP.join(links)}</td>'
                f'</tr>'
            )

    # represents (computed inverse of isRepresentedBy)
    # If other terms declare isRepresentedBy pointing at this term,
    # then this term "represents" those other terms.
    if represents_index:
        term_id = term.get("@id", "")
        represented_terms = represents_index.get(term_id, [])
        if represented_terms:
            links = [render_uri_link(t.get("@id", "")) for t in represented_terms]
            bfo_html += (
                f'<tr>'
                f'<td>Represents</td>'
                f'<td>{SEP.join(links)}</td>'
                f'</tr>'
            )

    # Breakdown structure constituent relations (shown on individual concept pages)
    for field, label in BREAKDOWN_RELATION_LABELS.items():
        val = term.get(field)
        if not val:
            continue
        uris = [val] if isinstance(val, str) else val
        links = [render_uri_link(uri) for uri in uris]
        bfo_html += (
            f'<tr>'
            f'<td>{label}</td>'
            f'<td>{SEP.join(links)}</td>'
            f'</tr>'
        )

    # Allocated by (computed inverse of allocates)
    if allocated_by_index:
        term_id = term.get("@id", "")
        allocating_terms = allocated_by_index.get(term_id, [])
        if allocating_terms:
            links = [render_uri_link(t.get("@id", "")) for t in allocating_terms]
            bfo_html += (
                f'<tr>'
                f'<td>Allocated by</td>'
                f'<td>{SEP.join(links)}</td>'
                f'</tr>'
            )

    # Role relations (isResponsibleFor / isAccountableFor / isSupporting)
    role_html = ""
    for field, label in ROLE_RELATION_LABELS.items():
        val = term.get(field)
        if not val:
            continue
        uris = [val] if isinstance(val, str) else val
        links = [render_uri_link(uri) for uri in uris]
        role_html += (
            f'<tr>'
            f'<td>{label}</td>'
            f'<td>{SEP.join(links)}</td>'
            f'</tr>'
        )

    # Exposure relations (isExposedBy)
    exposure_html = ""
    for field, label in EXPOSURE_RELATION_LABELS.items():
        val = term.get(field)
        if not val:
            continue
        uris = [val] if isinstance(val, str) else val
        links = [render_uri_link(uri) for uri in uris]
        exposure_html += (
            f'<tr>'
            f'<td>{label}</td>'
            f'<td>{SEP.join(links)}</td>'
            f'</tr>'
        )

    match = rel_rows([
        ("exactMatch", "Exact match"), ("closeMatch", "Close match"),
        ("broadMatch", "Broad match"), ("narrowMatch", "Narrow match"),
        ("relatedMatch", "Related match"),
    ])
    relations_html = ""
    if hier or bfo_html or role_html or exposure_html or match:
        sep1 = '<tr><td colspan="2" style="padding:.25rem 0"></td></tr>' if hier and (
                bfo_html or role_html or exposure_html or match) else ""
        sep2 = '<tr><td colspan="2" style="padding:.25rem 0"></td></tr>' if bfo_html and (
                role_html or exposure_html or match) else ""
        sep3 = '<tr><td colspan="2" style="padding:.25rem 0"></td></tr>' if role_html and (
                exposure_html or match) else ""
        sep4 = '<tr><td colspan="2" style="padding:.25rem 0"></td></tr>' if exposure_html and match else ""
        relations_html = f"""
        <div class="card" style="margin-top:1.5rem">
          <h3 style="margin-bottom:1rem">Relations</h3>
          <table class="relations-table">{hier}{sep1}{bfo_html}{sep2}{role_html}{sep3}{exposure_html}{sep4}{match}</table>
        </div>"""

    # isReferencedBy
    refs_html = ""
    if is_ref_by := term.get("isReferencedBy", []):
        ref_links = []
        for uri in is_ref_by:
            ref = ref_index.get(uri)
            label = ref.get("title", stem_from_uri(uri)) if ref else stem_from_uri(uri)
            ref_links.append(render_uri_link(uri, label))
        refs_html = f"""
        <div class="card" style="margin-top:1.5rem">
          <h3 style="margin-bottom:.75rem">Source References</h3>
          <p style="font-size:.9rem">{SEP.join(ref_links)}</p>
        </div>"""

    # Provenance
    prov = []
    if c := term.get("entryCreated"):   prov.append(f"Created {c}")
    if m := term.get("entryModified"):  prov.append(f"Modified {m}")
    if cr := agent_names(term.get("entryCreator")): prov.append(f"by {', '.join(cr)}")
    prov_html = f'<div class="provenance">{SEP.join(prov)}</div>' if prov else ""

    body = f"""
<nav class="breadcrumb">
  <a href="/3se-onto/">Index</a>
  <span>/</span>
  <a href="/3se-onto/terms/">Terms</a>
  <span>/</span>
  <span>{title}</span>
</nav>

<div style="margin-bottom:2rem">
  <div style="display:flex;align-items:baseline;gap:.75rem;flex-wrap:wrap">
    <h1>{title}</h1>{badges}
  </div>
  {id_html}
  {aliases_html}
  {superseded_html}
  {description_html}
</div>

{diagram_html}
{analysis_allocates_html}
{classification_html}
{architecture_html}
{role_matrix_html}
{notes_html}
{relations_html}
{refs_html}

<div class="card" style="margin-top:1.5rem">
  <h3 style="margin-bottom:.75rem">JSON-LD</h3>
  <pre class="code-block">{json.dumps(jsonld, indent=2, ensure_ascii=False)}</pre>
  <p style="margin-top:.75rem;font-size:.8rem;color:var(--muted)">
    Raw JSON-LD: <a href="./index.jsonld">index.jsonld</a>
  </p>
</div>

{prov_html}
"""
    return html_shell(title, body, jsonld=jsonld,
                      description=term.get("description", "")[:160])


# ---------------------------------------------------------------------------
# Reference page
# ---------------------------------------------------------------------------

def render_reference_page(ref: dict) -> str:
    title = ref.get("title", "*(untitled)*")
    jsonld = clean_jsonld(ref)
    bib_type = bibo_type_label(ref.get("@type"))

    id_uri = ref.get("@id", "")
    id_html = (
        f'<p style="margin-top:.35rem;font-family:var(--mono);font-size:.72rem;'
        f'color:var(--muted2)">{id_uri}</p>'
    ) if id_uri else ""

    _, rs_label, rs_color = resolve_status(ref)
    status_badge_html = ""
    if rs_label:
        status_badge_html = (
            f'<span class="badge" style="color:{rs_color};border-color:{rs_color};'
            f'margin-left:.75rem">{rs_label}</span>'
        )

    type_html = (
        f'<p style="margin-top:.35rem;font-family:var(--mono);font-size:.78rem;'
        f'color:var(--green)">{bib_type}</p>'
    ) if bib_type else ""

    abstract_html = ""
    if ab := ref.get("abstract"):
        abstract_html = f'<blockquote class="definition">{ab}</blockquote>'

    def bib_row(label: str, value: str) -> str:
        return f"<tr><td>{label}</td><td>{value}</td></tr>"

    bib_rows = ""
    if authors := agent_names(ref.get("authorList") or ref.get("creator")):
        bib_rows += bib_row("Authors", ", ".join(authors))
    if editors := agent_names(ref.get("editorList")):
        bib_rows += bib_row("Editors", ", ".join(editors))
    if pub := ref.get("publisher"):
        name = pub.get("name", pub) if isinstance(pub, dict) else pub
        bib_rows += bib_row("Publisher", str(name))
    if issued := ref.get("issued"):
        bib_rows += bib_row("Issued", issued)
    elif date := ref.get("date"):
        bib_rows += bib_row("Date", date)
    if ed := ref.get("edition"):     bib_rows += bib_row("Edition", ed)
    if num := ref.get("number"):      bib_rows += bib_row("Number", num)
    for f, l in [("volume", "Volume"), ("issue", "Issue")]:
        if v := ref.get(f): bib_rows += bib_row(l, str(v))
    if ps := ref.get("pageStart"):
        pe = ref.get("pageEnd")
        bib_rows += bib_row("Pages", f"{ps}–{pe}" if pe else str(ps))
    for f, l in [("doi", "DOI"), ("isbn13", "ISBN-13"), ("isbn10", "ISBN-10"), ("issn", "ISSN")]:
        if v := ref.get(f):
            bib_rows += bib_row(l, f'<code style="font-family:var(--mono)">{v}</code>')
    if uri := ref.get("uri") or ref.get("url"):
        bib_rows += bib_row("URL", f'<a href="{uri}" target="_blank" rel="noopener">{uri} ↗</a>')

    bib_html = ""
    if bib_rows:
        bib_html = f"""
        <div class="card" style="margin-top:1.5rem">
          <h3 style="margin-bottom:1rem">Bibliographic Details</h3>
          <table class="bib-table">{bib_rows}</table>
        </div>"""

    prov = []
    if c := ref.get("entryCreated"):  prov.append(f"Created {c}")
    if m := ref.get("entryModified"): prov.append(f"Modified {m}")
    if cr := agent_names(ref.get("entryCreator")): prov.append(f"by {', '.join(cr)}")
    prov_html = f'<div class="provenance">{SEP.join(prov)}</div>' if prov else ""

    body = f"""
<nav class="breadcrumb">
  <a href="/3se-onto/">Index</a>
  <span>/</span>
  <a href="/3se-onto/references/">References</a>
  <span>/</span>
  <span>{title}</span>
</nav>

<div style="margin-bottom:2rem">
  <div style="display:flex;align-items:baseline;gap:.75rem;flex-wrap:wrap">
    <h1>{title}</h1>{status_badge_html}
  </div>
  {id_html}
  {type_html}
  {abstract_html}
</div>

{bib_html}

<div class="card" style="margin-top:1.5rem">
  <h3 style="margin-bottom:.75rem">JSON-LD</h3>
  <pre class="code-block">{json.dumps(jsonld, indent=2, ensure_ascii=False)}</pre>
  <p style="margin-top:.75rem;font-size:.8rem;color:var(--muted)">
    Raw JSON-LD: <a href="./index.jsonld">index.jsonld</a>
  </p>
</div>

{prov_html}
"""
    return html_shell(title, body, jsonld=jsonld,
                      description=ref.get("abstract", title)[:160])


# ---------------------------------------------------------------------------
# Property page
# ---------------------------------------------------------------------------

def render_property_page(prop: dict, ref_index: dict[str, dict]) -> str:
    title = prop.get("title", "*(untitled)*")
    jsonld = clean_jsonld(prop)
    id_uri = prop.get("@id", "")

    id_html = (
        f'<p style="margin-top:.35rem;font-family:var(--mono);font-size:.72rem;'
        f'color:var(--muted2)">{id_uri}</p>'
    ) if id_uri else ""

    _, rs_label, rs_color = resolve_status(prop)
    status_badge_html = ""
    if rs_label:
        status_badge_html = (
            f'<span class="badge" style="color:{rs_color};border-color:{rs_color};'
            f'margin-left:.75rem">{rs_label}</span>'
        )

    description_html = ""
    if desc := prop.get("description"):
        desc_escaped = desc.replace("\n", "<br>")
        description_html = f'<blockquote class="definition">{desc_escaped}</blockquote>'

    # ── Relations rows ──
    def prop_rel_row(label: str, value: str) -> str:
        return f"<tr><td>{label}</td><td>{value}</td></tr>"

    rel_rows_html = ""

    # domain
    if domain := prop.get("domain", ""):
        if is_internal_uri(domain):
            rel_rows_html += prop_rel_row("Domain", render_uri_link(domain))
        else:
            rel_rows_html += prop_rel_row(
                "Domain",
                f'<code style="font-family:var(--mono);font-size:.82rem">{domain}</code>'
            )

    # range
    if range_val := prop.get("range", ""):
        if is_internal_uri(range_val):
            rel_rows_html += prop_rel_row("Range", render_uri_link(range_val))
        else:
            rel_rows_html += prop_rel_row(
                "Range",
                f'<code style="font-family:var(--mono);font-size:.82rem">{range_val}</code>'
            )

    # subPropertyOf
    sub_of = prop.get("subPropertyOf", [])
    if isinstance(sub_of, str):
        sub_of = [sub_of]
    if sub_of:
        links = [render_uri_link(uri) for uri in sub_of]
        rel_rows_html += prop_rel_row("Sub-property of", SEP.join(links))

    relations_html = ""
    if rel_rows_html:
        relations_html = f"""
        <div class="card" style="margin-top:1.5rem">
          <h3 style="margin-bottom:1rem">Relations</h3>
          <table class="relations-table">{rel_rows_html}</table>
        </div>"""

    # ── isReferencedBy ──
    refs_html = ""
    if is_ref_by := prop.get("isReferencedBy", []):
        if isinstance(is_ref_by, str):
            is_ref_by = [is_ref_by]
        ref_links = []
        for uri in is_ref_by:
            ref = ref_index.get(uri)
            label = ref.get("title", stem_from_uri(uri)) if ref else stem_from_uri(uri)
            ref_links.append(render_uri_link(uri, label))
        refs_html = f"""
        <div class="card" style="margin-top:1.5rem">
          <h3 style="margin-bottom:.75rem">Source References</h3>
          <p style="font-size:.9rem">{SEP.join(ref_links)}</p>
        </div>"""

    # ── Provenance ──
    prov = []
    if c := prop.get("entryCreated"):   prov.append(f"Created {c}")
    if m := prop.get("entryModified"):  prov.append(f"Modified {m}")
    if cr := agent_names(prop.get("entryCreator")): prov.append(f"by {', '.join(cr)}")
    prov_html = f'<div class="provenance">{SEP.join(prov)}</div>' if prov else ""

    body = f"""
<nav class="breadcrumb">
  <a href="/3se-onto/">Index</a>
  <span>/</span>
  <a href="/3se-onto/properties/">Properties</a>
  <span>/</span>
  <span>{title}</span>
</nav>

<div style="margin-bottom:2rem">
  <div style="display:flex;align-items:baseline;gap:.75rem;flex-wrap:wrap">
    <h1>{title}</h1>{status_badge_html}
  </div>
  {id_html}
  {description_html}
</div>

{relations_html}
{refs_html}

<div class="card" style="margin-top:1.5rem">
  <h3 style="margin-bottom:.75rem">JSON-LD</h3>
  <pre class="code-block">{json.dumps(jsonld, indent=2, ensure_ascii=False)}</pre>
  <p style="margin-top:.75rem;font-size:.8rem;color:var(--muted)">
    Raw JSON-LD: <a href="./index.jsonld">index.jsonld</a>
  </p>
</div>

{prov_html}
"""
    return html_shell(title, body, jsonld=jsonld,
                      description=prop.get("description", "")[:160])


# ---------------------------------------------------------------------------
# Directory listing pages
# ---------------------------------------------------------------------------

def render_listing(heading: str, subtitle: str, entries: list[dict],
                   dir_name: str, breadcrumb_label: str) -> str:
    items = ""
    for e in entries:
        stem = e["_stem"]
        status = e.get("status", "")
        badge = ""
        _, b_label, b_color = resolve_status(e)
        if b_label:
            badge = (f'<span class="badge" style="color:{b_color};border-color:{b_color}'
                     f';margin-left:.5rem;font-size:.65rem">{b_label}</span>')
        desc = e.get("description", "")[:120]
        if len(e.get("description", "")) > 120:
            desc += "…"
        items += f"""
        <li>
          <span class="entry-title">
            <a href="/3se-onto/{dir_name}/{stem}/">{e.get("title", stem)}</a>
            {badge}
          </span>
          {'<p class="entry-desc">' + desc + '</p>' if desc else ''}
        </li>"""

    body = f"""
<nav class="breadcrumb">
  <a href="/3se-onto/">Index</a>
  <span>/</span>
  <span>{breadcrumb_label}</span>
</nav>

<div style="margin-bottom:2.5rem">
  <h1>{heading}</h1>
  <p style="margin-top:.5rem;color:var(--muted);font-size:.92rem">{subtitle}</p>
</div>

<ul class="entry-list">{items}</ul>
"""
    return html_shell(heading, body, description=subtitle)


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

    # Rebuild _site/
    if SITE_DIR.exists():
        shutil.rmtree(SITE_DIR)
    SITE_DIR.mkdir(parents=True)
    (SITE_DIR / "terms").mkdir()
    (SITE_DIR / "references").mkdir()
    (SITE_DIR / "properties").mkdir()

    # Index
    (SITE_DIR / "index.html").write_text(
        render_index(se3_terms, other_terms, references,
                     se3_properties, other_properties), encoding="utf-8"
    )

    # Terms listing
    (SITE_DIR / "terms" / "index.html").write_text(
        render_listing(
            "Terms",
            f"{len(se3_terms)} 3SE terms and {len(other_terms)} external terms.",
            terms, "terms", "Terms"
        ), encoding="utf-8"
    )

    # References listing
    (SITE_DIR / "references" / "index.html").write_text(
        render_listing(
            "References",
            f"{len(references)} bibliographic references.",
            references, "references", "References"
        ), encoding="utf-8"
    )

    # Properties listing
    (SITE_DIR / "properties" / "index.html").write_text(
        render_listing(
            "Properties",
            f"{len(se3_properties)} 3SE properties"
            + (f" and {len(other_properties)} external properties." if other_properties
               else "."),
            properties, "properties", "Properties"
        ), encoding="utf-8"
    )

    # Individual term pages
    for term in terms:
        stem = term["_stem"]
        out_dir = SITE_DIR / "terms" / stem
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "index.html").write_text(
            render_term_page(term, ref_index, superclass_index, terms_index,
                             represents_index, allocated_by_index), encoding="utf-8"
        )
        (out_dir / "index.jsonld").write_text(
            json.dumps(clean_jsonld(term), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8"
        )

    # Individual reference pages
    for ref in references:
        stem = ref["_stem"]
        out_dir = SITE_DIR / "references" / stem
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "index.html").write_text(
            render_reference_page(ref), encoding="utf-8"
        )
        (out_dir / "index.jsonld").write_text(
            json.dumps(clean_jsonld(ref), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8"
        )

    # Individual property pages
    for prop in properties:
        stem = prop["_stem"]
        out_dir = SITE_DIR / "properties" / stem
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "index.html").write_text(
            render_property_page(prop, ref_index), encoding="utf-8"
        )
        (out_dir / "index.jsonld").write_text(
            json.dumps(clean_jsonld(prop), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8"
        )

    print(
        f"✅ Site generated in {SITE_DIR}/ "
        f"({len(se3_terms)} 3SE terms, {len(other_terms)} other terms, "
        f"{len(references)} references, "
        f"{len(se3_properties)} 3SE properties, {len(other_properties)} other properties)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
