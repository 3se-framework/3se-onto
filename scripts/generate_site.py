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
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

TERMS_DIR = Path("terms")
REFERENCES_DIR = Path("references")
SITE_DIR = Path("_site")

BASE_IRIS: dict[str, str] = {
    "terms": "https://www.3se.info/3se-onto/terms/",
    "references": "https://www.3se.info/3se-onto/references/",
}

TERM_STATUS_LABELS: dict[str, tuple[str, str]] = {
    "draft": ("Draft", "#9ca3af"),
    "under review": ("Under Review", "#f59e0b"),
    "reviewed": ("Reviewed", "#3b82f6"),
    "under approval": ("Under Approval", "#8b5cf6"),
    "approved": ("Approved", "#10b981"),
    "standard": ("Standard", "#059669"),
}

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
    """Return (raw_key, display_label, color) for a term or reference entry.
    Terms use plain string status; references use bibo:status CURIE values."""
    # Term status (plain string)
    status = entry.get("status", "")
    if status and status in TERM_STATUS_LABELS:
        label, color = TERM_STATUS_LABELS[status]
        return status, label, color
    # Reference bibo:status
    bibo_status = entry.get("bibo:status", "")
    if bibo_status and bibo_status in BIBO_STATUS_LABELS:
        label, color = BIBO_STATUS_LABELS[bibo_status]
        return bibo_status, label, color
    return status, "", ""


def build_reference_index(references: list[dict]) -> dict[str, dict]:
    return {r["@id"]: r for r in references if "@id" in r}


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
                 references: list[dict]) -> str:
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
    {len(references)} references.
  </p>
</div>

<div class="filter-bar">
  <input id="search" type="search" placeholder="Search by title or description…">
  <select id="filter-type">
    <option value="">All types</option>
    <option value="3se term">3SE Terms</option>
    <option value="term">Other Terms</option>
    <option value="reference">References</option>
  </select>
  <select id="filter-status">
    <option value="">All statuses</option>
    <optgroup label="Term statuses">
      <option value="draft">Draft</option>
      <option value="reviewed">Reviewed</option>
      <option value="approved">Approved</option>
      <option value="standard">Standard</option>
    </optgroup>
    <optgroup label="Reference statuses">
      <option value="bibo:draft">Draft (bibo)</option>
      <option value="bibo:published">Published</option>
      <option value="bibo:peerreviewed">Peer Reviewed</option>
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


def render_term_page(term: dict, ref_index: dict[str, dict]) -> str:
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
        description_html = f'<blockquote class="definition">{desc}</blockquote>'

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
                f'<td>{" &nbsp;·&nbsp; ".join(links)}</td>'
                f'</tr>'
            )
        return out

    hier = rel_rows([("broader", "Broader"), ("narrower", "Narrower"), ("related", "Related")])
    match = rel_rows([
        ("exactMatch", "Exact match"), ("closeMatch", "Close match"),
        ("broadMatch", "Broad match"), ("narrowMatch", "Narrow match"),
        ("relatedMatch", "Related match"),
    ])
    relations_html = ""
    if hier or match:
        separator = '<tr><td colspan="2" style="padding:.25rem 0"></td></tr>' if hier and match else ""
        relations_html = f"""
        <div class="card" style="margin-top:1.5rem">
          <h3 style="margin-bottom:1rem">Relations</h3>
          <table class="relations-table">{hier}{separator}{match}</table>
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
          <p style="font-size:.9rem">{" &nbsp;·&nbsp; ".join(ref_links)}</p>
        </div>"""

    # Provenance
    prov = []
    if c := term.get("entryCreated"):   prov.append(f"Created {c}")
    if m := term.get("entryModified"):  prov.append(f"Modified {m}")
    if cr := agent_names(term.get("entryCreator")): prov.append(f"by {', '.join(cr)}")
    prov_html = f'<div class="provenance">{" &nbsp;·&nbsp; ".join(prov)}</div>' if prov else ""

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
    prov_html = f'<div class="provenance">{" &nbsp;·&nbsp; ".join(prov)}</div>' if prov else ""

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
    ref_index = build_reference_index(references)
    se3_terms, other_terms = split_terms(terms)

    # Rebuild _site/
    if SITE_DIR.exists():
        shutil.rmtree(SITE_DIR)
    SITE_DIR.mkdir(parents=True)
    (SITE_DIR / "terms").mkdir()
    (SITE_DIR / "references").mkdir()

    # Index
    (SITE_DIR / "index.html").write_text(
        render_index(se3_terms, other_terms, references), encoding="utf-8"
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

    # Individual term pages
    for term in terms:
        stem = term["_stem"]
        out_dir = SITE_DIR / "terms" / stem
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "index.html").write_text(
            render_term_page(term, ref_index), encoding="utf-8"
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

    print(
        f"✅ Site generated in {SITE_DIR}/ "
        f"({len(se3_terms)} 3SE terms, {len(other_terms)} other terms, "
        f"{len(references)} references)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
