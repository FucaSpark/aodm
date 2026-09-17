
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JAVA_BIN = "/opt/homebrew/opt/openjdk/bin"

CASES = [
    ("valid: minimal entity", """
        <aodm:knowledge xmlns:aodm="http://fucaspark.com/aodm/1.2">
          <aodm:entity id="engine" type="component" label="Engine"/>
        </aodm:knowledge>""", []),

    ("valid: relationship between entities", """
        <aodm:knowledge xmlns:aodm="http://fucaspark.com/aodm/1.2">
          <aodm:entity id="engine" type="component"/>
          <aodm:entity id="fuel" type="substance"/>
          <aodm:relationship id="r1" type="requires" subject="engine"
                             predicate="requires" object="fuel"/>
        </aodm:knowledge>""", []),

    ("valid: fact with measurement and provenance", """
        <aodm:knowledge xmlns:aodm="http://fucaspark.com/aodm/1.2">
          <aodm:entity id="engine" type="component"/>
          <aodm:fact id="f1" about="engine">
            Temperature rise.
            <aodm:value number="1.2" unit="Cel" tolerance="0.1"/>
            <aodm:source uri="https://example.com/r" retrieved="2026-01-15"/>
            <aodm:confidence value="0.9"/>
          </aodm:fact>
        </aodm:knowledge>""", []),

    ("R1: relationship endpoint missing", """
        <aodm:knowledge xmlns:aodm="http://fucaspark.com/aodm/1.2">
          <aodm:entity id="engine" type="component"/>
          <aodm:relationship type="requires" subject="engine"
                             predicate="requires" object="ghost"/>
        </aodm:knowledge>""", ["R1"]),

    ("R2: fact about a missing id", """
        <aodm:knowledge xmlns:aodm="http://fucaspark.com/aodm/1.2">
          <aodm:fact id="f1" about="nobody">X<aodm:confidence value="0.9"/></aodm:fact>
        </aodm:knowledge>""", ["R2"]),

    ("R4: rule concludes its own premise", """
        <aodm:knowledge xmlns:aodm="http://fucaspark.com/aodm/1.2">
          <aodm:fact id="f1">X<aodm:confidence value="0.9"/></aodm:fact>
          <aodm:rule id="r1">
            <aodm:condition ref="f1"/><aodm:conclusion ref="f1"/>
          </aodm:rule>
        </aodm:knowledge>""", ["R4"]),

    ("R5: duplicate id across element types", """
        <aodm:knowledge xmlns:aodm="http://fucaspark.com/aodm/1.2">
          <aodm:entity id="dup" type="component"/>
          <aodm:fact id="dup">X<aodm:confidence value="0.9"/></aodm:fact>
        </aodm:knowledge>""", ["R5"]),

    ("R6: derived-from points nowhere", """
        <aodm:knowledge xmlns:aodm="http://fucaspark.com/aodm/1.2">
          <aodm:fact id="f1" derived-from="ghost">X</aodm:fact>
        </aodm:knowledge>""", ["R6"]),

    ("R7: derivation cycle", """
        <aodm:knowledge xmlns:aodm="http://fucaspark.com/aodm/1.2">
          <aodm:fact id="a" derived-from="b">A</aodm:fact>
          <aodm:fact id="b" derived-from="a">B</aodm:fact>
        </aodm:knowledge>""", ["R7"]),

    ("C1: two confidence elements", """
        <aodm:knowledge xmlns:aodm="http://fucaspark.com/aodm/1.2">
          <aodm:entity id="e" type="thing">
            <aodm:confidence value="0.1"/><aodm:confidence value="0.9"/>
          </aodm:entity>
        </aodm:knowledge>""", ["C1"]),

    ("V1: confidence above 1.0", """
        <aodm:knowledge xmlns:aodm="http://fucaspark.com/aodm/1.2">
          <aodm:entity id="e" type="thing"><aodm:confidence value="1.7"/></aodm:entity>
        </aodm:knowledge>""", ["V1"]),

    ("V2: source retrieved in the future", """
        <aodm:knowledge xmlns:aodm="http://fucaspark.com/aodm/1.2">
          <aodm:fact id="f1">X<aodm:source retrieved="2099-01-01"/></aodm:fact>
        </aodm:knowledge>""", ["V2"]),

    ("M1: both a number and a range", """
        <aodm:knowledge xmlns:aodm="http://fucaspark.com/aodm/1.2">
          <aodm:fact id="f1">X
            <aodm:value number="3" min="1" max="9" unit="bar"/>
            <aodm:confidence value="0.9"/>
          </aodm:fact>
        </aodm:knowledge>""", ["M1"]),

    ("M2: min greater than max", """
        <aodm:knowledge xmlns:aodm="http://fucaspark.com/aodm/1.2">
          <aodm:fact id="f1">X
            <aodm:value min="10" max="5" unit="bar"/>
            <aodm:confidence value="0.9"/>
          </aodm:fact>
        </aodm:knowledge>""", ["M2"]),

    ("T1: valid-to before valid-from", """
        <aodm:knowledge xmlns:aodm="http://fucaspark.com/aodm/1.2">
          <aodm:fact id="f1" valid-from="2026-05-01" valid-to="2024-01-01">X
            <aodm:confidence value="0.9"/>
          </aodm:fact>
        </aodm:knowledge>""", ["T1"]),

    ("N1: unknown polarity", """
        <aodm:knowledge xmlns:aodm="http://fucaspark.com/aodm/1.2">
          <aodm:fact id="f1" polarity="maybe">X<aodm:confidence value="0.9"/></aodm:fact>
        </aodm:knowledge>""", ["N1"]),

    ("H1: bare hex digest", """
        <aodm:knowledge xmlns:aodm="http://fucaspark.com/aodm/1.2">
          <aodm:entity id="e" type="thing" hash="%s"/>
        </aodm:knowledge>""" % ("a" * 64), ["H1"]),

    ("valid: hash matches its text content", """
        <aodm:knowledge xmlns:aodm="http://fucaspark.com/aodm/1.2">
          <aodm:entity id="e" type="thing"
                       hash="sha256:09a1d8c87d3cc233b56bcc2aec9e3ee8658628de6042c2dd13a7744be165361a">Text here.</aodm:entity>
        </aodm:knowledge>""", []),

    ("H4: hash does not match its text content", """
        <aodm:knowledge xmlns:aodm="http://fucaspark.com/aodm/1.2">
          <aodm:entity id="e" type="thing" hash="sha256:%s">Text here.</aodm:entity>
        </aodm:knowledge>""" % ("0" * 64), ["H4"]),

    ("XSD: entity without a type", """
        <aodm:knowledge xmlns:aodm="http://fucaspark.com/aodm/1.2">
          <aodm:entity id="e"/>
        </aodm:knowledge>""", ["XSD"]),
]

