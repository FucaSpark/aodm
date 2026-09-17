
from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET

NS = "http://fucaspark.com/aodm/1.2"
LEGACY_NS = "http://fucaspark.com/aodm"
VERSION = "1.2"

PRIMITIVES = ("entity", "relationship", "fact", "rule")
ANNOTATIONS = ("source", "confidence", "value")

_DIGEST_RE = re.compile(r"^[a-z0-9-]+:[0-9a-fA-F]{32,128}$")
_HASH_ALGORITHM = "sha256"
_TOKEN_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?$")

_COLLECTION = {
    "entity": "entities",
    "relationship": "relationships",
    "fact": "facts",
    "rule": "rules",
}

class AodmError(Exception):
    pass

@dataclass
class Issue:
    rule: str
    message: str
    where: str = ""
    severity: str = "error"

    def __str__(self) -> str:
        loc = f" [{self.where}]" if self.where else ""
        return f"{self.severity.upper()} {self.rule}: {self.message}{loc}"

def _trim(text: str) -> str:
    return text.strip()

def content_hash(text: str, algorithm: str = _HASH_ALGORITHM) -> str:
    if algorithm != _HASH_ALGORITHM:
        raise AodmError(f"unsupported digest algorithm: {algorithm}")
    digest = hashlib.sha256(_trim(text).encode("utf-8")).hexdigest()
    return f"{_HASH_ALGORITHM}:{digest}"

def _is_temporal(v: str) -> bool:
    return bool(_DATE_RE.match(v) or _DATETIME_RE.match(v))

def _temporal_value(v: str) -> Optional[datetime]:
    if not _is_temporal(v):
        return None
    s = v + "T00:00:00+00:00" if _DATE_RE.match(v) else v.replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

def _num(v: Optional[str]):
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except ValueError:
        return v
    return int(f) if f.is_integer() else f

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag

def _ns_of(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""

@dataclass
class Document:

    model: Dict[str, Any] = field(default_factory=lambda: {"aodm_version": VERSION})
    issues: List[Issue] = field(default_factory=list)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.model, indent=indent, ensure_ascii=False)

    def to_dict(self) -> Dict[str, Any]:
        return self.model

    def to_xml(self, indent: int = 2) -> str:
        return _to_xml(self.model, indent)

    @property
    def entities(self) -> List[dict]:
        return self.model.get("entities", [])

    @property
    def relationships(self) -> List[dict]:
        return self.model.get("relationships", [])

    @property
    def facts(self) -> List[dict]:
        return self.model.get("facts", [])

    @property
    def rules(self) -> List[dict]:
        return self.model.get("rules", [])

    def by_id(self, item_id: str) -> Optional[dict]:
        for coll in _COLLECTION.values():
            for item in self.model.get(coll, []):
                if item.get("id") == item_id:
                    return item
        return None

    def validate(self) -> List[Issue]:
        return list(self.issues) + _validate(self.model)

    def errors(self) -> List[Issue]:
        return [i for i in self.validate() if i.severity == "error"]

    def warnings(self) -> List[Issue]:
        return [i for i in self.validate() if i.severity == "warning"]

    def is_valid(self) -> bool:
        return not self.errors()

def _text_of(el: ET.Element) -> str:
    parts: List[str] = [el.text or ""]
    for child in el:
        if _ns_of(child.tag) == NS:
            parts.append(child.tail or "")
            continue
        parts.append("".join(child.itertext()))
        parts.append(child.tail or "")
    return _trim("".join(parts))

