
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from xbrl_to_aodm import convert
from _common import validate

SAMPLE = os.path.join(HERE, "samples", "xbrl-instance.xml")

results = []

def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}{'  -- ' + detail if detail and not condition else ''}")

def fact_named(model, prefix):
    for f in model.get("facts", []):
        if f.get("statement", "").startswith(prefix):
            return f
    return None

def main():
    model = convert(SAMPLE)
    facts = model.get("facts", [])
    entities = model.get("entities", [])
    rels = model.get("relationships", [])

    print("XBRL 2.1 instance constructs\n")

    f = fact_named(model, "Revenues")
    check("4.4 duration period -> valid-from/valid-to",
          f and f.get("valid_from") == "2025-01-01" and f.get("valid_to") == "2025-12-31")

    f = fact_named(model, "CommonStockSharesOutstanding")
    check("4.4 instant period -> valid-from == valid-to",
          f and f.get("valid_from") == "2025-12-31" and f.get("valid_to") == "2025-12-31")

    f = fact_named(model, "EntityIncorporationStateCountryCode")
    check("4.4 forever period -> no temporal bounds (rule T2)",
          f and "valid_from" not in f and "valid_to" not in f)

    check("4.4 entity identifier -> reporting-entity",
          any(e["type"] == "reporting-entity" and e.get("label") == "CIK 0000320193"
              for e in entities))

    check("xbrldi explicitMember in scenario -> relationship",
          any(r["predicate"] == "geographyaxis" for r in rels))
    check("xbrldi explicitMember in segment -> relationship",
          any(r["predicate"] == "productaxis" for r in rels))
    check("xbrldi typedMember -> typed-dimension-member entity",
          any(e["type"] == "typed-dimension-member" and e.get("label") == "PLANT-17"
              for e in entities))

    f = fact_named(model, "Revenues")
    check("4.6 single measure unit -> value/@unit", f and f["value"]["unit"] == "USD")

    f = fact_named(model, "EarningsPerShareBasic")
    check("4.6 divided unit -> numerator/denominator",
          f and f["value"]["unit"] == "USD/shares")

    f = fact_named(model, "CommonStockSharesOutstanding")
    check("4.6 non-currency measure (shares)", f and f["value"]["unit"] == "shares")

    f = fact_named(model, "EntityRegistrantName")
    check("4.6 non-numeric item -> statement carries the text",
          f and "Example Corporation" in f["statement"] and "value" not in f)

    f = fact_named(model, "RestructuringCharges")
    check("4.6 xsi:nil item -> fact with no value",
          f and "value" not in f)

    f = fact_named(model, "EffectiveTaxRate")
    check("4.6.5 fraction -> numerator/denominator computed",
          f and abs(f["value"]["number"] - 0.125) < 1e-12,
          f"got {f and f.get('value')}")

    f = fact_named(model, "Revenues")
    check("4.6.4 @decimals=-6 -> tolerance 500000",
          f and abs(f["value"].get("tolerance", 0) - 500000.0) < 1e-6,
          f"got {f and f['value'].get('tolerance')}")

    f = fact_named(model, "GrossProfit")
    check("4.6.4 @precision=4 -> tolerance from significant digits",
          f and abs(f["value"].get("tolerance", 0) - 5e7) < 1.0,
          f"got {f and f['value'].get('tolerance')}")

    f = fact_named(model, "CommonStockSharesOutstanding")
    check("4.6.4 @decimals=INF -> exact, no tolerance",
          f and "tolerance" not in f["value"])

    check("4.9 tuple -> fact-group entity",
          any(e["type"] == "fact-group" and e.get("label") == "DirectorCompensation"
              for e in entities))
    check("4.9 nested tuple -> composition relationship",
          any(r["predicate"] == "contains" for r in rels))
    check("4.9 tuple children attach to their group",
          any(f.get("statement", "").startswith("salary")
              and f.get("about") == "tuple-directorcompensation" for f in facts))
    check("4.9 nested tuple children attach to the inner group",
          any(f.get("statement", "").startswith("awardValue")
              and f.get("about") == "tuple-awarddetail" for f in facts))

    f = fact_named(model, "Revenues")
    check("4.11 footnote resolved through XLink arc",
          f and "segment reorganisation" in f["statement"],
          f"got {f and f.get('statement')}")

    check("5.1 schemaRef recorded as the source",
          any(f.get("source", {}).get("uri", "").endswith("ex-2025.xsd") for f in facts))

    issues = validate(model)
    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    check("output is valid AODM 1.2 (no MUST violations)", not errors,
          "; ".join(str(e) for e in errors[:3]))
    check("output raises no SHOULD-level warnings either", not warnings,
          "; ".join(str(w) for w in warnings[:3]))

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("Failed: " + ", ".join(failed))
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(main())
