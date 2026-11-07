# 3SE Ontology

Data-only repo: the 3SE ontology as JSON-LD entries (SKOS), plus Python scripts that validate, enrich and publish them. See `README.md` for the concepts (SKOS match relations, BFO/RO alignment, domains, status lifecycle, releases).

## Layout

```
.github/workflows/  — CI: validate (+ inject), generate glossary, deploy site, release site
contexts/           — JSON-LD context per entry type (term, property, reference, domain)
domains/            — one file per engineering domain (skos:Collection)
properties/         — one file per typed relation (allocates, produces, isResponsibleFor, ...)
references/         — one file per bibliographic reference
schemas/            — JSON Schema per entry type; validate_glossary.py applies them plus extra checks
scripts/            — validation, injection, generation and status scripts (see Commands)
terms/              — one file per term, 3SE and external (standards, BFO, ...)
                      roles, analyses, breakdown structures and conceptual models are all terms
glossary.md         — generated, do not edit by hand
_site/              — generated site build, gitignored
graph_out.json      — untracked scratch output, ignore it
requirements.txt    — Python dependencies for the scripts
README.md           — concepts, domains, releases, status lifecycle
```

## Entry conventions

- Filename is `<slug>-<16 hex of UUIDv7>.json`; `@id` is `https://www.3se.info/3se-onto/terms/<stem>`. Identifiers are permanent: never rename a file or change an `@id`.
- Terms are titled `Name - 3SE` for 3SE concepts; external terms carry a source suffix (e.g. `-24765-2017`, `-bfo-2-0`).
- Relation fields (`related`, `subClassOf`, `isAccountableFor`, ...) hold full `@id` URIs. Bare slugs are resolved by `inject_uris.py`, but write full URIs.
- `subClassOf` is reserved for formal BFO subsumption; engineering relations use the typed properties in `properties/`.
- `status` is one of draft / under review / reviewed / under approval / approved / standard. `manage_statuses.py` promotes it after each release; don't promote by hand.
- JSON style: 2-space indent, UTF-8 (no `\u` escapes), trailing newline.

## CI-managed fields — do not hand-maintain

**Always ask the user before editing any of these fields or running the scripts that inject them.** Describe what you intend to change and wait for confirmation.

`entryCreated`, `entryModified`, `entryCreator`, `entryContributor` (from git history), `@id`, and many link fields are injected by the `Validate glossary entries` workflow on every push to `terms|references|properties|domains`, which commits back as `main: inject missing ids, dates and contributors [skip ci]`. In particular:

- `inject_3se_links.py` adds/prunes `related` between 3SE terms based on whether a term's title appears in another's description. Mentioning a concept by its exact name in a description creates a link; removing the mention removes it.
- `inject_analysis_roles.py` copies a role's `isResponsibleFor` / `isAccountableFor` / `isSupporting` from an analysis to that analysis's breakdown structures and conceptual models (taken from the analysis's `related`).
- `inject_responsible_roles.py` derives a role's `isResponsibleFor` from the non-BS/CM/analysis terms in `related` of the analyses it is accountable for. Roles cannot appear in an analysis's `related` (script fails).
- `check_inheritance.py` is a read-only audit of `produces`/`consumes`/`conveys`/`exposes`/`fires` inheritance via `subClassOf`.

So to change role responsibilities, edit the role's `isAccountableFor`/`isSupporting` and the analysis's `related`, then run the two role scripts; also keep the role's `description` text ("accountable for ... It contributes to ...") in sync with its fields.

## Commands

**Always ask the user before running any of these commands.** Several rewrite files in `terms/` (and `glossary.md`/`_site/`), so describe what you intend to run and wait for confirmation.

Run from the repo root (scripts use relative `terms/` paths). `pip install -r requirements.txt` first.

```bash
python scripts/validate_glossary.py          # must pass; CI blocks on it
python scripts/check_inheritance.py
python scripts/inject_analysis_roles.py && python scripts/inject_responsible_roles.py
python scripts/generate_glossary.py          # glossary.md (CI: workflow_dispatch "Generate glossary")
python scripts/generate_site.py              # _site/ (published via GitHub Pages)
```

On Windows set `PYTHONIOENCODING=utf-8` for `validate_glossary.py`, or it crashes on its ✓/─ characters.

CI order is validate → check_inheritance → inject_uuids → inject_ids → inject_uris → inject_3se_links → inject_analysis_roles → inject_responsible_roles → inject_dates → inject_contributors. There are no tests beyond validation.

## Releases

Tag a commit `X.Y` (no `v` prefix) to publish a frozen snapshot under `/3se-onto/X-Y/` (`release_site.yml`). Never retag or delete an existing release tag.

## 3SE consistency

After any change here, check consistency with these repositories and flag any inconsistency before closing the task:

* `3se-mcp`
* `3se-maturity-evaluation`
* `3se-skill`
* `3se-position-paper`
* `3se-talk`

Their local paths are listed in the global CLAUDE.md.
