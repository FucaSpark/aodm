# AODM 1.2 — Validation Rules

The XSD (`aodm-core-1.2.xsd`) and JSON Schema (`aodm-core-1.2.schema.json`)
enforce structure and types. The rules below are semantic checks that a
conforming AODM processor MUST also apply — an XML/JSON Schema validator
alone cannot catch these.

## Referential integrity

> **Implementation note.** The XSD types these attributes as `xs:IDREF` /
> `xs:IDREFS`, but do not rely on that for integrity: widely used
> validators (libxml2, and therefore lxml, Python, PHP and much of the
> XML tooling ecosystem) do not enforce IDREF resolution for XML Schema,
> only for DTDs. A dangling reference will pass schema validation
> silently. Rules R1–R3 and R6–R7 MUST therefore be implemented in the
> processor. `conformance-check.py` in this repository demonstrates the
> gap.

- **R1.** `relationship/@subject` and `relationship/@object` (XML) or
  `relationship.subject` / `relationship.object` (JSON) MUST resolve to the
  `id` of an existing `entity` in the same document.
- **R2.** `fact/@about` (XML) or `fact.about` (JSON), if present, MUST
  resolve to the `id` of an existing `entity` or `relationship`.
- **R3.** `rule/condition/@ref` and `rule/conclusion/@ref` (XML), or
  `rule.conditions[].ref` / `rule.conclusion` (JSON), MUST each resolve to
  the `id` of an existing `fact` or `entity`.
- **R4.** A `rule` MUST NOT list its own `conclusion` id among its
  `conditions` (no self-referential rules).
- **R5.** `id` values MUST be unique across the whole document, regardless
  of element type (an `entity` and a `fact` cannot share an id).
- **R6.** Every id in `@derived-from` / `derived_from` MUST resolve to an
  existing `fact`, `rule`, or `entity` in the same document.
- **R7.** The derivation graph formed by `derived-from` MUST be acyclic. A
  fact MUST NOT derive from itself, directly or transitively. (Without
  this, retraction cannot terminate — see P4.)

## Cardinality

XSD 1.0 cannot express these limits while also allowing free child
ordering, so processors MUST enforce them directly.

- **C1.** An `entity`, `relationship`, `fact`, or `rule` MUST carry at most
  one `confidence` child.
- **C2.** A `fact` MUST carry at most one `value` child.

## Value constraints

- **V1.** `confidence` values MUST be within `[0.0, 1.0]` inclusive.
  Processors MUST reject out-of-range values rather than clamping silently.
- **V2.** `source/@retrieved` MUST NOT be a future date relative to
  processing time. `source/@asserted` MAY precede `@retrieved` (a source
  written before you fetched it) but MUST NOT follow it.
- **V3.** `relationship/@predicate` and `entity/@type` SHOULD be lowercase,
  hyphen-separated tokens (e.g. `requires`, `part-of`) for cross-vocabulary
  consistency. Domain extensions MAY define their own token conventions.

## Measurement

- **M1.** A `value` MUST carry either `@number` or both `@min` and `@max` —
  never both forms, and never neither.
- **M2.** When `@min` and `@max` are both present, `@min` MUST be less than
  or equal to `@max`. `@tolerance`, if present, MUST be non-negative and
  MUST only accompany `@number`.
- **M3.** `@unit` SHOULD be a UCUM code (`Cel`, `mm`, `kg`, `bar`). A
  `value` carrying `@number` without `@unit` is valid only for genuinely
  dimensionless quantities (counts, ratios); processors SHOULD warn
  otherwise, since an unlabelled magnitude is the most common source of
  silently wrong engineering data.

## Temporal validity

- **T1.** When both are present, `@valid-to` MUST be greater than or equal
  to `@valid-from`.
- **T2.** A missing `@valid-from` means "valid for all time up to
  `@valid-to`"; a missing `@valid-to` means "valid indefinitely". A
  processor MUST NOT treat a missing bound as "invalid".
- **T3.** A processor answering a time-scoped query MUST exclude facts and
  relationships whose validity window does not contain the query time. When
  no query time is given, "now" is the default.
- **T4.** Expired knowledge MUST NOT be silently deleted on ingest. It is
  excluded from default query results (T3) but retained, because provenance
  and audit depend on knowing what was once believed.

## Polarity

- **N1.** `polarity="negative"` asserts that something is known to be
  false. It is NOT the same as the absence of a fact, which asserts only
  that nothing is known. Processors MUST preserve this distinction.
- **N2.** A processor that does not implement polarity MUST reject
  documents containing `polarity="negative"` rather than ingest them as
  positive assertions. Silently dropping a negation inverts its meaning,
  which is the most dangerous failure mode in this specification.

## Assertion

- **A1.** A `fact` with `asserted="false"` is **declared but not claimed**. A
  processor MUST NOT treat it as established knowledge: it does not satisfy
  a rule premise, and it MUST NOT be returned as a fact the document asserts,
  until something derives it.
- **A2.** Once a rule derives an `asserted="false"` fact, the derived result
  is asserted, and MUST carry `derived-from` naming the rule and premises
  that produced it (rule P3 then applies).
