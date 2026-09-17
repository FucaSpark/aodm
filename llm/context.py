
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "parsers", "python"))

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

def confidence_word(c: Optional[float]) -> str:
    if c is None:
        return "unverified"
    if c >= 0.95:
        return "near-certain"
    if c >= 0.8:
        return "confident"
    if c >= 0.6:
        return "probable"
    if c >= 0.4:
        return "uncertain"
    return "speculative"

def _measure(v: Dict[str, Any]) -> str:
    if not isinstance(v, dict):
        return ""
    unit = f" {v['unit']}" if v.get("unit") else ""
    if v.get("number") is not None:
        tol = f" ±{v['tolerance']}" if v.get("tolerance") is not None else ""
        return f"{v['number']}{tol}{unit}"
    if v.get("min") is not None and v.get("max") is not None:
        return f"{v['min']}–{v['max']}{unit}"
    return ""

def _period(item: Dict[str, Any]) -> str:
    vf, vt = item.get("valid_from"), item.get("valid_to")
    if vf and vt:
        return f"valid {vf} to {vt}"
    if vf:
        return f"since {vf}"
    if vt:
        return f"until {vt}"
    return ""

def build(model: Dict[str, Any], at: Optional[str] = None,
          include_expired: bool = False) -> Dict[str, Any]:
    when = _instant(at)
    entities = {e["id"]: e for e in model.get("entities", []) if e.get("id")}

    kept_facts: List[Dict[str, Any]] = []
    excluded_expired = 0
    excluded_unasserted = 0

    for f in model.get("facts", []):

        if f.get("asserted") is False:
            excluded_unasserted += 1
            continue
        if not _valid_at(f, when):
            excluded_expired += 1
            if not include_expired:
                continue
        kept_facts.append(f)

    rels = [r for r in model.get("relationships", [])
            if include_expired or _valid_at(r, when)]

    return {
        "as_at": when.date().isoformat(),
        "entities": list(entities.values()),
        "facts": kept_facts,
        "relationships": rels,
        "rules": model.get("rules", []),
        "excluded_expired": excluded_expired,
        "excluded_unasserted": excluded_unasserted,
    }

def to_markdown(summary: Dict[str, Any], max_chars: Optional[int] = None) -> str:
    ents = {e["id"]: e for e in summary["entities"]}
    out: List[str] = []

    out.append("# Knowledge base")
    out.append(f"Current as at {summary['as_at']}. Every statement below carries a "
               "confidence and, where known, a source. Do not present a statement as "
               "more certain than its stated confidence, and say \"as of "
               f"{summary['as_at']}\" when the answer depends on timing.")
    out.append("")

    if summary["entities"]:
        out.append("## Things")
        for e in summary["entities"]:
            label = e.get("label") or e["id"]
            bits = [f"- **{label}** (`{e['id']}`, {e.get('type', 'entity')})"]
            if e.get("content"):
                bits.append(f": {e['content']}")
            out.append("".join(bits))
        out.append("")

    if summary["relationships"]:
        out.append("## Relationships")
        for r in summary["relationships"]:
            s = ents.get(r.get("subject"), {}).get("label") or r.get("subject")
            o = ents.get(r.get("object"), {}).get("label") or r.get("object")
            neg = r.get("polarity") == "negative"
            arrow = f"NOT {r.get('predicate')}" if neg else r.get("predicate")
            line = f"- {s} **{arrow}** {o}"
            extra = []
            if neg:

                extra.append("KNOWN FALSE — this is a denial, not an absence of information")
            c = r.get("confidence")
            extra.append(f"{confidence_word(c)}" + (f" ({c})" if c is not None else ""))
            p = _period(r)
            if p:
                extra.append(p)
            out.append(line + "  \n  _" + "; ".join(extra) + "_")
        out.append("")

    if summary["facts"]:
        out.append("## Facts")
        for f in summary["facts"]:
            about = ents.get(f.get("about"), {}).get("label") or f.get("about")
            head = f"- {f.get('statement', '').strip()}"
            if about:
                head += f" _(about {about})_"
            if f.get("polarity") == "negative":
                head += "  **[KNOWN FALSE]**"
            out.append(head)

            meta = []
            c = f.get("confidence")
            meta.append(confidence_word(c) + (f" ({c})" if c is not None else ""))
            m = _measure(f.get("value") or {})
            if m:
                meta.append(f"measured {m}")
            p = _period(f)
            if p:
                meta.append(p)
            src = f.get("source") or {}
            label = src.get("title") or src.get("uri")
            if label:
                meta.append(f"source: {label}")
            if f.get("derived_from"):
                meta.append("INFERRED, not observed — derived from "
                            + ", ".join(f["derived_from"]))
            out.append("  _" + "; ".join(meta) + "_")
        out.append("")

    if summary["rules"]:
        out.append("## Rules")
        for r in summary["rules"]:
            conds = [c.get("ref") if isinstance(c, dict) else c
                     for c in r.get("conditions", [])]
            negs = {c.get("ref") for c in r.get("conditions", [])
                    if isinstance(c, dict) and c.get("polarity") == "negative"}
            parts = [("NOT " if c in negs else "") + str(c) for c in conds]
            line = f"- IF {' AND '.join(parts)} THEN {r.get('conclusion')}"
            c = r.get("confidence")
            if c is not None:
                line += f"  _({confidence_word(c)}, {c})_"
            out.append(line)
        out.append("")

    notes = []
    if summary["excluded_expired"]:
        notes.append(f"{summary['excluded_expired']} statement(s) were excluded because "
                     f"they had expired by {summary['as_at']}. Do not assume they are "
                     "still true; say so if asked about that period.")
    if summary["excluded_unasserted"]:
        notes.append(f"{summary['excluded_unasserted']} statement(s) are declared but not "
                     "asserted — conclusions awaiting derivation. They are NOT knowledge "
                     "and were excluded.")
    if notes:
        out.append("## What is not here")
        for n in notes:
            out.append(f"- {n}")
        out.append("")

    out.append("If the answer is not supported by the statements above, say so rather "
               "than inferring one.")

    text = "\n".join(out)
    return _truncate(text, max_chars)

