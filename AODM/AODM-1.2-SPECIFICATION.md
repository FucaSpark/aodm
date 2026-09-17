# AODM 1.2 Specification

**Namespace:** `http://fucaspark.com/aodm/1.2`
**Files:** `aodm-core-1.2.xsd`, `aodm-core-1.2.schema.json`, `VALIDATION-RULES.md`

## 1. Abstract

AODM (AI Optimized Data Markup) is a small, stable vocabulary for
representing knowledge — entities, the relationships between them, the
facts asserted about them, and the rules that connect facts — in a form
that both humans and AI systems can read, validate, and exchange without
depending on any one vendor's model or database.

## 2. Design philosophy

HTML won not by being the most powerful markup language available, but by
solving a universal problem — "how do I represent and link documents" —
better than the alternatives at the time. AODM's goal is the analogous
problem for AI-era knowledge: *how do facts, entities, and their
relationships move cleanly between databases, LLMs, graph engines, RAG
pipelines, PLM systems, and autonomous agents, without becoming
model-specific or vendor-specific?*

Two consequences follow, and they shape every decision in this document:

1. **The core stays small.** AODM 1.2 defines four knowledge primitives
   (`entity`, `relationship`, `fact`, `rule`) and four annotations
   (`source`, `confidence`, `value`, `evidence`). New tags are not added
   opportunistically — every AI system implementing AODM should be able to
   understand the basics without tracking a moving target. Domain
   vocabularies (§11) extend AODM through separate, versioned namespaces
   layered on top of this core, never by growing the core itself.
2. **The spec is implementation-independent.** This document, the XSD, and
   the JSON Schema are the authoritative definition. The tools in this
   repository are one implementation, not the definition — anyone should
   be able to build a conformant AODM parser from this document alone.

### 2.1 Small core, but not a thin one

There is a real tension between keeping the core small and making the data
it carries trustworthy. AODM resolves it with a rule of thumb: **the number
of elements stays small; the expressiveness of those elements does not have
to.** Adding an element enlarges the surface every implementer must handle.
Adding an optional attribute to an existing element does not — an
implementer who ignores it still parses the document correctly.

So the qualities that make knowledge trustworthy — when it was true, where
it came from, whether it was measured or inferred, whether it is affirmed
or denied — are carried as attributes on the existing primitives (§6),
rather than as new elements. The one exception is `value` (§5.7), which
needs internal structure that attributes on `fact` could not express
cleanly.

## 3. Namespace and versioning

- The XML namespace for AODM 1.2 is `http://fucaspark.com/aodm/1.2`.
- The version is carried in the namespace URI, and every release does the
  same. An unversioned `http://fucaspark.com/aodm` namespace is not AODM 1.2
  and processors MUST NOT treat it as such.
- Breaking changes (removing an element, changing required attributes)
  require a new namespace version. Additive, backward-compatible changes
  may be released as 1.3, 1.4, etc.
- Domain extensions (§11) use their own namespace and version
  independently of the core.

## 4. Document forms

AODM is written in two forms, and the core ontology in §5 is identical in
both.

**Standalone documents.** A knowledge document of its own, in XML or JSON,
rooted at `<aodm:knowledge>` (§5.8). Use this when the knowledge is the
artefact — a dataset, a rulebase, an export from a system of record.

**Embedded in HTML.** Attributes on the elements of an existing page, so the
page states its own facts where a reader can see them. Embedding is defined
by `AODM-1.2-HTML-PROFILE.md`, which uses `data-aodm` attributes and works
within HTML5's parsing rules. A page served as `text/html` has no XML
namespaces, so embedding MUST use the attribute profile rather than
namespaced elements.

The two forms interoperate: a standalone document may describe entities a
page also marks up, and the `hash` (§6.1) is what lets a processor tell that
two statements about the same subject rest on the same text.

## 5. Core ontology

Every AODM 1.2 document is composed of instances of these elements. Each is
shown in both XML and JSON form; the two are intended to be losslessly
convertible (see the JSON Schema for the exact field mapping). Note that
XML attributes are hyphenated (`valid-from`) and their JSON counterparts
are snake_cased (`valid_from`).

Child elements may appear **in any order**. Cardinality limits that XSD 1.0
cannot express alongside free ordering are stated in `VALIDATION-RULES.md`
(C1, C2) and MUST be enforced by processors.

### 5.1 `entity`

A thing: an object, concept, component, actor, or place.

```xml
<aodm:entity id="engine" type="component" label="Engine"
             hash="sha256:2a405ca8706ec21cb1e55539b1c514daf94b3f6cb304328b3df662b04b80c1d7">
  Internal combustion engine, 4-cylinder.
  <aodm:source uri="https://example.com/spec-sheet-24" title="Engineering Test Report 24"/>
  <aodm:confidence value="0.95"/>
</aodm:entity>
```

