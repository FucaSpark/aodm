# AODM

AODM (AI Optimized Data Markup) is a small, open vocabulary for
representing knowledge — entities, relationships, facts, rules — in a form
both humans and AI systems can read, validate, and exchange.

This is the AODM 1.2 specification and its reference implementations.

## AODM 1.2 Specification (start here)

The current core: 4 knowledge primitives (`entity`, `relationship`,
`fact`, `rule`) and 3 annotations (`source`, `confidence`, `value`),
plus a data-quality layer — content hashing, polarity, derivation
tracking, temporal validity, and structured measurement.

Namespace: `http://fucaspark.com/aodm/1.2`

| File | Purpose |
|---|---|
| [`AODM/AODM-1.2-SPECIFICATION.md`](AODM/AODM-1.2-SPECIFICATION.md) | The authoritative specification |
| [`AODM/aodm-core-1.2.xsd`](AODM/aodm-core-1.2.xsd) | XML Schema |
| [`AODM/aodm-core-1.2.schema.json`](AODM/aodm-core-1.2.schema.json) | JSON Schema |
| [`AODM/VALIDATION-RULES.md`](AODM/VALIDATION-RULES.md) | Semantic rules processors must enforce beyond schema validation |
| [`AODM/example-core-1.2.xml`](AODM/example-core-1.2.xml) / [`.json`](AODM/example-core-1.2.json) | Worked examples using every feature |
| [`conformance-check.py`](conformance-check.py) | Verifies the schemas accept valid documents and reject invalid ones |

### Running the conformance check

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install lxml jsonschema && python3 conformance-check.py
```

It also documents which constraints the schemas enforce and which require
processor logic — notably referential integrity, since libxml2 does not
enforce `xs:IDREF` for XML Schema.

Content digests are processor logic of the same kind: every reference
implementation recomputes an item's `sha256` hash and rejects a document
whose digest disagrees with its text, in both the XML and JSON
serialisations.

## Reference implementations

| Directory | Contents |
|---|---|
| [`parsers/`](parsers) | Parsers for Python, JavaScript, Java and C#, each parsing AODM 1.2 XML into the published JSON model and applying the validation rules no schema language can express. [`parsers/conformance.py`](parsers/conformance.py) runs every parser against the same suite. |
| [`graph/`](graph) | Graph compiler and forward-chaining inference engine |
| [`converters/`](converters) | XBRL to AODM conversion |
| [`llm/context.py`](llm/context.py) | Builds LLM context windows from an AODM document |
| [`reference/`](reference) | Browser scripts — a validator and the HTML profile extractor |

Each parser is standard library only, with no dependency to add.

## Embedding AODM in web pages

Use the HTML Embedding Profile:
[`AODM/AODM-1.2-HTML-PROFILE.md`](AODM/AODM-1.2-HTML-PROFILE.md). It marks
up content with `data-aodm` attributes on the elements that display it, so
the human-readable and machine-readable versions cannot drift apart.

```html
<p data-aodm="fact" data-aodm-id="license" data-aodm-about="aodm"
   data-aodm-confidence="1.0">
  AODM is released under the Apache License 2.0.
</p>
```

Extract and validate embedded markup with
[`reference/aodm-html-extract.js`](reference/aodm-html-extract.js), or
online at <https://fucaspark.com/validator.php>.

## Status

The 1.2 core ontology and its formal definition are complete and tested,
with reference parsers in 4 languages, a graph compiler, an inference
engine, an LLM context builder and an XBRL converter, all covered by the
conformance suite.

## License

Apache License 2.0 — see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