def _annotations(el: ET.Element, issues: List[Issue], where: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    seen = {"confidence": 0, "value": 0}

    for child in el:
        if _ns_of(child.tag) != NS:
            continue
        kind = _local(child.tag)

        if kind == "confidence":
            seen["confidence"] += 1
            if "confidence" not in out:
                out["confidence"] = _num(child.get("value"))
                if child.get("method"):
                    out["confidence_method"] = child.get("method")

        elif kind == "value":
            seen["value"] += 1
            if "value" not in out:
                val = {}
                for a in ("number", "min", "max", "tolerance"):
                    if child.get(a) is not None:
                        val[a] = _num(child.get(a))
                if child.get("unit"):
                    val["unit"] = child.get("unit")
                if val:
                    out["value"] = val

        elif kind == "evidence":
            ev = {}
            for a in ("uri", "locator", "retrieved"):
                if child.get(a):
                    ev[a] = child.get(a)
            excerpt = re.sub(r"\s+", " ", "".join(child.itertext())).strip()
            if excerpt:
                ev["excerpt"] = excerpt
            if ev:
                out.setdefault("evidence", []).append(ev)

        elif kind == "source":
            if "source" not in out:
                src = {}
                for a in ("uri", "title", "retrieved", "asserted"):
                    if child.get(a):
                        src[a] = child.get(a)
                text = (child.text or "").strip()
                if text and "title" not in src:
                    src["title"] = text
                if src:
                    out["source"] = src

    if seen["confidence"] > 1:
        issues.append(Issue("C1", f"Carries {seen['confidence']} confidence elements; "
                                  "at most one is allowed.", where))
    if seen["value"] > 1:
        issues.append(Issue("C2", f"Carries {seen['value']} value elements; "
                                  "at most one is allowed.", where))
    return out

def _describe(kind: str, item_id: Optional[str], index: int) -> str:
    return f'{kind} "{item_id}"' if item_id else f"{kind} #{index + 1}"

def parse(xml: str) -> Document:
    if not isinstance(xml, str) or not xml.strip():
        raise AodmError("Nothing to parse: empty input.")

    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise AodmError(f"Not well-formed XML: {exc}") from exc

    issues: List[Issue] = []

    found_ns = {_ns_of(el.tag) for el in root.iter()}
    if NS not in found_ns:
        if LEGACY_NS in found_ns:
            raise AodmError(
                f"This document uses the unversioned namespace ({LEGACY_NS}). "
                f"This parser reads AODM 1.2 ({NS})."
            )
        raise AodmError(f'No AODM 1.2 elements found. Declare xmlns:aodm="{NS}".')

    model: Dict[str, Any] = {"aodm_version": VERSION}
    counters = {k: 0 for k in PRIMITIVES}

    for el in root.iter():
        if _ns_of(el.tag) != NS:
            continue
        kind = _local(el.tag)
        if kind not in PRIMITIVES:
            continue

        index = counters[kind]
        counters[kind] += 1
        item_id = el.get("id")
        where = _describe(kind, item_id, index)

        item: Dict[str, Any] = {}
        if item_id:
            item["id"] = item_id

        for attr, key in (("polarity", "polarity"), ("origin", "origin"), ("hash", "hash"),
                          ("valid-from", "valid_from"), ("valid-to", "valid_to")):
            if el.get(attr):
                item[key] = el.get(attr)

        if el.get("derived-from"):
            item["derived_from"] = el.get("derived-from").split()

        item.update(_annotations(el, issues, where))

        if kind == "entity":
            if not item_id:
                issues.append(Issue("XSD", "entity is missing the required id attribute.", where))
            if el.get("type"):
                item["type"] = el.get("type")
            else:
                issues.append(Issue("XSD", "entity is missing the required type attribute.", where))
            if el.get("label"):
                item["label"] = el.get("label")

            has_nested = any(
                _ns_of(c.tag) == NS and _local(c.tag) in PRIMITIVES for c in el.iter() if c is not el
            )
            body = "" if has_nested else _text_of(el)
            if body:
                item["content"] = body
            item.pop("value", None)

        elif kind == "relationship":
            for a in ("type", "subject", "predicate", "object"):
                if el.get(a):
                    item[a] = el.get(a)
                else:
                    issues.append(Issue("XSD", f"relationship is missing the required "
                                                f"{a} attribute.", where))
            item.pop("value", None)

        elif kind == "fact":
            if el.get("about"):
                item["about"] = el.get("about")

            if el.get("asserted") in ("false", "0"):
                item["asserted"] = False
            item["statement"] = _text_of(el)

        elif kind == "rule":
            conditions = []
            for c in el:
                if _ns_of(c.tag) == NS and _local(c.tag) == "condition":
                    ref = c.get("ref")
                    if not ref:
                        issues.append(Issue("XSD", "rule has a condition with no ref "
                                                   "attribute.", where))
                        continue
                    cond: Dict[str, Any] = {"ref": ref}
                    if c.get("polarity"):
                        cond["polarity"] = c.get("polarity")
                    conditions.append(cond)
            if not conditions:
                issues.append(Issue("XSD", "rule has no conditions; at least one is "
                                           "required.", where))
            item["conditions"] = conditions

            concl = [c for c in el if _ns_of(c.tag) == NS and _local(c.tag) == "conclusion"]
            if not concl:
                issues.append(Issue("XSD", "rule has no conclusion; exactly one is "
                                           "required.", where))
            else:
                if len(concl) > 1:
                    issues.append(Issue("XSD", f"rule has {len(concl)} conclusions; "
                                               "exactly one is allowed.", where))
                if concl[0].get("ref"):
                    item["conclusion"] = concl[0].get("ref")
            item.pop("value", None)

        model.setdefault(_COLLECTION[kind], []).append(item)

    return Document(model=model, issues=issues)

def parse_file(path: str) -> Document:
    with open(path, "r", encoding="utf-8") as fh:
        return parse(fh.read())

def parse_json(text: str) -> Document:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise AodmError(f"Not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise AodmError("The document root must be a JSON object.")
    return Document(model=data)

_ATTR_ORDER = {
    "entity": [("id", "id"), ("type", "type"), ("label", "label"), ("hash", "hash"),
               ("polarity", "polarity"), ("valid_from", "valid-from"),
               ("valid_to", "valid-to"), ("derived_from", "derived-from")],
    "relationship": [("id", "id"), ("type", "type"), ("subject", "subject"),
                     ("predicate", "predicate"), ("object", "object"),
                     ("polarity", "polarity"), ("origin", "origin"),
                     ("valid_from", "valid-from"),
                     ("valid_to", "valid-to"), ("derived_from", "derived-from")],
    "fact": [("id", "id"), ("about", "about"), ("asserted", "asserted"),
             ("origin", "origin"), ("polarity", "polarity"),
             ("hash", "hash"), ("valid_from", "valid-from"), ("valid_to", "valid-to"),
             ("derived_from", "derived-from")],
    "rule": [("id", "id"), ("origin", "origin"), ("valid_from", "valid-from"),
             ("valid_to", "valid-to")],
}

def _esc_attr(v: Any) -> str:
    return (str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))

def _esc_text(v: Any) -> str:
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _fmt_num(v: Any) -> str:
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)