| Attribute | Required | Meaning |
|---|---|---|
| `id` | yes | Unique identifier, referenced by relationships/facts/rules |
| `type` | yes | Open vocabulary (e.g. `component`, `person`, `organization`) |
| `label` | no | Human-readable name |
| `hash` | no | Content digest for deduplication (§6.1) |

### 5.2 `relationship`

A directed, typed link between two entities: `subject —predicate→ object`.

```xml
<aodm:relationship type="requires" subject="engine" predicate="requires" object="fuel"
                   valid-from="2024-01-01" polarity="positive">
  <aodm:confidence value="1.0"/>
</aodm:relationship>
```

`subject` and `object` MUST resolve to `entity` ids in the same document
(R1). Also accepts `polarity` (§6.2), `valid-from`/`valid-to` (§6.4), and
`derived-from` (§6.3).

### 5.3 `fact`

An assertion, optionally scoped to an entity or relationship via `about`.

```xml
<aodm:fact id="temp-rise" about="engine" valid-from="2026-01-15">
  Temperature rise under load.
  <aodm:value number="1.2" unit="Cel" tolerance="0.1"/>
  <aodm:source uri="https://example.com/report-24" retrieved="2026-01-15"/>
  <aodm:confidence value="0.9"/>
</aodm:fact>
```

Accepts `polarity`, `asserted`, `valid-from`/`valid-to`, `hash`, and
`derived-from`.

#### `asserted` — declared versus claimed

A document usually has to declare a fact before a rule can conclude it,
because `conclusion/@ref` must resolve to something (rule R3). But a fact
written only so a rule has a target is not being *claimed* — it is a
placeholder awaiting derivation.

`asserted="false"` marks that distinction. The default is `true`.

```xml
<!-- Observed: claimed to hold, with evidence -->
<aodm:fact id="temp-rise" about="engine">
  Temperature rise under sustained load.
  <aodm:confidence value="0.9"/>
</aodm:fact>

<!-- Declared so a rule can conclude it; not claimed until derived -->
<aodm:fact id="failure-risk" about="engine" asserted="false">
  Elevated failure risk under sustained load.
</aodm:fact>
```

Without this, an inference engine cannot tell a placeholder from an
observation. A rule downstream then fires on evidence that was never
established, and the chain produces a confident conclusion resting on
nothing — the most dangerous possible failure, because the output looks
exactly like a sound derivation.

### 5.4 `rule`

A conditional statement that connects assertions, expressed by reference.
AODM 1.2 defines the *shape* of a rule, not how it is evaluated (§10, and
`VALIDATION-RULES.md` I1).

```xml
<aodm:rule id="risk-rule">
  <aodm:condition ref="temp-rise"/>
  <aodm:condition ref="pressure-fact" polarity="negative"/>
  <aodm:conclusion ref="failure-risk"/>
  <aodm:confidence value="0.7"/>
</aodm:rule>
```

A condition may carry `polarity="negative"`, meaning "this fact is known to
be false" — the rule equivalent of a negated premise.

### 5.5 `source`

Provenance. `retrieved` is when *you* obtained it; `asserted` is when the
source itself made the claim.

```xml
<aodm:source uri="https://example.com/report-24" title="Engineering Test Report 24"
             asserted="2025-11-02" retrieved="2026-01-15"/>
```

### 5.6 `confidence`

A single scalar, `0.0`–`1.0`, optionally tagged with how it was derived.

```xml
<aodm:confidence value="0.82" method="model-estimate"/>
```

### 5.7 `value`

A structured measurement attached to a `fact`, so that a quantity is
machine-usable without regex-parsing prose. Either a point value
(`number`, optionally with `tolerance`) or a range (`min` and `max`) —
never both, never neither (M1).

```xml
<aodm:value number="1.2" unit="Cel" tolerance="0.1"/>
<aodm:value min="5" max="10" unit="bar"/>
```

`unit` SHOULD be a UCUM code. A magnitude with no unit is the most common
source of silently wrong engineering data, so processors SHOULD warn on a
unitless `number` unless the quantity is genuinely dimensionless (M3).

### 5.8 `knowledge` (root container)

Standalone AODM documents use `<aodm:knowledge>` as the root:

```xml
<aodm:knowledge version="1.2" xmlns:aodm="http://fucaspark.com/aodm/1.2">
  <aodm:entity id="engine" type="component" label="Engine"/>
  <aodm:entity id="fuel" type="substance" label="Fuel"/>
  <aodm:relationship type="requires" subject="engine" predicate="requires" object="fuel"/>
</aodm:knowledge>
```

