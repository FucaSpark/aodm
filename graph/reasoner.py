
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "parsers", "python"))

from aodm_graph import Graph, compile_model

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

def _instant(v: Optional[str]) -> datetime:
    if not v:
        return datetime.now(timezone.utc)
    s = v + "T00:00:00+00:00" if _DATE_RE.match(v) else v.replace("Z", "+00:00")
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

def _valid_at(item: Dict[str, Any], when: datetime) -> bool:
    vf, vt = item.get("valid_from"), item.get("valid_to")
    if vf and _instant(vf) > when:
        return False
    if vt:

        end = _instant(vt)
        if _DATE_RE.match(vt):
            end = end.replace(hour=23, minute=59, second=59)
        if end < when:
            return False
    return True

@dataclass
class Derivation:
    fact_id: str
    rule_id: str
    premises: List[str]
    confidence: float
    step: int

@dataclass
class Result:
    model: Dict[str, Any]
    derivations: List[Derivation] = field(default_factory=list)
    fired: List[str] = field(default_factory=list)
    blocked: List[tuple] = field(default_factory=list)

    def graph(self) -> Graph:
        return compile_model(self.model)

class Reasoner:

    def __init__(self, model: Dict[str, Any]):

        import copy
        self.model = copy.deepcopy(model)
        self._index()

    def _index(self) -> None:
        self.facts: Dict[str, Dict[str, Any]] = {
            f["id"]: f for f in self.model.get("facts", []) if f.get("id")
        }
        self.rules: List[Dict[str, Any]] = list(self.model.get("rules", []))
        self.entities: Dict[str, Dict[str, Any]] = {
            e["id"]: e for e in self.model.get("entities", []) if e.get("id")
        }

        self.rule_targets: Set[str] = {
            r["conclusion"] for r in self.rules if r.get("conclusion")
        }

        self.placeholders: Set[str] = {
            fid for fid, f in self.facts.items()
            if f.get("asserted") is False
        } | {
            fid for fid in self.rule_targets
            if (f := self.facts.get(fid)) is not None
            and f.get("asserted") is not False
            and not f.get("source") and f.get("confidence") is None
            and not f.get("derived_from")
        }
        self.derived: Set[str] = set()

    def _satisfied(self, ref: str, want_negative: bool, when: datetime):
        item = self.facts.get(ref) or self.entities.get(ref)
        if item is None:

            return False, 0.0, f"'{ref}' is not present"

        if ref in self.placeholders and ref not in self.derived:
            return False, 0.0, (f"'{ref}' is declared but not asserted, and has not "
                                "been derived")

        if not _valid_at(item, when):
            return False, 0.0, (f"'{ref}' is outside its validity window "
                                f"({item.get('valid_from', '-')}..{item.get('valid_to', '-')})")

        is_negative = item.get("polarity") == "negative"
        if want_negative and not is_negative:
            return False, 0.0, f"'{ref}' is not asserted false, and absence does not count"
        if not want_negative and is_negative:
            return False, 0.0, f"'{ref}' is asserted false"

        conf = item.get("confidence")
        return True, (1.0 if conf is None else float(conf)), ""

    def infer(self, at: Optional[str] = None, max_steps: int = 100) -> Result:
        when = _instant(at)
        result = Result(model=self.model)
        best: Dict[str, float] = {}
        self.derived = set()

        for step in range(1, max_steps + 1):
            changed = False

            for rule in self.rules:
                rid = rule.get("id") or "rule"
                concl = rule.get("conclusion")
                if not concl:
                    continue

                if not _valid_at(rule, when):
                    if step == 1:
                        result.blocked.append((rid, "rule is outside its own validity window"))
                    continue

                conf = rule.get("confidence")
                acc = 1.0 if conf is None else float(conf)
                premises: List[str] = []
                ok = True
                reason = ""

                for cond in rule.get("conditions", []) or []:
                    ref = cond.get("ref") if isinstance(cond, dict) else cond
                    want_neg = (isinstance(cond, dict)
                                and cond.get("polarity") == "negative")
                    good, pconf, why = self._satisfied(ref, want_neg, when)
                    if not good:
                        ok, reason = False, why
                        break
                    acc *= pconf
                    premises.append(ref)

                if not ok:
                    if step == 1:
                        result.blocked.append((rid, reason))
                    continue

                if concl in best and acc <= best[concl] + 1e-12:
                    continue

                best[concl] = acc
                self.derived.add(concl)
                target = self.facts.get(concl)
                if target is None:
                    target = {"id": concl, "statement": f"(derived) {concl}"}
                    self.model.setdefault("facts", []).append(target)
                    self.facts[concl] = target

                target["confidence"] = round(acc, 6)
                target["derived_from"] = [rid] + premises

                target.pop("asserted", None)

                result.derivations.append(
                    Derivation(fact_id=concl, rule_id=rid, premises=premises,
                               confidence=round(acc, 6), step=step))
                if rid not in result.fired:
                    result.fired.append(rid)
                changed = True

            if not changed:
                break

        return result

    def explain(self, fact_id: str, depth: int = 0, seen: Optional[Set[str]] = None) -> List[str]:
        seen = seen or set()
        pad = "  " * depth
        item = self.facts.get(fact_id) or self.entities.get(fact_id)
        if item is None:
            return [f"{pad}{fact_id} — not present"]
        if fact_id in seen:
            return [f"{pad}{fact_id} — (already shown)"]
        seen.add(fact_id)

        conf = item.get("confidence")
        bits = [f"{pad}{fact_id}"]
        text = item.get("statement") or item.get("label") or ""
        if text:
            bits.append(f"— {text[:70]}")
        if conf is not None:
            bits.append(f"[confidence {conf}]")
        if item.get("polarity") == "negative":
            bits.append("[ASSERTED FALSE]")
        lines = [" ".join(bits)]

        derived = item.get("derived_from") or []
        if derived:
            lines.append(f"{pad}  derived by {derived[0]} from:")
            for ref in derived[1:]:
                lines.extend(self.explain(ref, depth + 2, seen))
        else:
            src = item.get("source") or {}
            label = src.get("title") or src.get("uri")
            lines.append(f"{pad}  observed{f' — source: {label}' if label else ' — no source recorded'}")
        return lines

    def retract_source(self, uri_or_title: str) -> Dict[str, List[str]]:
        directly: List[str] = []
        for f in self.model.get("facts", []):
            src = f.get("source") or {}
            if uri_or_title in (src.get("uri"), src.get("title")):
                directly.append(f.get("id"))

        fallen: Set[str] = set(filter(None, directly))
        changed = True
        while changed:
            changed = False
            for f in self.model.get("facts", []):
                fid = f.get("id")
                if not fid or fid in fallen:
                    continue
                deps = set(f.get("derived_from") or [])
                if deps & fallen:
                    fallen.add(fid)
                    changed = True

        return {
            "direct": sorted(x for x in directly if x),
            "consequent": sorted(fallen - set(directly)),
        }