def to_text(summary: Dict[str, Any], max_chars: Optional[int] = None) -> str:
    ents = {e["id"]: e for e in summary["entities"]}
    out = [f"KNOWLEDGE (as at {summary['as_at']}; trust each line no further than its "
           "stated confidence)"]

    for r in summary["relationships"]:
        s = ents.get(r.get("subject"), {}).get("label") or r.get("subject")
        o = ents.get(r.get("object"), {}).get("label") or r.get("object")
        neg = "NOT " if r.get("polarity") == "negative" else ""
        c = r.get("confidence")
        out.append(f"- {s} {neg}{r.get('predicate')} {o} [{confidence_word(c)}]")

    for f in summary["facts"]:
        neg = "[KNOWN FALSE] " if f.get("polarity") == "negative" else ""
        c = f.get("confidence")
        m = _measure(f.get("value") or {})
        line = f"- {neg}{f.get('statement', '').strip()}"
        if m:
            line += f" = {m}"
        line += f" [{confidence_word(c)}"
        if f.get("derived_from"):
            line += ", inferred"
        line += "]"
        out.append(line)

    if summary["excluded_expired"]:
        out.append(f"({summary['excluded_expired']} expired statement(s) withheld)")

    return _truncate("\n".join(out), max_chars)

def to_json_context(summary: Dict[str, Any], max_chars: Optional[int] = None) -> str:
    payload = {
        "as_at": summary["as_at"],
        "instructions": (
            "Each statement carries a confidence between 0 and 1 and, where known, a "
            "source. Do not state anything with more certainty than its confidence. "
            "polarity='negative' means the statement is known to be FALSE, which is not "
            "the same as unknown. Items marked inferred were derived, not observed. If "
            "the answer is not supported here, say so."
        ),
        "entities": summary["entities"],
        "relationships": summary["relationships"],
        "facts": [
            {**f, "confidence_label": confidence_word(f.get("confidence")),
             "inferred": bool(f.get("derived_from"))}
            for f in summary["facts"]
        ],
        "rules": summary["rules"],
        "withheld": {
            "expired": summary["excluded_expired"],
            "unasserted": summary["excluded_unasserted"],
        },
    }
    return _truncate(json.dumps(payload, indent=2, ensure_ascii=False), max_chars)

def _truncate(text: str, max_chars: Optional[int]) -> str:
    if not max_chars or len(text) <= max_chars:
        return text
    notice = "\n\n[TRUNCATED: this knowledge base was too large for the context budget. "\
             "Some statements are missing — treat coverage as incomplete.]"
    cut = text[: max(0, max_chars - len(notice))]
    if "\n" in cut:
        cut = cut[: cut.rfind("\n")]
    return cut + notice

def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)

FORMATS = {"markdown": to_markdown, "md": to_markdown,
           "text": to_text, "json": to_json_context}

def load_model(path: str) -> Dict[str, Any]:
    from aodm import parse, parse_json
    text = open(path, "r", encoding="utf-8").read()
    doc = parse_json(text) if path.endswith(".json") else parse(text)
    return doc.model

def main(argv: List[str]) -> int:
    def opt(name, default=None):
        for i, a in enumerate(argv):
            if a == name and i + 1 < len(argv):
                return argv[i + 1]
            if a.startswith(name + "="):
                return a.split("=", 1)[1]
        return default

    fmt = opt("--format", "markdown")
    at = opt("--at")
    max_chars = opt("--max-chars")
    include_expired = "--include-expired" in argv
    consumed = {fmt, at, max_chars, "--format", "--at", "--max-chars"}
    args = [a for a in argv[1:] if not a.startswith("-") and a not in consumed]

    if not args:
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        print("usage: context.py <file.xml> [--format markdown|text|json] "
              "[--at DATE] [--max-chars N] [--include-expired]", file=sys.stderr)
        return 2
    if fmt not in FORMATS:
        print(f"error: unknown format '{fmt}'", file=sys.stderr)
        return 2

    try:
        model = load_model(args[0])
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    summary = build(model, at=at, include_expired=include_expired)
    text = FORMATS[fmt](summary, int(max_chars) if max_chars else None)
    print(text)
    print(f"\n<!-- ~{estimate_tokens(text)} tokens -->", file=sys.stderr)
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv))