The equivalent JSON document is an object with an `aodm_version` field and
`entities` / `relationships` / `facts` / `rules` / `sources` arrays.

## 6. Data quality features

These are what distinguish 1.2 from a bare ontology. All are optional
attributes: a document that omits them is still valid, and a processor
that ignores them still parses correctly.

### 6.1 Content hashing

`hash` on `entity` and `fact` carries a self-describing digest,
`<algorithm>:<hex>` — e.g.
`sha256:2a405ca8706ec21cb1e55539b1c514daf94b3f6cb304328b3df662b04b80c1d7`.
It exists so that the same fact arriving from two pipelines is recognised
as one fact rather than ingested twice.

The digest covers the element's text content as UTF-8, with leading and
trailing whitespace stripped and interior whitespace left untouched (H2).
Nested AODM elements contribute nothing; their text belongs to them.

A processor able to compute the named algorithm recomputes the digest and
rejects an item whose `hash` disagrees with its text (H4), so a hash that
was never right does not travel silently. Every reference parser does this
for `sha256`, which is the only algorithm 1.2 requires.

This is a byte-level comparison: equal hashes mean duplicates, but unequal
hashes do **not** prove semantic difference, and two publishers who indent
the same text differently produce different digests. A stronger
canonicalization is deferred.

A digest MUST name its algorithm. A bare 64-character hex digest is not
valid; write it as `sha256:` followed by the digest.

### 6.2 Polarity

`polarity="negative"` on a `fact` or `relationship` asserts that something
is known to be **false** — distinct from the absence of a fact, which
asserts only that nothing is known. "The engine does not require coolant"
and "we have no information about coolant" are different claims, and a
knowledge base that cannot tell them apart will confidently answer
questions it should decline.

Because a dropped negation silently inverts meaning, a processor that does
not implement polarity MUST reject documents containing negative
assertions rather than ingest them as positive ones (N2).

### 6.3 Derivation

`derived-from` on a `fact` or `relationship` lists the ids of the rule
and/or facts it was inferred from. It answers "why does the system believe
this?" and makes retraction possible: invalidate a source, and every
conclusion transitively resting on it can be found (P4). The derivation
graph MUST be acyclic so that traversal terminates (R7).

This is also how *generated* knowledge is represented. A fact proposed by
a model rather than observed is an ordinary `fact` carrying
`derived-from`, a `confidence`, and a `source` describing the generator —
no separate element is required.

### 6.4 Self-generated knowledge: `origin` and `evidence`

A system that can only store knowledge is a database. The point of carrying
provenance and confidence is that a system can also *propose* knowledge —
read a document, notice a pattern, and offer a claim for review.

That requires distinguishing three things a consumer must never confuse:

| `origin` | Meaning |
|---|---|
| `observed` | Recorded by a person or instrument. The default. |
| `derived` | Produced by executing a rule (§10). Follows deterministically from its premises. |
| `generated` | **Proposed** by a system, typically a language model. A proposal, not a finding. |

The distinction between `derived` and `generated` is the important one. A
derivation is guaranteed by a rule: given the premises, the conclusion
follows. A generated claim carries no such guarantee — a model read something
and suggested a claim, and it may be wrong in ways a derivation cannot be.
Presenting the two identically is how a plausible-sounding invention ends up
in a decision.

#### `evidence`

`source` says where something came from. `evidence` shows the passage it came
from:

```xml
<aodm:fact id="fatigue-risk" about="engine" origin="generated">
  Cyclic loading above 200 hours may accelerate bearing fatigue.
  <aodm:confidence value="0.45" method="llm-extraction"/>
  <aodm:evidence uri="https://example.com/report-24" locator="p.12, lines 4-9"
                 retrieved="2026-01-15">
    Beyond 200 hours of sustained load, bearing temperatures rose faster than
    the linear model predicts.
  </aodm:evidence>
</aodm:fact>
```

Evidence is repeatable — a proposal may rest on several passages — and
carries a `locator` (page, line range, span, cell, timestamp) so a reviewer
can confirm or reject the claim in seconds rather than re-reading the source.

#### Why not `<generatedFact>` and `<generatedRule>`

An earlier design sketched separate elements. They were not adopted, because
a generated fact *is* a fact: it needs `about`, `value`, `polarity`, validity
and hashing exactly as any other. Separate elements would duplicate the
entire hierarchy, double the validation rules, and force every implementer to
handle two shapes for one concept.

The difference between generated and observed knowledge is **provenance, not
structure**, and provenance is what attributes carry. So `origin` marks it,
`evidence` supports it, and every existing parser, validator, query and graph
traversal keeps working unchanged — which is precisely what would break under
a parallel hierarchy.

