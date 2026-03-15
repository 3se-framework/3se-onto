# 3SE Ontology

> A formal, shared vocabulary that aligns concepts across system, safety, and security engineering — one language for all disciplines.

## What is this?

The 3SE Ontology is the semantic foundation of the [3SE framework](https://www.3se.info/) — System, Safety & Security Engineering.

It defines the core concepts used across the three engineering disciplines and maps them explicitly to the terms found in the standards and frameworks that practitioners already work with.

The ontology is published as machine-readable JSON-LD entries and browsable at [www.3se.info/3se-onto/](https://www.3se.info/3se-onto/).

## Why a dedicated ontology?

Engineering projects draw simultaneously from systems engineering standards (ISO/IEC/IEEE 15288, ISO/IEC/IEEE 24765), safety standards (ISO 26262), security standards (ISO/SAE 21434), requirements frameworks (IREB CPRE), agile frameworks (SAFe), and testing vocabularies (IEEE 1012, ISTQB).

Each of these sources defines its own terms, often covering the same concepts with subtly different scope, framing, or intent. Without an explicit alignment layer, engineers from different disciplines must constantly translate across vocabularies — silently accumulating misunderstandings that surface late, as integration failures or compliance gaps.

The 3SE Ontology addresses this directly by:

1. **Defining** 3SE terms with precision — each concept is defined once, unambiguously, with explicit scope notes where needed.
2. **Mapping** each 3SE term to its closest counterparts across referenced standards using SKOS semantic relations.

## How 3SE terms relate to referenced standards?

Every 3SE term is compared to one or more definitions from the referenced standards. The nature of each relationship is encoded using SKOS mapping properties:

| Relation | Meaning |
|---|---|
| `skos:exactMatch` | The definitions are functionally equivalent and interchangeable in most contexts. |
| `skos:closeMatch` | Strong conceptual overlap but not interchangeable — framing, scope, or method differs. |
| `skos:broadMatch` | The 3SE term is broader — it subsumes the referenced definition. |
| `skos:narrowMatch` | The 3SE term is narrower — it adds constraints the reference does not have. |
| `skos:relatedMatch` | The concepts are associatively related but not hierarchically aligned. |

## Structure
```
terms/          — one JSON-LD file per term (3SE and external)
references/     — one JSON-LD file per bibliographic reference
schemas/        — JSON Schema files for validation
scripts/        — CI/CD pipeline scripts
.github/        — GitHub Actions workflows
```

Each entry is a JSON-LD file conforming to the `skos:Concept` type, identified by a time-ordered UUIDv7-suffixed slug URI under `https://www.3se.info/3se-onto/`. Fields are validated automatically on every push.

## Contributing

The ontology is community-driven. To propose a new term, correct a definition, or add a mapping to a standard not yet covered:

1. Fork the repository
2. Add or edit the relevant JSON file in `terms/` or `references/`
3. Open a pull request — CI will validate your entry automatically

All entries go through a `draft → reviewed → approved` editorial workflow tracked via the `status` field.

---

© 2022 3SE — System, Safety & Security Engineering · [www.3se.info](https://www.3se.info/)

![CC_BY-NC-ND](https://www.3se.info/CC_BY-NC-ND.png)