def _to_xml(model: Dict[str, Any], indent: int = 2) -> str:
    pad = " " * indent
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           f'<aodm:knowledge version="{_esc_attr(model.get("aodm_version", VERSION))}"'
           f' xmlns:aodm="{NS}">']

    def annotations(item: Dict[str, Any], depth: int) -> List[str]:
        p = pad * depth
        lines = []
        val = item.get("value")
        if isinstance(val, dict):
            attrs = "".join(
                f' {a}="{_esc_attr(_fmt_num(val[a]))}"'
                for a in ("number", "min", "max", "tolerance", "unit")
                if val.get(a) is not None
            )
            lines.append(f"{p}<aodm:value{attrs}/>")
        for ev in item.get("evidence", []) or []:
            attrs_e = "".join(f' {a}="{_esc_attr(ev[a])}"'
                              for a in ("uri", "locator", "retrieved") if ev.get(a))
            if ev.get("excerpt"):
                lines.append(f"{p}<aodm:evidence{attrs_e}>{_esc_text(ev['excerpt'])}"
                             f"</aodm:evidence>")
            else:
                lines.append(f"{p}<aodm:evidence{attrs_e}/>")
        src = item.get("source")
        if isinstance(src, dict):
            attrs = "".join(
                f' {a}="{_esc_attr(src[a])}"'
                for a in ("uri", "title", "retrieved", "asserted")
                if src.get(a) is not None
            )
            lines.append(f"{p}<aodm:source{attrs}/>")
        if item.get("confidence") is not None:
            m = item.get("confidence_method")
            extra = f' method="{_esc_attr(m)}"' if m else ""
            lines.append(f'{p}<aodm:confidence value="'
                         f'{_esc_attr(_fmt_num(item["confidence"]))}"{extra}/>')
        return lines

    for kind, coll in _COLLECTION.items():
        for item in model.get(coll, []):
            attrs = ""
            for key, xml_name in _ATTR_ORDER[kind]:
                v = item.get(key)
                if v is None or v == "" or v == []:
                    continue
                if key == "derived_from":
                    v = " ".join(str(x) for x in v)
                elif isinstance(v, bool):
                    v = "true" if v else "false"
                attrs += f' {xml_name}="{_esc_attr(v)}"'

            body: List[str] = []
            text = item.get("statement") if kind == "fact" else item.get("content")
            if text:
                body.append(f"{pad * 2}{_esc_text(text)}")

            if kind == "rule":
                for cond in item.get("conditions", []):
                    ref = cond.get("ref") if isinstance(cond, dict) else cond
                    pol = cond.get("polarity") if isinstance(cond, dict) else None
                    extra = f' polarity="{_esc_attr(pol)}"' if pol else ""
                    body.append(f'{pad * 2}<aodm:condition ref="{_esc_attr(ref)}"{extra}/>')
                if item.get("conclusion"):
                    body.append(f'{pad * 2}<aodm:conclusion '
                                f'ref="{_esc_attr(item["conclusion"])}"/>')

            body.extend(annotations(item, 2))

            if body:
                out.append(f"{pad}<aodm:{kind}{attrs}>")
                out.extend(body)
                out.append(f"{pad}</aodm:{kind}>")
            else:
                out.append(f"{pad}<aodm:{kind}{attrs}/>")

    out.append("</aodm:knowledge>")
    return "\n".join(out)

