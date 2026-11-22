"""Drive the LeaseBoston demo in Claude Desktop + the landlord page, while recording the screen.

Writes demo/out/raw.mov, demo/out/raw2.mov and demo/out/steps.json (label, start, end seconds).
Setup and the hands-off warning are in demo/README.md.
"""
import json, os, signal, subprocess, sys, time
from pathlib import Path
HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import ad

OUT = str(HERE / "out")
os.makedirs(OUT, exist_ok=True)
steps, T0 = [], None
CHROME_W = None  # the landlord page window, found by its title in main()


def now():
    return round(time.time() - T0, 1)


def step(label):
    print(f"[{now():6.1f}] {label}", flush=True)
    steps.append({"label": label, "start": now()})


def end_step():
    steps[-1]["end"] = now()


def matches(name, role=None, app="Claude", exact=False):
    args = ["find", "--app", app, "--name", name] + (["--window-id", CHROME_W] if app == "Google Chrome" else []) + (["--role", role] if role else []) + (["--exact"] if exact else [])
    d = ad.run(*args)
    data = d.get("data") or {}
    return data.get("matches") or ([data["match"]] if data.get("match") else [])


def click(name, role="button", app="Claude", index=0, exact=False):
    m = matches(name, role, app, exact)
    if not m:
        print(f"   ! no '{name}'", flush=True); return False
    r = ad.run("click", m[index]["ref_id"])
    return r.get("ok")


def type_into(placeholder, text, app="Claude", index=-1, role="textfield"):
    m = matches(placeholder, role, app)
    if not m:
        print(f"   ! no field '{placeholder}'", flush=True); return False
    return ad.run("type", m[index]["ref_id"], text, headed=True).get("ok")


def focus(app):
    if app == "Google Chrome":
        wid = CHROME_W
    else:
        w = ad.run("list-windows", "--app", app)["data"]
        wid = [x for x in w if x.get("visible")][0]["id"]
    ad.run("focus-window", "--app", app, "--window-id", wid)
    time.sleep(0.8)


def send(prompt):
    type_into("Write your prompt to Claude", prompt) or type_into("Write a message", prompt) \
        or type_into("Or reply directly", prompt)
    time.sleep(0.6)
    click("Send message")


def wait_done(timeout=200):
    t, idle, seen = time.time(), 0, False
    while time.time() - t < timeout:
        time.sleep(1.5)
        if matches("Allow once", "button"):
            time.sleep(1.2)  # let the viewer see the approval prompt
            click("Allow once"); print("   approved", flush=True); idle = 0; continue
        busy = bool(matches("Stop response", "button"))
        seen |= busy
        idle = 0 if busy else idle + 1
        if idle >= 2 and (seen or time.time() - t > 20):
            time.sleep(1.5)
            return True
    print("   ! wait timed out", flush=True)
    return False


def new_chat():
    """Open a fresh chat. The sidebar flashes open, so never call this while recording."""
    click("Show sidebar"); time.sleep(1.2)       # New lives in the sidebar
    click("New", "button", exact=True); time.sleep(1.5)
    click("Hide sidebar"); time.sleep(1.2)
    if not matches("Write your prompt to Claude", "textfield") or matches("Hide sidebar"):
        raise SystemExit("no fresh chat, or sidebar still open; stopping before recording")