def have(cmd):
    return shutil.which(cmd) is not None

def runners():
    out = {}
    out["python"] = lambda p: subprocess.run(
        [sys.executable, os.path.join(ROOT, "parsers/python/aodm.py"), "--validate", p],
        capture_output=True, text=True)

    if have("node"):
        js = os.path.join(ROOT, "parsers/javascript/aodm.js")
        script = (
            "const {parse}=require(%r);const fs=require('fs');"
            "try{const d=parse(fs.readFileSync(process.argv[1],'utf8'));"
            "d.validate().forEach(i=>console.log(i.severity.toUpperCase()+' '+i.rule+': '+i.message));}"
            "catch(e){console.log('ERROR PARSE: '+e.message);}" % js
        )
        out["javascript"] = lambda p: subprocess.run(
            ["node", "-e", script, p], capture_output=True, text=True)

    javac = os.path.join(JAVA_BIN, "javac")
    java = os.path.join(JAVA_BIN, "java")
    if os.path.exists(java) or have("java"):
        jbin = java if os.path.exists(java) else "java"
        jc = javac if os.path.exists(javac) else "javac"
        classes = os.path.join(tempfile.gettempdir(), "aodm-java-conf")
        os.makedirs(classes, exist_ok=True)
        subprocess.run([jc, "-d", classes, os.path.join(ROOT, "parsers/java/Aodm.java")],
                       capture_output=True, text=True)
        if os.path.exists(os.path.join(classes, "Aodm.class")):
            out["java"] = lambda p: subprocess.run(
                [jbin, "-cp", classes, "Aodm", "--validate", p], capture_output=True, text=True)

    if have("dotnet"):
        proj = os.path.join(ROOT, "parsers/csharp")
        env = dict(os.environ, DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_NOLOGO="1")
        out["csharp"] = lambda p: subprocess.run(
            ["dotnet", "run", "--project", proj, "-v", "quiet", "--nologo", "--", "--validate", p],
            capture_output=True, text=True, env=env)

    return out

def rules_from(result):
    codes = set()
    for line in (result.stdout + result.stderr).splitlines():
        line = line.strip()
        if line.startswith("ERROR "):
            codes.add(line.split()[1].rstrip(":"))
        elif line.startswith("ERROR PARSE"):
            codes.add("PARSE")
    return codes

def main():
    impls = runners()
    expected_all = ["python", "javascript", "java", "csharp"]
    missing = [i for i in expected_all if i not in impls]

    print(f"Implementations under test: {', '.join(impls)}")
    if missing:
        print(f"SKIPPED (toolchain unavailable): {', '.join(missing)}")
    print()

    failures = 0
    disagreements = 0

    for name, xml, expect in CASES:
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-8") as fh:
            fh.write(xml.strip())
            path = fh.name
        try:
            got = {k: rules_from(fn(path)) for k, fn in impls.items()}
        finally:
            os.unlink(path)

        exp = set(expect)
        agree = len({frozenset(v) for v in got.values()}) == 1
        correct = all(exp <= v for v in got.values()) and (
            all(not v for v in got.values()) if not exp else True)

        ok = agree and all(exp <= v for v in got.values()) and (exp or not any(got.values()))
        status = "PASS" if ok else "FAIL"
        if not ok:
            failures += 1
            if not agree:
                disagreements += 1
        print(f"  {status}  {name}")
        if not ok:
            for k, v in got.items():
                print(f"          {k:11} -> {sorted(v) or '(none)'}   expected {sorted(exp) or '(none)'}")

    total = len(CASES)
    print(f"\n{total - failures}/{total} cases passed across {len(impls)} implementations")
    if disagreements:
        print(f"{disagreements} case(s) where implementations DISAGREED — the specification "
              f"is ambiguous there, not just one parser.")
    if missing:
        print(f"NOTE: {', '.join(missing)} were not exercised.")
    return 1 if failures else 0

if __name__ == "__main__":
    sys.exit(main())
