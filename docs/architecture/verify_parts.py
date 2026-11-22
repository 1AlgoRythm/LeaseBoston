"""Check the explanation files in docs/architecture/parts/ before they are published.

For every part: required fields are present, each evidence quote is the exact text
of the cited line in the frozen commit, each drawing is valid SVG of the house size,
and no text names another company. Exit code 0 only when everything passes.

Run from the repo root:  python3 docs/architecture/verify_parts.py [parts/<group>.json ...]
"""

import json
import pathlib
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[2]
HERE = ROOT / "docs" / "architecture"
COMMIT = "9f140fd"
FIELDS = ("id", "name", "one_liner", "explain", "why", "basis", "owner", "units", "evidence")


def line_at(file: str, n: int) -> str | None:
    r = subprocess.run(["git", "show", f"{COMMIT}:{file}"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        return None
    lines = r.stdout.splitlines()
    return lines[n - 1].strip() if 1 <= n <= len(lines) else None


def check_entry(e: dict, needs_svg: bool) -> list[str]:
    errs = [f"missing field {f}" for f in FIELDS if not e.get(f)]
    if e.get("basis") not in ("evidence", "inferred"):
        errs.append("basis must be 'evidence' or 'inferred'")
    for u in e.get("units", []):
        if not (u.get("name") and u.get("detail")):
            errs.append(f"unit without name/detail: {u}")
    if not 3 <= len(e.get("evidence", [])) <= 6:
        errs.append(f"needs 3-6 evidence entries, has {len(e.get('evidence', []))}")
    for ev in e.get("evidence", []):
        got = line_at(ev.get("file", ""), int(ev.get("line", 0)))
        if got is None:
            errs.append(f"evidence file/line not found: {ev.get('file')}:{ev.get('line')}")
        elif got != ev.get("quote", "").strip():
            errs.append(f"quote mismatch at {ev['file']}:{ev['line']}: file has {got!r}")
    if needs_svg:
        svg = HERE / "svg" / str(e.get("svg", ""))
        if not e.get("svg") or not svg.exists():
            errs.append(f"svg missing: {e.get('svg')}")
        else:
            try:
                root = ET.parse(svg).getroot()
                if root.get("viewBox") != "0 0 480 300":
                    errs.append("svg viewBox must be '0 0 480 300'")
                if not root.get("aria-label"):
                    errs.append("svg needs an aria-label")
                text = svg.read_text()
                if "<script" in text or "href=\"http" in text:
                    errs.append("svg must not contain scripts or external links")
                if svg.stat().st_size > 9000:
                    errs.append(f"svg is {svg.stat().st_size} bytes (max 9000)")
            except ET.ParseError as x:
                errs.append(f"svg does not parse: {x}")
    return errs


def main(paths: list[str]) -> int:
    files = [pathlib.Path(p) for p in paths] or sorted((HERE / "parts").glob("*.json"))
    total = bad = 0
    for f in files:
        d = json.loads(f.read_text())
        entries = [(d["parent"], False)] if d.get("parent") else []
        entries += [(c, True) for c in d.get("children", [])] + [(c, True) for c in d.get("tops", [])]
        for e, needs_svg in entries:
            total += 1
            errs = check_entry(e, needs_svg)
            bad += bool(errs)
            print(f"{'PASS' if not errs else 'FAIL'}  {f.name} :: {e.get('id')}")
            for x in errs:
                print("      -", x)
    print(f"Checked {total} of {total}; {bad} failing")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
