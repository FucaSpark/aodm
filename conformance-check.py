
import json
import sys

from lxml import etree
import jsonschema

XSD = "AODM/aodm-core-1.2.xsd"
JSON_SCHEMA = "AODM/aodm-core-1.2.schema.json"
XML_EXAMPLE = "AODM/example-core-1.2.xml"
JSON_EXAMPLE = "AODM/example-core-1.2.json"

NS = "http://fucaspark.com/aodm/1.2"

results = []

def check(name, passed, detail=""):
    results.append((name, passed, detail))
    print(f"  {'PASS' if passed else 'FAIL'}  {name}{' -- ' + detail if detail else ''}")

def xml_doc(body, attrs=''):
    return f'<aodm:knowledge version="1.2" xmlns:aodm="{NS}"{attrs}>{body}</aodm:knowledge>'.encode()

def main():
    schema = etree.XMLSchema(etree.parse(XSD))
    jschema = json.load(open(JSON_SCHEMA))

    def xml_valid(body):
        try:
            return schema.validate(etree.fromstring(xml_doc(body)))
        except etree.XMLSyntaxError:
            return False

    def json_valid(inst):
        try:
            jsonschema.validate(instance=inst, schema=jschema)
            return True
        except jsonschema.ValidationError:
            return False

    print("\nPositive cases (must validate)")
    check("XML worked example", schema.validate(etree.parse(XML_EXAMPLE)))
    check("JSON worked example", json_valid(json.load(open(JSON_EXAMPLE))))
    check("children in any order (confidence before source)",
          xml_valid('<aodm:entity id="e" type="t">'
                    '<aodm:confidence value="0.5"/><aodm:source title="s"/></aodm:entity>'))
    check("open-ended validity (valid-from only)",
          xml_valid('<aodm:fact id="f" valid-from="2024-01-01">x</aodm:fact>'))
    check("dateTime precision accepted",
          xml_valid('<aodm:fact id="f" valid-from="2024-01-01T10:30:00Z">x</aodm:fact>'))

    print("\nNegative cases, caught by schema (must be rejected)")
    check("confidence above 1.0",
          not xml_valid('<aodm:entity id="e" type="t"><aodm:confidence value="1.5"/></aodm:entity>'))
    check("bare hex hash (invalid in 1.2)",
          not xml_valid('<aodm:entity id="e" type="t" hash="%s"/>' % ("a" * 64)))
    check("unknown polarity value",
          not xml_valid('<aodm:fact id="f" polarity="maybe">x</aodm:fact>'))
    check("entity missing required @type",
          not xml_valid('<aodm:entity id="e"/>'))
    check("malformed date",
          not xml_valid('<aodm:fact id="f" valid-from="last Tuesday">x</aodm:fact>'))
    check("rule with no conclusion",
          not xml_valid('<aodm:rule id="r"><aodm:condition ref="r"/></aodm:rule>'))
    check("JSON: confidence above 1.0",
          not json_valid({"aodm_version": "1.2", "facts": [{"statement": "x", "confidence": 1.5}]}))
    check("JSON: value with both number and min/max (M1)",
          not json_valid({"aodm_version": "1.2",
                          "facts": [{"statement": "x",
                                     "value": {"number": 1, "min": 0, "max": 2}}]}))
    check("JSON: value with min but no max (M1)",
          not json_valid({"aodm_version": "1.2",
                          "facts": [{"statement": "x", "value": {"min": 0}}]}))
    check("JSON: unknown field rejected",
          not json_valid({"aodm_version": "1.2",
                          "facts": [{"statement": "x", "colour": "red"}]}))

    print("\nConstraints requiring processor logic (schema cannot catch these)")

    check("R1 dangling entity reference passes schema, needs processor",
          xml_valid('<aodm:relationship type="r" subject="ghost" '
                    'predicate="r" object="ghost2"/>'),
          "xs:IDREF is not enforced by libxml2; see VALIDATION-RULES R1")
    check("M2 min>max passes schema, needs processor",
          json_valid({"aodm_version": "1.2",
                      "facts": [{"statement": "x", "value": {"min": 10, "max": 5}}]}),
          "VALIDATION-RULES M2")
    check("T1 valid-to before valid-from passes schema, needs processor",
          xml_valid('<aodm:fact id="f" valid-from="2026-01-01" valid-to="2024-01-01">x</aodm:fact>'),
          "VALIDATION-RULES T1")
    check("C1 duplicate confidence passes schema, needs processor",
          xml_valid('<aodm:entity id="e" type="t">'
                    '<aodm:confidence value="0.1"/><aodm:confidence value="0.9"/></aodm:entity>'),
          "VALIDATION-RULES C1")

    import filecmp
    import os

    if os.path.isdir(os.path.join("site", "aodm", "1.2")):
        print("\nPublished copies match the authoritative schemas")
        for name in ("aodm-core-1.2.xsd", "aodm-core-1.2.schema.json"):
            served = os.path.join("site", "aodm", "1.2", name)
            same = os.path.exists(served) and filecmp.cmp(
                os.path.join("AODM", name), served, shallow=False)
            check(f"{name} matches AODM/{name}", same,
                  "" if same else f"re-copy AODM/{name} to {served}")
    else:
        print("\nPublished copies match the authoritative schemas")
        print("  SKIP  not the source repository (no site/ directory)")

    failed = [n for n, p, _ in results if not p]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("Failed:", ", ".join(failed))
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(main())
