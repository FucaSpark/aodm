# AODM 1.2 HTML Embedding Profile

**Applies to:** AODM 1.2 core (`http://fucaspark.com/aodm/1.2`)
**Companion to:** `AODM-1.2-SPECIFICATION.md`

## 1. Why this profile exists

HTML5 has no XML namespaces. A page served as `text/html` — which is every
normal web page — discards an `xmlns:aodm` declaration entirely, and an
element written as `<aodm:fact>` is parsed as an element whose *name* is
literally `aodm:fact`, in the XHTML namespace. Namespace-aware tooling
therefore finds nothing:

```js
document.getElementsByTagNameNS('http://fucaspark.com/aodm', 'fact').length
// => 0, on any text/html page
```

This is not a bug in any particular parser; it is how the HTML5 parsing
algorithm is specified. Any embedding approach that relies on XML namespace
declarations inside HTML is therefore unusable in practice, and a validator
built on `getElementsByTagNameNS` will report success on such a page having
inspected nothing at all.

This profile defines an embedding that works within HTML5's actual rules,
using `data-*` attributes — which are valid on any element, ignored by
browsers, and preserved exactly by every HTML parser.

## 2. Design principle: no drift

The data is written **on the element that displays it**, not in a separate
block beside it. An author editing the visible sentence sees the markup that
describes it in the same place, so the human-readable and machine-readable
versions cannot silently diverge. This is the property this profile is
optimising for, and it is the reason to prefer it over a detached
`<script>` payload.

## 3. Mapping rules

### 3.1 Naming an element

`data-aodm="<element>"` declares that the HTML element carries an AODM
element of that kind. The value is one of `entity`, `relationship`, `fact`,
`rule`, `source`, `confidence`, `value`, `evidence`.

```html
<span data-aodm="entity" data-aodm-id="engine" data-aodm-type="component">Engine</span>
```

is equivalent to:

```xml
<aodm:entity id="engine" type="component">Engine</aodm:entity>
```

### 3.2 Attributes

Every AODM attribute is written as `data-aodm-` followed by the attribute
name, unchanged — including hyphens. §3.2a gives a shorter equivalent form.

| AODM (XML) | HTML profile |
|---|---|
| `id` | `data-aodm-id` |
| `type` | `data-aodm-type` |
| `about` | `data-aodm-about` |
| `subject` / `predicate` / `object` | `data-aodm-subject` / `-predicate` / `-object` |
| `polarity` | `data-aodm-polarity` |
| `origin` | `data-aodm-origin` |
| `asserted` | `data-aodm-asserted` |
| `valid-from` / `valid-to` | `data-aodm-valid-from` / `data-aodm-valid-to` |
| `derived-from` | `data-aodm-derived-from` |
| `hash` | `data-aodm-hash` |

### 3.2a Compact form

Writing `data-aodm-` before every attribute is verbose. A conformant document
MAY instead put a JSON object in the single `data-aodm` attribute. Both forms
are equivalent; a processor MUST accept either, and MAY mix them in one
document.

```html
<p data-aodm='{"fact":"temp-rise","about":"engine","valid_from":"2026-01-15",
   "value":{"number":1.2,"unit":"Cel","tolerance":0.1},
   "source":"https://example.com/report-24","confidence":0.9}'>
  Temperature rise under sustained load: 1.2 °C.
</p>
```

An attribute value beginning with `{` is the compact form. Anything else is
the long form of §3.1.

**Keys.** Exactly one key names the element kind — `entity`, `relationship`,
`fact`, `rule`, `source`, `confidence`, `value` or `evidence` — and its value
is that element's `id`. Every remaining key uses the field name from the
standalone JSON serialisation, so there is one set of names to learn rather
than two: `valid_from`, not `valid-from`. Hyphenated spellings are accepted
as aliases.

**Shorthands.** Three fields accept a scalar where the document form takes an
object:

| Written | Means |
|---|---|
| `"source": "https://example.com/r"` | `{"uri": "https://example.com/r"}` |
| `"confidence": 0.9` | `{"value": 0.9}` |
| `"value": [1.2, "Cel", 0.1]` | `{"number": 1.2, "unit": "Cel", "tolerance": 0.1}` |

`derived_from` and a rule's `conditions` accept either an array or a
space-separated string.

**Quoting.** The attribute must be delimited with single quotes, because JSON
uses double quotes internally. A single quote inside a value is written
`&#39;`. JSON's own escaping handles everything else — including URLs
containing `;`, `=` or `&`, which is why a delimited micro-syntax such as
`data-aodm="fact;id=x;src=..."` is not used.

