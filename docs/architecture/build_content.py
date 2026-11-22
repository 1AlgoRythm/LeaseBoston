"""Assemble the part explanations into the portfolio's content.json and a GitHub-readable README.

Inputs:  docs/architecture/parts/*.json (one per part group), svg/*.svg, the delivered diagram HTML.
Outputs: docs/architecture/content.json, docs/architecture/README.md, and, with --site DIR,
         a copy of everything the portfolio page needs in DIR (flat folder, like the other projects).

Run from the repo root:  python3 docs/architecture/build_content.py [--site /path/to/projects/leaseboston]
"""

import json
import pathlib
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
REPO = "https://github.com/1AlgoRythm/LeaseBoston"
COMMIT = "9f140fd2ef6d25c2a4d41b81522ebe0317c5771e"

# Top-level parts in reading order: (part id, parts file, sub-diagram or None)
ORDER = [
    ("mcp-server", "mcp-server", "mcp"), ("chat-card", "chat-card", "card"),
    ("question-lifecycle", "question-lifecycle", "lifecycle"), ("answer-matcher", "answer-matcher", "matcher"),
    ("search-ranking", "search-ranking", "search"), ("landlord-inbox", "landlord-inbox", "inbox"),
    ("notifications", "atomic", None), ("data-store", "atomic", None), ("seed-data", "atomic", None),
    ("tests", "tests", "tests"), ("demo-recorder", "demo-recorder", "demo"),
]

PITCH = ("I built LeaseBoston, an MCP server that brings apartment search into Claude and ChatGPT. Renters see ranked "
         "listings as cards in the chat and can ask a landlord anything. If the landlord already answered, the saved "
         "answer comes back word for word. If not, the renter can send the question with one click, and the landlord "
         "replies from an inbox. Every reply can be saved, so the next renter gets it instantly. It has 29 tests and a "
         "demo recorded live in Claude Desktop.")


def load_parts():
    return {f.stem: json.loads(f.read_text()) for f in sorted((HERE / "parts").glob("*.json"))}


def build():
    parts, comps = load_parts(), []
    for pid, file, sub in ORDER:
        d = parts[file]
        if sub:
            entry = dict(d["parent"], id=pid, sub=f"{sub}.html",
                         sub_map={c["id"]: c["id"] for c in d["children"]}, children=d["children"])
        else:
            entry = next(t for t in d["tops"] if t["id"] == pid)
        comps.append(entry)
    return {"slug": "leaseboston", "title": "LeaseBoston: Apartment Search Inside Claude", "repo": REPO, "team": "solo",
            "pitch": PITCH, "stack": ["Python", "MCP Python SDK 2.3.0 (MCPServer, Apps)", "SQLite", "Starlette",
                                      "agent-desktop", "ffmpeg"],
            "archify": "architecture.html", "archify_quality": "showcase", "components": comps}


def link(ev):
    return f"[`{ev['file']}:{ev['line']}`]({REPO}/blob/{COMMIT}/{ev['file']}#L{ev['line']})"


def readme(c):
    out = ["# How LeaseBoston works, part by part", "",
           "Every part of the system is explained here. A big part has its own architecture diagram (open the `.html` "
           "file in a browser). Its smallest pieces each have a hand-drawn animation. Code links point to commit "
           f"[`{COMMIT[:7]}`]({REPO}/tree/{COMMIT}).", "",
           "The overview diagram is [`index.html`](index.html). The portfolio version, with clickable boxes, is on "
           "[satyaasudarshan.me](https://satyaasudarshan.me/#leaseboston).", ""]
    def block(k, level):
        h = "#" * level
        out.extend([f"{h} {k['name']}", "", f"*{k['one_liner']}*", ""])
        if k.get("svg"):
            out.extend([f"![{k['name']}](svg/{k['svg']})", ""])
        if k.get("sub"):
            out.extend([f"Diagram: [`{k['sub']}`]({k['sub']})", ""])
        out.extend([k["explain"], "", f"**Why it matters.** {k['why']}", "", "**Smallest pieces:**", ""])
        out.extend(f"- `{u['name']}`: {u['detail']}" for u in k["units"])
        out.extend(["", "**See the code:** " + " · ".join(link(e) for e in k["evidence"]), ""])
        for ch in k.get("children", []):
            block(ch, level + 1)
    for k in c["components"]:
        block(k, 2)
    return "\n".join(out)


BACK = '<script src="../../site-back.js"></script>\n'


def put_page(src, dst):
    """Copy a diagram page for the portfolio, with the same 'Back to portfolio' script the other projects use."""
    html = src.read_text()
    assert "</body>" in html
    dst.write_text(html.replace("</body>", BACK + "</body>", 1))


def main(args):
    c = build()
    (HERE / "content.json").write_text(json.dumps(c, indent=1, ensure_ascii=False) + "\n")
    (HERE / "README.md").write_text(readme(c))
    n_parts = sum(1 + len(k.get("children", [])) for k in c["components"])
    print(f"content.json and README.md written: {len(c['components'])} top parts, {n_parts} explained parts")
    if "--site" in args:
        site = pathlib.Path(args[args.index("--site") + 1])
        site.mkdir(parents=True, exist_ok=True)
        shutil.copy(HERE / "content.json", site / "content.json")
        put_page(HERE / "index.html", site / "architecture.html")
        shutil.copy(HERE / "overview.json", site / "archify.json")
        for _, _, sub in ORDER:
            if sub:
                put_page(HERE / f"{sub}.html", site / f"{sub}.html")
        for svg in (HERE / "svg").glob("*.svg"):
            shutil.copy(svg, site / svg.name)
        shutil.copy(ROOT / "docs" / "demo.mp4", site / "demo.mp4")
        print("site folder:", site)


if __name__ == "__main__":
    main(sys.argv[1:])