def _validate(model: Dict[str, Any]) -> List[Issue]:
    issues: List[Issue] = []
    by_id: Dict[str, dict] = {}
    kind_of: Dict[str, str] = {}

    for kind, coll in _COLLECTION.items():
        for i, item in enumerate(model.get(coll, [])):
            iid = item.get("id")
            if not iid:
                continue
            if iid in by_id:
                issues.append(Issue("R5", f'Duplicate id "{iid}". Ids must be unique across '
                                          "the whole document, regardless of element type.",
                                    _describe(kind, iid, i)))
            else:
                by_id[iid] = item
                kind_of[iid] = kind

    def where_of(kind: str, item: dict, i: int) -> str:
        return _describe(kind, item.get("id"), i)

    for kind, coll in _COLLECTION.items():
        for i, item in enumerate(model.get(coll, [])):
            w = where_of(kind, item, i)

            if kind == "relationship":
                for side in ("subject", "object"):
                    ref = item.get(side)
                    if not ref:
                        continue
                    if ref not in by_id:
                        issues.append(Issue("R1", f'The {side} "{ref}" does not match any '
                                                  "entity id in this document.", w))
                    elif kind_of[ref] != "entity":
                        issues.append(Issue("R1", f'The {side} "{ref}" refers to a '
                                                  f"{kind_of[ref]}, but must refer to an "
                                                  "entity.", w))

            if kind == "fact" and item.get("about"):
                ref = item["about"]
                if ref not in by_id:
                    issues.append(Issue("R2", f'about="{ref}" does not match any id in this '
                                              "document.", w))
                elif kind_of[ref] not in ("entity", "relationship"):
                    issues.append(Issue("R2", f'about="{ref}" refers to a {kind_of[ref]}; it '
                                              "must refer to an entity or relationship.", w))

            if kind == "rule":
                for cond in item.get("conditions", []):
                    ref = cond.get("ref") if isinstance(cond, dict) else cond
                    if ref and ref not in by_id:
                        issues.append(Issue("R3", f'Condition ref="{ref}" does not match any '
                                                  "id in this document.", w))
                    elif ref and kind_of[ref] not in ("fact", "entity"):
                        issues.append(Issue("R3", f'Condition ref="{ref}" refers to a '
                                                  f"{kind_of[ref]}; it must refer to a fact "
                                                  "or entity.", w))
                concl = item.get("conclusion")
                if concl:
                    if concl not in by_id:
                        issues.append(Issue("R3", f'Conclusion ref="{concl}" does not match '
                                                  "any id in this document.", w))
                    refs = [c.get("ref") if isinstance(c, dict) else c
                            for c in item.get("conditions", [])]
                    if concl in refs:
                        issues.append(Issue("R4", f'This rule lists its own conclusion '
                                                  f'"{concl}" as a condition. Self-referential '
                                                  "rules are not allowed.", w))

            for ref in item.get("derived_from", []) or []:
                if ref not in by_id:
                    issues.append(Issue("R6", f'derived-from references "{ref}", which does '
                                              "not match any id in this document.", w))
                elif kind_of[ref] not in ("fact", "rule", "entity"):
                    issues.append(Issue("R6", f"derived-from references a {kind_of[ref]}; it "
                                              "must reference a fact, rule, or entity.", w))

            conf = item.get("confidence")
            if conf is not None:
                if not isinstance(conf, (int, float)):
                    issues.append(Issue("V1", "Confidence is not a number.", w))
                elif not (0.0 <= conf <= 1.0):
                    issues.append(Issue("V1", f"Confidence {conf} is outside the allowed "
                                              "range 0.0-1.0.", w))
                elif conf < 0.5 and kind == "fact":
                    issues.append(Issue("P2", "Confidence is below 0.5. Consumers should be "
                                              "shown that this fact is uncertain.", w,
                                        "warning"))

            src = item.get("source") or {}
            now = datetime.now(timezone.utc)
            for key in ("retrieved", "asserted"):
                if src.get(key) and not _is_temporal(src[key]):
                    issues.append(Issue("V2", f'source {key}="{src[key]}" is not a valid '
                                              "ISO 8601 date.", w))
            if src.get("retrieved") and _is_temporal(src["retrieved"]):
                if _temporal_value(src["retrieved"]) > now:
                    issues.append(Issue("V2", f'source retrieved="{src["retrieved"]}" is in '
                                              "the future.", w))
            if (src.get("asserted") and src.get("retrieved")
                    and _is_temporal(src["asserted"]) and _is_temporal(src["retrieved"])
                    and _temporal_value(src["asserted"]) > _temporal_value(src["retrieved"])):
                issues.append(Issue("V2", f'source asserted="{src["asserted"]}" is later than '
                                          f'retrieved="{src["retrieved"]}". A source cannot be '
                                          "written after you fetched it.", w))

            if kind == "entity" and item.get("type") and not _TOKEN_RE.match(item["type"]):
                issues.append(Issue("V3", f'type="{item["type"]}" should be a lowercase, '
                                          "hyphen-separated token.", w, "warning"))
            if kind == "relationship" and item.get("predicate")\
                    and not _TOKEN_RE.match(item["predicate"]):
                issues.append(Issue("V3", f'predicate="{item["predicate"]}" should be a '
                                          "lowercase, hyphen-separated token.", w, "warning"))

            val = item.get("value")
            if isinstance(val, dict):
                has_num = val.get("number") is not None
                has_min = val.get("min") is not None
                has_max = val.get("max") is not None
                if has_num and (has_min or has_max):
                    issues.append(Issue("M1", "A value must use either number (a point value) "
                                              "or min and max (a range), not both.", w))
                elif not has_num and not (has_min and has_max):
                    issues.append(Issue("M1", "A range value needs both min and max."
                                              if (has_min or has_max) else
                                              "A value must carry either number, or both min "
                                              "and max.", w))
                if has_min and has_max:
                    try:
                        if float(val["min"]) > float(val["max"]):
                            issues.append(Issue("M2", f'min ({val["min"]}) is greater than '
                                                      f'max ({val["max"]}).', w))
                    except (TypeError, ValueError):
                        issues.append(Issue("M2", "min/max are not numeric.", w))
                if val.get("tolerance") is not None:
                    try:
                        if float(val["tolerance"]) < 0:
                            issues.append(Issue("M2", "tolerance must not be negative.", w))
                    except (TypeError, ValueError):
                        issues.append(Issue("M2", "tolerance is not numeric.", w))
                    if not has_num:
                        issues.append(Issue("M2", "tolerance may only accompany a number, not "
                                                  "a min/max range.", w))
                if not val.get("unit") and (has_num or has_min):
                    issues.append(Issue("M3", "This measurement has no unit. Add one (a UCUM "
                                              "code such as Cel, mm, kg, bar) unless the "
                                              "quantity is dimensionless.", w, "warning"))

            for key, label in (("valid_from", "valid-from"), ("valid_to", "valid-to")):
                if item.get(key) and not _is_temporal(item[key]):
                    issues.append(Issue("T1", f'{label}="{item[key]}" is not a valid ISO 8601 '
                                              "date or date-time.", w))
            if (item.get("valid_from") and item.get("valid_to")
                    and _is_temporal(item["valid_from"]) and _is_temporal(item["valid_to"])
                    and _temporal_value(item["valid_to"]) < _temporal_value(item["valid_from"])):
                issues.append(Issue("T1", f'valid-to ({item["valid_to"]}) is earlier than '
                                          f'valid-from ({item["valid_from"]}).', w))

            if item.get("polarity") and item["polarity"] not in ("positive", "negative"):
                issues.append(Issue("N1", f'polarity="{item["polarity"]}" is not allowed; use '
                                          '"positive" or "negative".', w))

            h = item.get("hash")
            if h:
                if re.fullmatch(r"[0-9a-fA-F]{64}", h):
                    issues.append(Issue("H1", "This is a bare hex digest. AODM "
                                              f'1.2 requires a named algorithm: "sha256:'
                                              f'{h[:12]}...".', w))
                elif not _DIGEST_RE.match(h):
                    issues.append(Issue("H1", f'hash="{h}" is not of the form '
                                              "<algorithm>:<hex-digest>.", w))
                else:
                    algorithm = h.split(":", 1)[0].lower()
                    body = item.get("statement") if kind == "fact" else item.get("content")
                    if body and algorithm == _HASH_ALGORITHM:
                        expected = content_hash(body, algorithm)
                        if expected.lower() != h.lower():
                            issues.append(Issue("H4", f'hash="{h}" does not match the '
                                                      "digest of this item's text content "
                                                      f"({expected}).", w))

            if item.get("origin") == "generated":
                if item.get("confidence") is None:
                    issues.append(Issue("G3", 'origin="generated" marks this a proposal, '
                                              "but it carries no confidence. Nothing states "
                                              "how far it should be trusted.", w))
                if not item.get("evidence"):
                    issues.append(Issue("G3", 'origin="generated" without evidence is '
                                              "unreviewable: nothing shows what prompted "
                                              "the claim.", w, "warning"))
            for ev in item.get("evidence", []) or []:
                if not ev.get("locator"):
                    issues.append(Issue("G4", "evidence has no locator, so a reviewer must "
                                              "re-read the whole source to check it.",
                                        w, "warning"))
            if item.get("origin") == "derived" and not item.get("derived_from"):
                issues.append(Issue("G5", 'origin="derived" but nothing named in '
                                          "derived-from; the claim cannot be explained "
                                          "or retracted.", w, "warning"))

            if kind == "fact" and item.get("asserted") is False and (
                    item.get("source") or item.get("confidence") is not None):
                issues.append(Issue("A3", 'asserted="false" declares the fact unclaimed, '
                                          "yet it carries a source or confidence. One or the "
                                          "other is wrong.", w, "warning"))

            if kind in ("fact", "rule") and not item.get("source")\
                    and item.get("confidence") is None and not item.get("derived_from")\
                    and item.get("asserted") is not False:
                issues.append(Issue("P1", "No source and no confidence. Consumers should treat "
                                          "this as unverified.", w, "warning"))

    state: Dict[str, int] = {}
    reported = False

    def visit(node_id: str, stack: List[str]) -> None:
        nonlocal reported
        if state.get(node_id) == 1:
            return
        if state.get(node_id) == 0:
            if not reported:
                cycle = " -> ".join(stack[stack.index(node_id):] + [node_id])
                issues.append(Issue("R7", f"Derivation cycle detected: {cycle}. A fact cannot "
                                          "derive from itself, directly or transitively."))
                reported = True
            return
        state[node_id] = 0
        node = by_id.get(node_id, {})
        for ref in node.get("derived_from", []) or []:
            visit(ref, stack + [node_id])
        if kind_of.get(node_id) == "rule":
            for cond in node.get("conditions", []) or []:
                ref = cond.get("ref") if isinstance(cond, dict) else cond
                if ref:
                    visit(ref, stack + [node_id])
        state[node_id] = 1

    for node_id in list(by_id):
        visit(node_id, [])

    return issues

def _main(argv: List[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("-")]
    validate_only = "--validate" in argv or "-v" in argv

    if not args:
        print(__doc__.strip().splitlines()[0])
        print("usage: aodm.py [--validate] <file.xml|file.json>", file=sys.stderr)
        return 2

    try:
        text = open(args[0], "r", encoding="utf-8").read()
        doc = parse_json(text) if args[0].endswith(".json") else parse(text)
    except AodmError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    issues = doc.validate()
    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]

    if validate_only:
        for i in issues:
            print(i, file=sys.stderr if i.severity == "error" else sys.stdout)
        counts = ", ".join(
            f"{len(doc.model.get(c, []))} {c}" for c in _COLLECTION.values()
            if doc.model.get(c)
        )
        print(f"\n{counts or 'empty document'} — "
              f"{len(errors)} error(s), {len(warnings)} warning(s)")
        return 1 if errors else 0

    print(doc.to_json())
    return 1 if errors else 0

if __name__ == "__main__":
    sys.exit(_main(sys.argv))
