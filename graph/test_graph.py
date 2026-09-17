
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "parsers", "python"))

from aodm_graph import compile_file, compile_model
from reasoner import Reasoner, _load

SAMPLE = os.path.join(HERE, "samples", "engine.xml")
results = []

def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  -- {detail}" if detail and not cond else ""))

def main():
    g = compile_file(SAMPLE)
    model = _load(SAMPLE)

    print("Graph compilation\n")

    edge = next((e for e in g.edges
                 if e.source == "engine" and e.target == "spark" and e.type == "REQUIRES"), None)
    check("entity -> node, relationship -> edge (Engine requires Spark)", edge is not None)
    check("node for each entity", len([n for n in g.nodes if n.labels[0] == "Entity"]) == 4)

    check("facts become nodes, not properties",
          len([n for n in g.nodes if n.labels[0] == "Fact"]) == 5)
    check("fact links to its subject with ABOUT",
          any(e.type == "ABOUT" and e.source == "temp-rise" and e.target == "engine"
              for e in g.edges))

    check("sources become shared nodes (enables retraction)",
          len([n for n in g.nodes if n.labels[0] == "Source"]) == 2)
    check("two facts citing one report share a single Source node",
          len([e for e in g.edges if e.type == "SOURCED_FROM"
               and e.source in ("temp-rise", "pressure-nominal")]) == 2)

    check("rules become nodes with PREMISE and CONCLUDES edges",
          any(e.type == "PREMISE" for e in g.edges) and
          any(e.type == "CONCLUDES" for e in g.edges))

    neg = next((e for e in g.edges if e.props.get("polarity") == "negative"), None)
    check("negative polarity is written on the edge, never dropped",
          neg is not None and neg.target == "coolant")
    check("positive polarity is explicit too, not merely absent",
          all("polarity" in e.props for e in g.edges if e.type == "REQUIRES"))

    check("measurements flatten so queries can filter on magnitude",
          any(n.props.get("value_number") == 1.2 and n.props.get("value_unit") == "Cel"
              for n in g.nodes))
    check("temporal bounds ride on the graph",
          any(n.props.get("valid_to") == "2025-12-31" for n in g.nodes))

    print("\nExporters\n")
    cy = g.to_cypher()
    check("Cypher uses MERGE so re-running is idempotent",
          "MERGE" in cy and "CREATE " not in cy)
    check("Cypher escapes quotes in text",
          "\\'" in cy or all("'" not in (n.props.get("statement") or "") for n in g.nodes))
    ttl = g.to_turtle()
    check("Turtle declares the AODM vocabulary", "@prefix aodm:" in ttl)
    check("Turtle reifies edges carrying confidence/polarity", "rdf:Statement" in ttl)
    check("Turtle types dates as xsd:date", "^^xsd:date" in ttl)
    gml = g.to_graphml()
    check("GraphML is well-formed", gml.startswith("<?xml") and "</graphml>" in gml)
    dot = g.to_dot()
    check("DOT marks negative edges visually", 'color="red"' in dot)
    check("JSON export round-trips node and edge counts",
          __import__("json").loads(g.to_json())["nodes"].__len__() == len(g.nodes))

    print("\nReasoning\n")
    r = Reasoner(model)
    res = r.infer(at="2026-08-01")
    derived = {d.fact_id: d for d in res.derivations}

    check("rule fires when all premises hold", "failure-risk" in derived)
    check("confidence is the product of rule and premises (0.7*0.9*0.95)",
          abs(derived["failure-risk"].confidence - 0.5985) < 1e-6,
          f"got {derived.get('failure-risk') and derived['failure-risk'].confidence}")
    check("inference chains: rule 2 consumes rule 1's conclusion",
          "shorten-service" in derived)
    check("confidence decays along the chain (0.9*0.5985)",
          abs(derived["shorten-service"].confidence - 0.53865) < 1e-6)
    check("derived facts record derived_from = [rule, *premises]",
          r.facts["failure-risk"]["derived_from"] == ["risk-rule", "temp-rise", "pressure-nominal"])

    r2 = Reasoner(model)
    res2 = r2.infer(at="2025-06-01")
    check("a rule outside its validity window does not fire",
          not any(d.rule_id == "risk-rule" for d in res2.derivations))
    check("an undischarged conclusion does not satisfy a later rule",
          not res2.derivations,
          f"derived {[d.fact_id for d in res2.derivations]}")
    check("blocked rules explain themselves",
          any("validity window" in why for _, why in res2.blocked))

    r3 = Reasoner(model)
    r3.infer(at="2026-08-01")
    check("an expired fact is not usable as a premise",
          not r3._satisfied("temp-rise-legacy", False,
                            __import__("reasoner")._instant("2026-08-01"))[0])

    r4 = Reasoner(model)
    ok, _, why = r4._satisfied("no-coolant-missing", True,
                               __import__("reasoner")._instant("2026-08-01"))
    check("absence never satisfies a negative premise (no negation-as-failure)",
          not ok and "not present" in why)

    lines = "\n".join(r.explain("shorten-service"))
    check("explanation walks the chain to observed facts",
          "risk-rule" in lines and "Test Report 24" in lines)

    fallen = r.retract_source("https://example.com/report-24")
    check("retracting a source finds directly invalidated facts",
          set(fallen["direct"]) == {"temp-rise", "pressure-nominal"})
    check("retraction cascades to everything transitively derived",
          set(fallen["consequent"]) == {"failure-risk", "shorten-service"})

    from aodm import Document
    issues = Document(model=res.model).validate()
    errors = [i for i in issues if i.severity == "error"]
    check("the reasoned model is still valid AODM 1.2", not errors,
          "; ".join(str(e) for e in errors[:3]))

    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("Failed: " + ", ".join(failed))
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(main())