def _load(path: str) -> Dict[str, Any]:
    from aodm import parse, parse_json
    text = open(path, "r", encoding="utf-8").read()
    doc = parse_json(text) if path.endswith(".json") else parse(text)
    return doc.model

def main(argv: List[str]) -> int:
    def opt(name: str) -> Optional[str]:
        for i, a in enumerate(argv):
            if a == name and i + 1 < len(argv):
                return argv[i + 1]
            if a.startswith(name + "="):
                return a.split("=", 1)[1]
        return None

    at = opt("--at")
    explain = opt("--explain")
    retract = opt("--retract")
    consumed = {at, explain, retract, "--at", "--explain", "--retract"}
    args = [a for a in argv[1:] if not a.startswith("-") and a not in consumed]

    if not args:
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        print("usage: reasoner.py <file.xml> [--at DATE] [--explain ID] "
              "[--retract SOURCE]", file=sys.stderr)
        return 2

    try:
        model = _load(args[0])
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    r = Reasoner(model)
    res = r.infer(at=at)

    print(f"Reasoning as at {(_instant(at)).date()}\n")

    if res.derivations:
        print(f"Derived {len(res.derivations)} conclusion(s):")
        for d in res.derivations:
            print(f"  step {d.step}: {d.fact_id}  confidence {d.confidence}")
            print(f"           by {d.rule_id} from {', '.join(d.premises)}")
    else:
        print("Derived nothing.")

    if res.blocked:
        print("\nRules that did not fire:")
        for rid, why in res.blocked:
            print(f"  {rid}: {why}")

    if explain:
        print(f"\nWhy is '{explain}' believed?")
        for line in r.explain(explain):
            print("  " + line)

    if retract:
        fallen = r.retract_source(retract)
        print(f"\nIf '{retract}' were withdrawn:")
        print(f"  directly invalidated : {', '.join(fallen['direct']) or 'nothing'}")
        print(f"  consequently falls   : {', '.join(fallen['consequent']) or 'nothing'}")

    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv))