### 6.5 Temporal validity

`valid-from` and `valid-to` on `fact`, `relationship`, and `rule` bound
when an assertion holds. Each accepts a date or a dateTime. A missing bound
is open-ended, never "invalid" (T2).

Expired knowledge is excluded from default query results but MUST NOT be
deleted on ingest (T4) — auditability depends on knowing what was once
believed.

## 7. Validation

See `VALIDATION-RULES.md` for the full list of referential-integrity,
cardinality, measurement, temporal, polarity, provenance, and hashing
constraints that a conformant processor must enforce beyond what XSD/JSON
Schema alone can express.

## 8. Conformance

A processor is **Core-conformant** if it correctly parses and validates all
eight core elements against the XSD or JSON Schema and enforces the MUST
rules in `VALIDATION-RULES.md`. It is **Strict-conformant** if it
additionally enforces the SHOULD-level rules. Implementations MUST state
which level they claim.

## 9. Provenance and trust

Every `fact` and `rule` SHOULD be able to answer "where did this come
from?" (`source`), "how sure are we?" (`confidence`), and "was this
observed or inferred?" (`derived-from`). This specification defines the
structure; policies for weighting low-confidence or source-less facts are
left to the consuming application.

## 10. Inference

A rule is a conditional statement connecting assertions. This section defines
what that means, so two conformant engines reach the same conclusions from the
same document.

### 10.1 Firing

A rule fires when **every** condition is satisfied. Conditions are
conjunctive; AODM 1.2 has no disjunction. Express alternatives as separate
rules with the same conclusion.

### 10.2 Satisfaction

A condition names a `fact` or `entity` by `ref`. It is satisfied when the
referent:

1. exists in the document;
2. is **asserted** — either `asserted` is absent or true, or a rule has
   already derived it (§5.3, rule A1);
3. is temporally valid at the evaluation instant (§10.4); and
4. has matching polarity — a positive condition needs a positive referent, a
   condition with `polarity="negative"` needs one marked
   `polarity="negative"`.

**Absence never satisfies anything.** A negative condition is satisfied only
by a fact positively asserting the thing is false, never by the fact being
missing. This follows from §6.2: AODM distinguishes "known false" from
"unknown", so an engine MUST NOT treat failure to find a fact as proof of its
negation. Engines built on closed-world assumptions must not be applied to
AODM documents without stating that they change the meaning.

### 10.3 Confidence

A derived conclusion takes the **product** of the rule's confidence and the
confidence of every satisfying condition. A missing confidence counts as 1.0.

Multiplication is deliberate: a conclusion is never more certain than the
weakest link supporting it, and long chains decay. Engines MAY offer other
combinators, but MUST document any departure, because the resulting numbers
are not comparable with conformant ones.

### 10.4 Time

Evaluation is always relative to an instant, defaulting to now. A rule
outside its own validity window does not fire. A condition whose referent is
outside its validity window is not satisfied. Consequently the same document
yields different conclusions at different instants — which is the point:
knowledge that expired should stop driving decisions.

### 10.5 Provenance

A derived fact MUST carry `derived-from` listing the rule and every
satisfying condition, in that order. This makes each inference explainable by
walking backwards, and retractable by walking forwards (rule P4). Once
derived, a fact that was `asserted="false"` becomes asserted (rule A2).

### 10.6 Termination

Evaluation runs to a fixpoint. A conclusion is updated only when a new
derivation is strictly more confident, which keeps the fixpoint stable.
Rule R7 forbids cyclic derivation, but an engine MUST NOT rely on the
document being well-formed, and MUST terminate regardless.

### 10.7 Conformance

An engine implementing §10.1–10.6 is **Inference-conformant**. This is
optional: a Core-conformant processor is not required to execute rules
(rule I1), only to parse and validate their structure.

The reference implementation is `graph/reasoner.py` in the distribution.

## 11. Extending AODM

Domain vocabularies (manufacturing, healthcare, finance) are expected to
define their own elements in their own namespace and reference 1.2 ids from
within them, rather than adding elements to `http://fucaspark.com/aodm/1.2`.
This keeps the core stable while letting the ecosystem grow. No domain
extensions are defined by this release.

## 12. Changelog

- **1.2** — First formal specification. Defines the named core ontology
  (`entity`, `relationship`, `fact`, `rule`, `source`, `confidence`,
  `value`), the data quality layer — content hashing (§6.1), polarity
  (§6.2), derivation (§6.3), temporal validity (§6.4), structured
  measurement (§5.7) — and the two document forms of §4. The namespace URI
  carries the version. `AODM-1.2-HTML-PROFILE.md` defines HTML embedding.