**Text still comes from the element.** `statement` and `content` may be
omitted and are taken from what the element displays, exactly as in §3.3. The
`about` inheritance of §3.7 applies unchanged.

### 3.3 Text content

The element's text content, whitespace-normalised and trimmed, becomes the
AODM element's content — the `statement` of a `fact`, or the text body of an
`entity`. This is what welds the data to the prose.

```html
<p data-aodm="fact" data-aodm-id="license" data-aodm-about="aodm">
  AODM is released under the Apache License 2.0.
</p>
```

Two rules keep that text meaningful rather than swallowing the page:

- **Descendant primitives are excluded.** Text inside a nested `entity`,
  `relationship`, `fact` or `rule` belongs to *that* element, not its
  container. Nested **annotations** are kept, because they are inline parts
  of the sentence — "rise is `<value>`1.2&deg;C`</value>` per
  `<source>`Report 24`</source>`" must read as one statement.
- **A scope container emits no content.** An `entity` that contains any
  nested AODM markup exists to supply `about` to the facts inside it (§3.6),
  not to carry a text body. Extractors MUST NOT emit `content` for such an
  entity; give it `data-aodm-label` instead.

Without the second rule, wrapping a page section in `data-aodm="entity"`
produces an entity whose `content` is the entire section's prose — every
heading, table cell and code sample in it. That is not data anyone can use.

### 3.4 Annotations: nested or shorthand

`source`, `confidence` and `value` may be written either as nested elements
(when they have visible text of their own) or as shorthand attributes on the
parent (when they do not). Both forms produce identical data.

**Nested** — natural when the annotation *is* visible content, especially a
source that is already a link:

```html
<p data-aodm="fact" data-aodm-id="temp-rise" data-aodm-about="engine">
  Temperature rise under load is
  <span data-aodm="value" data-aodm-number="1.2"
        data-aodm-unit="Cel" data-aodm-tolerance="0.1">1.2&deg;C &plusmn; 0.1</span>,
  per <a data-aodm="source" data-aodm-uri="https://example.com/report-24"
         href="https://example.com/report-24">Test Report 24</a>.
</p>
```

**Shorthand** — for annotations with no visible representation. A shorthand
attribute on a primitive is hoisted into the corresponding annotation:

| Shorthand on the parent | Produces |
|---|---|
| `data-aodm-confidence="0.9"` | `<confidence value="0.9">` |
| `data-aodm-confidence-method="model-estimate"` | its `method` |
| `data-aodm-source-uri`, `-source-title`, `-source-retrieved`, `-source-asserted` | a `source` |
| `data-aodm-number`, `-unit`, `-tolerance`, `-min`, `-max` | a `value` |
| `data-aodm-evidence-uri`, `-evidence-locator` | an `evidence`, with the element's text as its excerpt |

```html
<p data-aodm="fact" data-aodm-id="ns" data-aodm-about="aodm"
   data-aodm-confidence="1.0"
   data-aodm-source-uri="https://fucaspark.com/aodm/1.2/">
  The AODM 1.2 namespace is http://fucaspark.com/aodm/1.2.
</p>
```

A document MUST NOT use both the nested and shorthand form of the same
annotation on one element; that is a cardinality violation (C1/C2).

> **Authoring note.** A nested annotation binds to the nearest **enclosing
> primitive**, which is not always the one you meant. A `source` anchor
> written as a *sibling* of a `fact` — both inside an `entity` — attaches to
> the entity, not the fact. Either nest the annotation inside the element it
> describes, or use the shorthand form on that element. This is the most
> common mistake in inline markup, and it fails silently: the document still
> validates, the provenance is just attached to the wrong thing.

### 3.5 Evidence on a page

`evidence` quotes the passage supporting a claim. On a web page that passage
is often already visible — a blockquote, a cited paragraph — so marking it up
in place costs nothing:

```html
<p data-aodm="fact" data-aodm-id="fatigue-risk" data-aodm-origin="generated"
   data-aodm-confidence="0.45">
  Cyclic loading above 200 hours may accelerate bearing fatigue.
  <span data-aodm="evidence" data-aodm-uri="https://example.com/report-24"
        data-aodm-locator="p.12">Bearing temperatures rose faster than the
    linear model predicts.</span>
</p>
```

Marking a page's own machine-proposed content with `data-aodm-origin="generated"`
is what lets a reader — or a crawler — tell which claims a person stood behind
and which a system suggested.

### 3.6 Rules

