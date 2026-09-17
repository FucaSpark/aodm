
from __future__ import annotations

import os
import re
import sys
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "parsers", "python"))

VERSION = "1.2"

def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag

def ns_of(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""

def slug(*parts: Any) -> str:
    raw = "-".join(str(p) for p in parts if p not in (None, ""))
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-").lower()
    s = re.sub(r"-{2,}", "-", s)
    if not s:
        s = "item"
    if not re.match(r"^[A-Za-z_]", s):
        s = "id-" + s
    return s[:120]

class Builder:

    def __init__(self) -> None:
        self.model: Dict[str, Any] = {"aodm_version": VERSION}
        self._ids: Dict[str, int] = {}

    def unique(self, candidate: str) -> str:
        base = slug(candidate)
        if base not in self._ids:
            self._ids[base] = 1
            return base
        self._ids[base] += 1
        return f"{base}-{self._ids[base]}"

    def _add(self, coll: str, item: Dict[str, Any]) -> Dict[str, Any]:
        self.model.setdefault(coll, []).append(item)
        return item

    def entity(self, ident: str, type_: str, label: Optional[str] = None,
               content: Optional[str] = None, **extra) -> str:
        item: Dict[str, Any] = {"id": self.unique(ident), "type": type_}
        if label:
            item["label"] = label
        if content:
            item["content"] = content
        item.update({k: v for k, v in extra.items() if v not in (None, "", [])})
        self._add("entities", item)
        return item["id"]

    def fact(self, statement: str, about: Optional[str] = None,
             ident: Optional[str] = None, value: Optional[Dict[str, Any]] = None,
             source: Optional[Dict[str, Any]] = None,
             confidence: Optional[float] = None, **extra) -> str:
        item: Dict[str, Any] = {}
        if ident:
            item["id"] = self.unique(ident)
        if about:
            item["about"] = about
        item["statement"] = statement
        if value:
            item["value"] = value
        if source:
            item["source"] = {k: v for k, v in source.items() if v not in (None, "")}
        if confidence is not None:
            item["confidence"] = confidence
        item.update({k: v for k, v in extra.items() if v not in (None, "", [])})
        self._add("facts", item)
        return item.get("id", "")

    def relationship(self, type_: str, subject: str, predicate: str, object_: str,
                     ident: Optional[str] = None, **extra) -> str:
        item: Dict[str, Any] = {}
        if ident:
            item["id"] = self.unique(ident)
        item.update({"type": type_, "subject": subject,
                     "predicate": predicate, "object": object_})
        item.update({k: v for k, v in extra.items() if v not in (None, "", [])})
        self._add("relationships", item)
        return item.get("id", "")

def measurement(number: Any, unit: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if number in (None, ""):
        return None
    try:
        f = float(str(number).replace(",", ""))
    except (TypeError, ValueError):
        return None
    out: Dict[str, Any] = {"number": int(f) if f.is_integer() else f}
    if unit:
        out["unit"] = unit
    return out

def parse_xml(path_or_text: str) -> ET.Element:
    if os.path.exists(path_or_text):
        return ET.parse(path_or_text).getroot()
    return ET.fromstring(path_or_text)

def emit(model: Dict[str, Any], as_xml: bool = False, indent: int = 2) -> str:
    import json
    if not as_xml:
        return json.dumps(model, indent=indent, ensure_ascii=False)
    from aodm import _to_xml
    return _to_xml(model, indent)

def validate(model: Dict[str, Any]) -> List[Any]:
    from aodm import Document
    return Document(model=model).validate()

def cli(convert_fn, description: str):
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    as_xml = "--xml" in sys.argv
    check = "--validate" in sys.argv

    if not args:
        print(description, file=sys.stderr)
        print(f"usage: {os.path.basename(sys.argv[0])} <input> [--xml] [--validate]",
              file=sys.stderr)
        return 2

    model = convert_fn(args[0])

    if check:
        issues = validate(model)
        errors = [i for i in issues if i.severity == "error"]
        for i in issues:
            print(i, file=sys.stderr if i.severity == "error" else sys.stdout)
        counts = ", ".join(
            f"{len(model.get(c, []))} {c}"
            for c in ("entities", "relationships", "facts", "rules") if model.get(c)
        )
        print(f"\n{counts or 'empty document'} — {len(errors)} error(s), "
              f"{len(issues) - len(errors)} warning(s)")
        return 1 if errors else 0

    print(emit(model, as_xml))
    return 0
