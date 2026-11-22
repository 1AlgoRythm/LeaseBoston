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



import time

def buttons(*names):
    """Return {name: ref} for the first match of each button name that is present."""
    out = {}
    for n in names:
        r = ref("button", n)
        if r: out[n] = r
    return out

def send(prompt):
    box = ref("textfield", "Write your prompt to Claude") or ref("textfield", "Write a message")
    t = run("type", box, prompt, headed=True)
    run("press", "return", "--app", "Claude", headed=True)
    return t.get("ok")

def wait_done(approve="Allow once", timeout=180, log=print):
    """Click approval buttons as they appear; return when Claude stops generating."""
    t0, idle, seen_busy = time.time(), 0, False
    while time.time() - t0 < timeout:
        time.sleep(2)
        b = buttons(approve)
        if b:
            run("click", b[approve]); log(f"  approved at {round(time.time()-t0)}s"); idle = 0; continue
        d = run("find", "--app", "Claude", "--role", "button", "--name", "Stop")
        busy = bool(d.get("ok") and d["data"].get("total_matches"))  # ok is true even with 0 matches
        seen_busy |= busy
        idle = 0 if busy else idle + 1
        if idle >= 2 and (seen_busy or time.time() - t0 > 15):
            log(f"  saw busy: {seen_busy}")
            return round(time.time() - t0)
    return None