def main():
    global T0, CHROME_W
    wins = ad.run("list-windows", "--app", "Google Chrome").get("data") or []
    CHROME_W = next((w["id"] for w in wins if w.get("title") == "Doyle Family Rentals"), None)
    if not CHROME_W:
        raise SystemExit("open the landlord page first (see demo/README.md)")
    time.sleep(10)  # time to read the HANDS OFF warning in Obsidian
    # ---------- setup ----------
    subprocess.run(["uv", "--directory", str(REPO), "run", "python", "-m", "leaseapp", "reset"],
                   check=True, capture_output=True)
    # reload both sides with the new design: the landlord server and Claude Desktop (which restarts the stdio server)
    subprocess.run(["pkill", "-f", "leaseapp serve --port 8000"])
    subprocess.Popen(f"cd '{REPO}' && exec uv run python -m leaseapp serve --port 8000"
                     " > /tmp/leaseboston-serve-8000.log 2>&1", shell=True, start_new_session=True)
    subprocess.run(["osascript", "-e", 'tell application "Claude" to quit'])
    for _ in range(40):
        if subprocess.run(["pgrep", "-x", "Claude"], capture_output=True).returncode: break
        time.sleep(0.5)
    subprocess.run(["open", "-a", "Claude"]); time.sleep(14)
    cw = [x for x in ad.run("list-windows", "--app", "Claude")["data"] if x.get("visible")][0]["id"]
    ad.run("resize-window", "--app", "Claude", "--window-id", cw, "--width", "800", "--height", "949")
    ad.run("move-window", "--app", "Claude", "--window-id", cw, "--x", "0", "--y", "33")
    ad.run("resize-window", "--app", "Google Chrome", "--window-id", CHROME_W, "--width", "712", "--height", "949")
    ad.run("move-window", "--app", "Google Chrome", "--window-id", CHROME_W, "--x", "800", "--y", "33")
    want = {"Claude": (cw, 0, 800), "Google Chrome": (CHROME_W, 800, 712)}
    for app, (wid, x, w) in want.items():
        for _ in range(3):
            b = [x_ for x_ in ad.run("list-windows", "--app", app)["data"] if x_["id"] == wid][0]["bounds"]
            if (b["x"], b["width"], b["height"]) == (x, w, 949): break
            ad.run("resize-window", "--app", app, "--window-id", wid, "--width", str(w), "--height", "949")
            ad.run("move-window", "--app", app, "--window-id", wid, "--x", str(x), "--y", "33"); time.sleep(1)
        else:
            raise SystemExit(f"setup failed: {app} window is {b}, not x={x} w={w}; nothing recorded")
    sess = ad.run("session", "start", "--cursor", "--name", "leaseboston-demo")
    print("session:", json.dumps(sess.get("data"))[:200], flush=True)
    sid = (sess.get("data") or {}).get("session_id") or (sess.get("data") or {}).get("id")
    if sid:
        os.environ["AGENT_DESKTOP_SESSION"] = sid
        ad.run("cursor-overlay", "enable", "--label", "Demo agent", "--size", "1.4", "--dwell-ms", "250")
    focus("Google Chrome"); click("Refresh", "link", app="Google Chrome")
    focus("Claude")
    new_chat()

    rec = subprocess.Popen(["screencapture", "-v", "-x", "-k", "-R0,33,1512,949", f"{OUT}/raw.mov"])
    time.sleep(2)
    T0 = time.time()

    try:
        step("1. Search inside Claude: listing cards")
        send("I'm a Northeastern student with a cat. Budget is $3000 a month, at least 1 bedroom. Use LeaseBoston to find my best options.")
        wait_done(); end_step()

        step("2. Ask from the card: the landlord's saved answer")
        m = matches("Ask landlord", "button")
        ad.run("click", m[1]["ref_id"]) if len(m) > 1 else None   # second tile = A101, Fenway Flats
        time.sleep(0.8)
        type_into("e.g. Is parking included?", "Is parking included?")
        time.sleep(0.5)
        click("Ask", exact=True)
        time.sleep(1.5)
        click("Send message")
        wait_done(); end_step()

        step("3. New question: not answered, renter sends it from the card")
        send("Ask the landlord of A203: is the building quiet at night?")
        wait_done()
        if matches("Skip", "button"):
            time.sleep(1.5); click("Skip")
        time.sleep(1)
        type_into("Your name", "Satyaa")
        type_into("Email address", "satyaa@example.com")
        time.sleep(0.8)
        click("Send to landlord", index=-1)
        time.sleep(2)
        wait_done(timeout=30)
        if matches("Send message", "button"):
            click("Send message"); wait_done()
        end_step()

        step("4. Another question: renter says don't send it")
        send("Ask the landlord of A203: can I store a bike in the basement?")
        wait_done()
        if matches("t send it"):
            time.sleep(1.5); click("t send it", role=None)
        else:
            time.sleep(1.5); send("No, don't send that one.")
        wait_done()
        end_step()

        step("5. Landlord's end: questions arrive, landlord replies")
        focus("Google Chrome")
        click("Refresh", "link", app="Google Chrome"); time.sleep(3)
        type_into("Type your reply", "Yes, it's very quiet. The bedrooms face the back garden, and quiet hours start at 10pm.",
                  app="Google Chrome", index=0, role=None)
        time.sleep(1)
        click("Send reply", app="Google Chrome"); time.sleep(3)
        click("Can I store a bike", "link", app="Google Chrome"); time.sleep(2.5)
        type_into("Add a saved answer", "Yes. There's a locked bike room in the basement, free for all tenants.",
                  app="Google Chrome", index=0, role=None)
        time.sleep(1)
        click("Save answer", app="Google Chrome"); time.sleep(3)
        click("Saved answers", "link", app="Google Chrome"); time.sleep(3.5)
        click("Outbox", "link", app="Google Chrome"); time.sleep(5)
        click("Inbox", "link", app="Google Chrome"); time.sleep(2)
        end_step()

        step("6. Renter checks back: the landlord's reply")
        focus("Claude")
        send("Did the landlord reply to my question about A203?")
        wait_done(); end_step()

        rec.send_signal(signal.SIGINT); rec.wait(timeout=30)   # pause recording: the sidebar flashes
        new_chat()
        rec = subprocess.Popen(["screencapture", "-v", "-x", "-k", "-R0,33,1512,949", f"{OUT}/raw2.mov"])
        time.sleep(2)
        T0 = time.time()
        step("7. Next renter: answered instantly from the landlord's new answer")
        steps[-1]["file"] = "raw2.mov"
        send("Hi, I'm looking at A203. Ask the landlord: can I store my bike in the basement?")
        wait_done(); time.sleep(2); end_step()
    finally:
        if rec.poll() is None:
            rec.send_signal(signal.SIGINT); rec.wait(timeout=30)
        ad.run("cursor-overlay", "disable"); ad.run("session", "end")
        json.dump(steps, open(f"{OUT}/steps.json", "w"), indent=1)
        subprocess.run(["open", "-a", "Obsidian"])   # back to Obsidian = the demo is over
        print("DONE", flush=True)


if __name__ == "__main__":
    try:
        main()
    finally:
        subprocess.run(["open", "-a", "Obsidian"])   # even if setup fails, hand the screen back
