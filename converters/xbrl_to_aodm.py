
from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET

from _common import Builder, cli, local, measurement, ns_of, parse_xml, slug

XBRLI = "http://www.xbrl.org/2003/instance"
XBRLDI = "http://xbrl.org/2006/xbrldi"
LINK = "http://www.xbrl.org/2003/linkbase"
XLINK = "http://www.w3.org/1999/xlink"
XSI = "http://www.w3.org/2001/XMLSchema-instance"

STRUCTURAL = {XBRLI, XBRLDI, LINK, XLINK, XSI}

def _tolerance(el: ET.Element, number: Optional[float]) -> Optional[float]:
    dec = el.get("decimals")
    if dec is not None:
        if dec.strip().upper() == "INF":
            return None
        try:
            return 0.5 * (10 ** -int(dec))
        except ValueError:
            return None

    prec = el.get("precision")
    if prec is not None and number is not None:
        if prec.strip().upper() == "INF":
            return None
        try:
            p = int(prec)
        except ValueError:
            return None
        if p <= 0 or number == 0:
            return None
        import math
        magnitude = math.floor(math.log10(abs(number)))
        return 0.5 * (10 ** (magnitude - p + 1))
    return None

def _measures(parent: ET.Element) -> List[str]:
    return [(m.text or "").strip().split(":")[-1]
            for m in parent
            if ns_of(m.tag) == XBRLI and local(m.tag) == "measure" and (m.text or "").strip()]

def _unit_label(unit_el: ET.Element) -> str:
    divide = [c for c in unit_el if ns_of(c.tag) == XBRLI and local(c.tag) == "divide"]
    if divide:
        num, den = [], []
        for c in divide[0]:
            if local(c.tag) == "unitNumerator":
                num = _measures(c)
            elif local(c.tag) == "unitDenominator":
                den = _measures(c)
        n = "*".join(num) or "1"
        d = "*".join(den) or "1"
        return f"{n}/{d}"
    return "*".join(_measures(unit_el))

def _read_contexts(root: ET.Element) -> Dict[str, Dict[str, Any]]:
    contexts: Dict[str, Dict[str, Any]] = {}

    for ctx in root.iter():
        if ns_of(ctx.tag) != XBRLI or local(ctx.tag) != "context":
            continue

        info: Dict[str, Any] = {"members": [], "forever": False}

        for child in ctx:
            name = local(child.tag)

            if name == "entity":
                for e in child.iter():
                    en = local(e.tag)
                    if en == "identifier":
                        info["entity_id"] = (e.text or "").strip()
                        info["scheme"] = e.get("scheme") or ""
                    elif en == "explicitMember":
                        info["members"].append({
                            "kind": "explicit",
                            "dimension": (e.get("dimension") or "").split(":")[-1],
                            "member": (e.text or "").strip().split(":")[-1],
                        })
                    elif en == "typedMember":

                        inner = list(e)
                        info["members"].append({
                            "kind": "typed",
                            "dimension": (e.get("dimension") or "").split(":")[-1],
                            "member": (inner[0].text or "").strip() if inner else "",
                            "member_name": local(inner[0].tag) if inner else "",
                        })

            elif name == "period":
                for p in child:
                    pn = local(p.tag)
                    if pn == "instant":
                        v = (p.text or "").strip()
                        info["valid_from"] = v
                        info["valid_to"] = v
                    elif pn == "startDate":
                        info["valid_from"] = (p.text or "").strip()
                    elif pn == "endDate":
                        info["valid_to"] = (p.text or "").strip()
                    elif pn == "forever":

                        info["forever"] = True

            elif name in ("segment", "scenario"):
                for s in child.iter():
                    sn = local(s.tag)
                    if sn == "explicitMember":
                        info["members"].append({
                            "kind": "explicit",
                            "dimension": (s.get("dimension") or "").split(":")[-1],
                            "member": (s.text or "").strip().split(":")[-1],
                        })
                    elif sn == "typedMember":
                        inner = list(s)
                        info["members"].append({
                            "kind": "typed",
                            "dimension": (s.get("dimension") or "").split(":")[-1],
                            "member": (inner[0].text or "").strip() if inner else "",
                            "member_name": local(inner[0].tag) if inner else "",
                        })

        contexts[ctx.get("id") or ""] = info

    return contexts

def _read_footnotes(root: ET.Element) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}

    for link in root.iter():
        if ns_of(link.tag) != LINK or local(link.tag) != "footnoteLink":
            continue

        locs: Dict[str, str] = {}
        notes: Dict[str, str] = {}
        arcs: List[tuple] = []

        for child in link:
            name = local(child.tag)
            label = child.get(f"{{{XLINK}}}label") or ""
            if name == "loc":
                href = child.get(f"{{{XLINK}}}href") or ""
                locs[label] = href.split("#")[-1]
            elif name == "footnote":
                notes[label] = "".join(child.itertext()).strip()
            elif name == "footnoteArc":
                arcs.append((child.get(f"{{{XLINK}}}from") or "",
                             child.get(f"{{{XLINK}}}to") or ""))

        for frm, to in arcs:
            fact_id = locs.get(frm)
            text = notes.get(to)
            if fact_id and text:
                out.setdefault(fact_id, []).append(text)

    return out

def _is_fact(el: ET.Element) -> bool:
    ns = ns_of(el.tag)
    return bool(ns) and ns not in STRUCTURAL

