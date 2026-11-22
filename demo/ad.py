"""Tiny wrapper around the agent-desktop CLI: find a ref, act, read text."""
import json, subprocess, sys

def run(*args, headed=False):
    cmd = ["agent-desktop"] + (["--headed"] if headed else []) + list(args)
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    return json.loads(out, strict=False)

def ref(role, name, app="Claude"):
    d = run("find", "--app", app, "--role", role, "--name", name, "--first")
    if not d.get("ok") or not (d["data"].get("match") or d["data"].get("matches")):
        return None
    data = d["data"]
    items = data if isinstance(data, list) else [data.get("match") or {}] + (data.get("matches") or [])
    for it in items:
        r = it.get("ref_id") or it.get("ref")
        if r: return r
    return None

if __name__ == "__main__":
    print(json.dumps(run(*sys.argv[1:]), indent=1)[:3000])