- **A3.** A fact with `asserted="false"` SHOULD carry neither `source` nor
  `confidence`, since it claims nothing yet. A processor encountering both
  SHOULD warn: the document is asserting evidence for something it
  simultaneously declares unclaimed.
- **A4.** `asserted` defaults to `true`. A fact that omits it is claimed, so
  existing documents keep their meaning.

## Self-generated knowledge

- **G1.** `origin` is `observed` (default), `derived` or `generated`. A
  processor MUST preserve it, and MUST be able to filter by it: a consumer
  that only wants human-recorded knowledge must be able to exclude the rest.
- **G2.** A processor MUST NOT present `origin="generated"` knowledge as
  observed. A proposal carries no guarantee that a derivation does, and
  presenting the two identically is how a plausible invention reaches a
  decision unchallenged.
- **G3.** A fact or relationship with `origin="generated"` MUST carry a
  `confidence`, and SHOULD carry at least one `evidence`. A proposal with
  neither is unreviewable: nothing states how far to trust it and nothing
  shows what prompted it.
- **G4.** `evidence` SHOULD carry a `locator` identifying the position within
  the source. Without one a reviewer must re-read the whole document, which
  in practice means the claim is never checked.
- **G5.** `origin="derived"` SHOULD accompany `derived-from`; a fact claiming
  derivation without naming what it derived from cannot be explained or
  retracted (see P4).
- **G6.** Generated knowledge MAY satisfy a rule premise, but a processor
  SHOULD make that configurable and SHOULD report when a conclusion rests on
  a proposal rather than an observation. Inference over unreviewed proposals
  compounds uncertainty silently.

## Provenance and trust

- **P1.** A `fact` or `rule` with no `source` and no `confidence` is
  syntactically valid but SHOULD be treated as unverified/low-trust.
- **P2.** If a `fact` carries a `confidence` below `0.5`, a conforming
  processor SHOULD surface that uncertainty to any consumer (human or LLM)
  rather than presenting the fact as settled.
- **P3.** A `fact` carrying `@derived-from` is inferred, not observed.
  Processors SHOULD distinguish inferred from observed knowledge when
  presenting results, and MUST NOT present an inferred fact as having the
  provenance of its inputs.
- **P4.** When a `source` is invalidated, a processor SHOULD be able to
  identify every fact transitively derived from it via `@derived-from`.
  This is the retraction path; R7 guarantees the traversal terminates.

## Content hashing

- **H1.** `@hash` is `<algorithm>:<hex-digest>` (e.g.
  `sha256:2a405ca8...`). The algorithm MUST be named; bare hex digests
  are not valid in 1.2.
- **H2.** The digest is computed over the item's text content, encoded as
  UTF-8, with leading and trailing whitespace stripped and interior
  whitespace preserved byte for byte. The text content is the element's own
  text together with the text of any non-AODM descendants; nested AODM
  elements contribute nothing, since their text belongs to them. Attributes
  are not included.
- **H3.** Two items with the same `@hash` SHOULD be treated as duplicates
  of one another for ingestion purposes. Processors MUST NOT assume the
  converse — differing hashes do not prove semantic difference, since H2
  is a byte-level comparison, not a semantic one. A stronger
  canonicalization is deferred to a future revision.
- **H4.** A processor that can compute the named algorithm MUST recompute
  the digest and reject any item whose `@hash` disagrees with its text
  content. `sha256` is the only algorithm 1.2 requires; a digest naming
  another algorithm satisfies H1 and is left unverified rather than
  rejected. An item carrying no text content is not checked.

## Inference

- **I1.** Executing rules is OPTIONAL. A Core-conformant processor need only
  parse and validate rule structure. A processor that does evaluate rules
  MUST follow Specification §10 and MAY then claim **Inference-conformance**.
- **I2.** Conditions are conjunctive: a rule fires only when every condition
  is satisfied. There is no disjunction; express alternatives as separate
  rules sharing a conclusion.
- **I3.** Absence MUST NOT satisfy a condition. A `polarity="negative"`
  condition requires a referent explicitly marked `polarity="negative"`;
  a missing fact satisfies nothing. Negation-as-failure changes the meaning
  of an AODM document and MUST NOT be applied silently.
- **I4.** A derived conclusion's confidence is the product of the rule's
  confidence and those of all satisfying conditions, treating absent
  confidence as 1.0. An engine using a different combinator MUST say so,
  because its numbers are not comparable with conformant ones.
- **I5.** Evaluation is relative to an instant. A rule or condition outside
  its validity window does not fire or satisfy (see T1–T3).
- **I6.** Evaluation MUST terminate even on a document that violates R7.

## Conformance levels

- **Core-conformant**: parses and validates all eight core elements per the
  XSD/JSON Schema, and enforces R1–R7, C1–C2, V1–V2, M1–M2, T1–T4, N1–N2,
  H1, and H4.
- **Strict-conformant**: Core-conformant, and additionally enforces the
  SHOULD-level rules (V3, M3, P1–P4, H3).

A processor MUST state which level it implements.