HTML nesting cannot conveniently express a rule's condition list, so this
profile carries it as a space-separated id list, mirroring `derived-from`:

```html
<div data-aodm="rule" data-aodm-id="risk-rule"
     data-aodm-conditions="temp-rise operating-pressure"
     data-aodm-conclusion="failure-risk"
     data-aodm-confidence="0.7">
  If temperature rise and operating pressure are both elevated, failure risk increases.
</div>
```

A condition may be negated by prefixing its id with `!`:
`data-aodm-conditions="temp-rise !coolant-present"`.

### 3.7 Scope and nesting

- Extraction is **document-wide**. Every element carrying `data-aodm` is
  collected regardless of where it sits in the DOM tree.
- Ids MUST be unique within the page (rule R5 applies unchanged).
- A `fact` with no explicit `data-aodm-about` that is a DOM descendant of an
  `entity` inherits that entity's id as its `about`. This makes the natural
  document structure — facts written inside the section describing a thing —
  do the right thing without repetition.
- Primitives do not nest into one another in the data model even when they
  nest in the DOM; the containment above affects only the `about` default.

### 3.8 Linking a standalone document

A page MAY point at a standalone AODM document that describes it, using a
`link` element in the document head:

```html
<link rel="alternate" type="application/aodm+xml" href="/aodm/site.xml"
      title="AODM knowledge for this site">
```

`application/aodm+json` names the JSON serialisation. The `href` MAY be
per-page or site-wide; a consumer that follows it MUST treat what it finds as
describing the linking page unless the document says otherwise through `about`.

**This is not an alternative to §2.** Inline markup remains the only form a
consumer sees without a second request, and a page that carries a link and no
markup is a page most consumers will read as carrying no data at all — the
same failure as a detached payload. The link exists for consumers that want the
whole site's knowledge in one document rather than reassembled page by page,
and it is additive: publish both, and the inline markup is what a crawler that
never follows the link still gets.

Discovery without an HTML page: a document MAY also be named in `robots.txt`
using an `AODM:` line, in the same shape as `Sitemap:`.

```
AODM: https://example.com/aodm/site.xml
```

## 4. Equivalence and validation

Extraction MUST produce the same JSON model defined by
`aodm-core-1.2.schema.json`. Consequently **every rule in
`VALIDATION-RULES.md` applies unchanged** to embedded AODM: referential
integrity, cardinality, measurement coherence, temporal ordering, polarity
handling and hash format. A conformant HTML extractor is expected to run
those checks against its output.

The reference extractor is `aodm-html-extract.js`, distributed with this
profile.

## 5. Serving requirements

Embedded AODM travels in the page, so the page has to survive the trip.

- Serve the page as `text/html`. The attribute profile is defined against
  HTML5 parsing rules; namespaced elements are not part of this profile.
- Keep `data-aodm` attributes single-quoted so the JSON inside them can use
  double quotes without escaping.
- Do not minify away attribute quoting. An unquoted attribute value ends at
  the first space, which truncates every compact object.
- A hash (§3.6) covers the text its element encloses after entity decoding
  and whitespace collapsing, so a template that reflows whitespace does not
  invalidate it, and one that rewrites text does.

## 6. Worked example

```html
<article data-aodm="entity" data-aodm-id="aodm"
         data-aodm-type="specification" data-aodm-label="AODM 1.2">

  <h1>AODM 1.2</h1>

  <p data-aodm="fact" data-aodm-id="aodm-license" data-aodm-confidence="1.0"
     data-aodm-source-uri="https://www.apache.org/licenses/LICENSE-2.0">
    AODM is released under the Apache License 2.0.
  </p>

  <p data-aodm="fact" data-aodm-id="aodm-elements"
     data-aodm-number="7" data-aodm-unit="1" data-aodm-confidence="1.0">
    The core vocabulary defines eight elements.
  </p>

  <p>
    AODM
    <span data-aodm="relationship" data-aodm-id="aodm-complements-schema"
          data-aodm-type="complements" data-aodm-subject="aodm"
          data-aodm-predicate="complements" data-aodm-object="schema-org"
          data-aodm-confidence="0.95">complements</span>
    <span data-aodm="entity" data-aodm-id="schema-org"
          data-aodm-type="specification">Schema.org</span>.
  </p>

</article>
```

Extracted, this yields one `entity` for AODM, one for Schema.org, two
`fact`s (both with `about` inherited from the enclosing entity, one carrying
a dimensionless `value`), and one `relationship` — a document that validates
against the 1.2 core schema unchanged.