def _fraction_value(el: ET.Element) -> Optional[float]:
    num = den = None
    for c in el:
        if ns_of(c.tag) != XBRLI:
            continue
        if local(c.tag) == "numerator":
            num = (c.text or "").strip()
        elif local(c.tag) == "denominator":
            den = (c.text or "").strip()
    if num is None or den is None:
        return None
    try:
        d = float(den)
        return float(num) / d if d else None
    except (TypeError, ValueError, ZeroDivisionError):
        return None

def convert(path: str) -> Dict[str, Any]:
    root = parse_xml(path)
    b = Builder()

    contexts = _read_contexts(root)
    footnotes = _read_footnotes(root)

    units: Dict[str, str] = {}
    for u in root.iter():
        if ns_of(u.tag) == XBRLI and local(u.tag) == "unit":
            units[u.get("id") or ""] = _unit_label(u)

    schema_ref = ""
    for s in root.iter():
        if ns_of(s.tag) == LINK and local(s.tag) == "schemaRef":
            schema_ref = s.get(f"{{{XLINK}}}href") or ""
            break

    filing_source: Dict[str, Any] = {"title": f"XBRL instance: {path.rsplit('/', 1)[-1]}"}
    if schema_ref:
        filing_source["uri"] = schema_ref

    entity_ids: Dict[str, str] = {}
    for info in contexts.values():
        key = info.get("entity_id")
        if not key or key in entity_ids:
            continue
        scheme = info.get("scheme", "")
        label = f"CIK {key}" if "sec.gov/CIK" in scheme else str(key)
        entity_ids[key] = b.entity(slug("entity", key), "reporting-entity",
                                   label=label,
                                   source={"uri": scheme} if scheme else None)

    member_ids: Dict[str, str] = {}
    for info in contexts.values():
        for m in info["members"]:
            key = f"{m['dimension']}::{m['member']}"
            if key in member_ids or not m["member"]:
                continue
            member_ids[key] = b.entity(
                slug("dim", m["dimension"], m["member"]),
                "dimension-member" if m["kind"] == "explicit" else "typed-dimension-member",
                label=m["member"],
            )

    tuple_ids: Dict[int, str] = {}

    def is_tuple(el: ET.Element) -> bool:

        if not _is_fact(el) or el.get("contextRef"):
            return False
        return any(_is_fact(c) for c in el)

    for el in root.iter():
        if is_tuple(el):
            tuple_ids[id(el)] = b.entity(slug("tuple", local(el.tag)),
                                         "fact-group", label=local(el.tag))

    parent_of: Dict[int, ET.Element] = {}
    for parent in root.iter():
        for child in parent:
            parent_of[id(child)] = parent

    def enclosing_tuple(el: ET.Element) -> Optional[str]:
        node = parent_of.get(id(el))
        while node is not None:
            if id(node) in tuple_ids:
                return tuple_ids[id(node)]
            node = parent_of.get(id(node))
        return None

    for el in root.iter():
        if not _is_fact(el) or is_tuple(el):
            continue
        ctx_ref = el.get("contextRef")
        if not ctx_ref:
            continue

        ctx = contexts.get(ctx_ref, {})
        name = local(el.tag)
        text = (el.text or "").strip()
        unit = units.get(el.get("unitRef") or "", "")

        frac = _fraction_value(el)
        if frac is not None:
            value = measurement(frac, unit or None)
        else:
            value = measurement(text, unit or None)

        number = value.get("number") if value else None
        tol = _tolerance(el, float(number) if isinstance(number, (int, float)) else None)
        if value is not None and tol is not None:
            value["tolerance"] = tol

        nil = el.get(f"{{{XSI}}}nil") == "true"

        if value is not None or nil:
            statement = name
        else:
            statement = f"{name}: {text}" if text else name

        notes = footnotes.get(el.get("id") or "", [])
        if notes:
            statement = f"{statement} — {' '.join(notes)}"

        about = enclosing_tuple(el) or entity_ids.get(ctx.get("entity_id", ""))

        extras: Dict[str, Any] = {}
        if not ctx.get("forever"):
            if ctx.get("valid_from"):
                extras["valid_from"] = ctx["valid_from"]
            if ctx.get("valid_to"):
                extras["valid_to"] = ctx["valid_to"]

        fid = b.fact(
            statement=statement,
            about=about,
            ident=slug("fact", name, ctx_ref),
            value=value,
            source=filing_source,

            confidence=1.0,
            **extras,
        )

        subject = entity_ids.get(ctx.get("entity_id", ""))
        for m in ctx.get("members", []):
            target = member_ids.get(f"{m['dimension']}::{m['member']}")
            if target and subject:
                b.relationship(
                    type_="dimension",
                    subject=subject,
                    predicate=slug(m["dimension"]) or "dimension",
                    object_=target,
                    ident=slug("rel", fid or name, m["dimension"], m["member"]),
                )

    for el in root.iter():
        if id(el) not in tuple_ids:
            continue
        child_group = tuple_ids[id(el)]
        outer = enclosing_tuple(el)
        if outer:
            b.relationship(type_="composition", subject=outer,
                           predicate="contains", object_=child_group,
                           ident=slug("rel", outer, child_group))

    return b.model

if __name__ == "__main__":
    sys.exit(cli(convert, __doc__.strip().splitlines()[0]))
