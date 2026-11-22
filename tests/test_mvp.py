"""End-to-end and unit tests. Run: uv run pytest -q

The two journey tests start the real server as a separate process, once over
stdio (how Claude Desktop runs it) and once over HTTP (how ChatGPT reaches it),
and drive it with the official MCP client.
"""

import asyncio
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setenv("LEASE_DB", str(path))
    from leaseapp import db as dbmod
    dbmod.init(reset=True)
    return path


# ---------- matcher: the landlord's saved answer, or nothing ----------

MATCH_CASES = [
    # (listing, renter's words, saved question that must answer it, or None = must go to the landlord)
    ("A101", "Can I park my car there?", "Is parking available?"),
    ("A101", "Is heat included?", "Are utilities included in the rent?"),
    ("A101", "how much is the deposit", "What is the security deposit?"),
    ("A101", "Do I need a cosigner as an international student?", "Do you accept international students without a US cosigner?"),
    ("A103", "is there a fee for my dog?", "Is there a pet fee for dogs?"),
    ("A202", "Is parking included?", "Is parking included in the rent?"),
    ("A301", "Can I sublease in summer", "Can I sublet in the summer?"),
    ("A402", "Are pets ok?", "Are pets allowed?"),
    ("A601", "when can I tour?", "Can I schedule a tour?"),
    ("A302", "is the driveway included", "Is parking included in the rent?"),
    # Must NOT answer: no saved answer on this topic for this landlord or unit.
    ("A201", "is parking included in rent?", None),   # regression: matched the utilities answer on "included rent"
    ("A402", "Is that allowed?", None),               # only filler words: must not match "Are pets allowed?"
    ("A601", "is internet included", None),           # L6 has no utilities answer
    ("A501", "what's the security deposit", None),    # L5 has no deposit answer
    ("A401", "Is a shorter lease possible?", None),   # the short-lease answer belongs to A403 only
    ("A101", "Can I sublet over the summer?", None),
    ("A101", "Is the rent negotiable?", None),
    ("A101", "Is the building quiet at night?", None),
]


@pytest.mark.parametrize("listing,question,expected", MATCH_CASES)
def test_saved_answer_matching(db, listing, question, expected):
    from leaseapp import service
    r = service.ask_landlord(listing, question)
    if expected is None:
        assert r["status"] == "not_answered", r
    else:
        assert r["status"] == "answered", r
        assert f'"{expected}"' in r["source"]


def test_every_question_is_logged_for_the_landlord(db):
    from leaseapp import service
    from leaseapp.db import connect
    service.ask_landlord("A101", "Can I park my car there?")
    service.ask_landlord("A101", "Is the building quiet at night?")
    with connect() as c:
        rows = {r["question"]: r["status"] for r in c.execute("SELECT question, status FROM questions")}
    assert rows == {"Can I park my car there?": "auto_answered", "Is the building quiet at night?": "not_sent"}


# ---------- recommendation ----------

def test_search_filters_and_explains(db):
    from leaseapp import service
    r = service.search({"max_rent": 3200, "min_beds": 1, "pets": "cat", "near": "Northeastern University"}, 5)
    assert r["matches"], r
    for m in r["matches"]:
        assert m["rent"] <= 3200 and m["beds"] >= 1 and m["pets"] in ("cats", "cats_and_dogs")
        assert any("Northeastern" in why for why in m["why_it_fits"])
    scores = [m["fit_score"] for m in r["matches"]]
    assert scores == sorted(scores, reverse=True)


def test_search_offers_near_misses_when_nothing_fits(db):
    from leaseapp import service
    r = service.search({"max_rent": 1500, "min_beds": 0}, 3)
    assert r["matches"] == []
    assert r["near_misses"] and all(len(m["why_not"]) == 1 for m in r["near_misses"])


def test_dog_owner_never_sees_cats_only(db):
    from leaseapp import service
    r = service.search({"pets": "dog"}, 10)
    assert r["matches"] and all(m["pets"] == "cats_and_dogs" for m in r["matches"])


# ---------- send / reply rules ----------

def test_send_is_idempotent_and_validates_contact(db):
    from leaseapp import service
    from leaseapp.db import connect
    ref = service.ask_landlord("A101", "Is the building quiet at night?")["reference_code"]
    with pytest.raises(service.UserError):
        service.send_to_landlord(ref, "Ana", "email", "not-an-email")
    service.send_to_landlord(ref, "Ana", "email", "ana@example.com")
    again = service.send_to_landlord(ref, "Ana", "email", "ana@example.com")
    assert again["status"] == "waiting"
    with connect() as c:
        assert c.execute("SELECT COUNT(*) FROM outbox WHERE question_ref = ?", (ref,)).fetchone()[0] == 2  # landlord + renter, once


def test_landlord_cannot_answer_another_landlords_question(db):
    from leaseapp import service
    ref = service.ask_landlord("A101", "Is the building quiet at night?")["reference_code"]
    service.send_to_landlord(ref, "Ana", "chat_only", None)
    with pytest.raises(service.UserError):
        service.landlord_reply("L2", ref, "Yes", None)


# ---------- the whole journey, over the real transports ----------

async def journey(client: Client, post_reply) -> None:
    tools = {t.name for t in (await client.list_tools()).tools}
    assert tools == {"search_apartments", "get_apartment", "ask_landlord", "send_question_to_landlord",
                     "check_landlord_reply"}
    assert "Never guess a landlord's policy" in (client.instructions or "")

    found = (await client.call_tool("search_apartments", {"max_rent": 3000, "pets": "cat",
                                                          "near": "Northeastern University"})).structured_content
    listing = found["matches"][0]["id"]

    saved = (await client.call_tool("ask_landlord", {"listing_id": "A101", "question": "Can I park my car?"})).structured_content
    assert saved["status"] == "answered" and "resident parking permit" in saved["answer"]

    new_q = "Is the building quiet at night?"
    open_q = (await client.call_tool("ask_landlord", {"listing_id": "A101", "question": new_q})).structured_content
    assert open_q["status"] == "not_answered"
    ref = open_q["reference_code"]

    bad = await client.call_tool("get_apartment", {"listing_id": "ZZZ"})
    assert bad.is_error and "No listing" in bad.content[0].text

    sent = (await client.call_tool("send_question_to_landlord", {
        "reference_code": ref, "renter_name": "Ana", "channel": "email", "contact": "ana@example.com"})).structured_content
    assert sent["status"] == "waiting"

    status = (await client.call_tool("check_landlord_reply", {"reference_code": ref})).structured_content
    assert status["status"] == "waiting"

    post_reply("L1", ref, "Very quiet, the bedrooms face the courtyard.")

    status = (await client.call_tool("check_landlord_reply", {"reference_code": ref})).structured_content
    assert status["status"] == "replied" and "courtyard" in status["landlord_reply"]

    # The reply became a saved answer, so the next renter gets it at once.
    again = (await client.call_tool("ask_landlord", {"listing_id": "A101", "question": new_q})).structured_content
    assert again["status"] == "answered" and "courtyard" in again["answer"]
    assert listing


def outbox_rows(db_path):
    import sqlite3
    with sqlite3.connect(db_path) as c:
        return c.execute("SELECT channel, recipient, subject, status FROM outbox ORDER BY id").fetchall()


def test_journey_over_stdio(db):
    from leaseapp import service

    def reply(lid, ref, text):  # the landlord page writes to the same database
        service.landlord_reply(lid, ref, text, "listing")

    server = StdioServerParameters(command=sys.executable, args=["-m", "leaseapp", "stdio"], cwd=str(ROOT),
                                   env={"LEASE_DB": str(db)})

    async def run():
        async with Client(server) as c:
            await journey(c, reply)
    asyncio.run(run())

    rows = outbox_rows(db)
    assert [r[1] for r in rows] == ["priya@fenwayflats.example.com", "ana@example.com", "ana@example.com"]
    assert all(r[3] == "simulated" for r in rows)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def http_server(db):
    port = free_port()
    proc = subprocess.Popen([sys.executable, "-m", "leaseapp", "serve", "--port", str(port),
                             "--public-host", "demo.trycloudflare.com"],
                            cwd=ROOT, env={**os.environ, "LEASE_DB": str(db)},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.1).close()
            break
        except OSError:
            time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    proc.terminate()
    proc.wait(5)


def http(url, data=None, host=None):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode() if data else None)
    if host:
        req.add_header("Host", host)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_journey_over_http_with_landlord_page(http_server, db):
    def reply(lid, ref, text):  # exactly what the landlord's form submits
        code, _ = http(f"{http_server}/landlord/{lid}/reply/{ref}", {"reply": text, "save": "on", "save_as": "listing"})
        assert code == 200  # after the 303 redirect back to the page

    async def run():
        async with Client(f"{http_server}/mcp") as c:
            await journey(c, reply)
    asyncio.run(run())

    code, page = http(f"{http_server}/landlord/L1")
    assert code == 200 and "Is the building quiet at night?" in page and "You replied" in page
    code, page = http(f"{http_server}/outbox")
    assert code == 200 and "priya@fenwayflats.example.com" in page


def test_landlord_page_is_localhost_only(http_server):
    code, _ = http(f"{http_server}/landlord", host="demo.trycloudflare.com")
    assert code == 403
    code, _ = http(f"{http_server}/landlord")
    assert code == 200


def test_mcp_accepts_the_tunnel_host_but_not_others(http_server):
    body = b'{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
    for host, ok in (("demo.trycloudflare.com", True), ("evil.example", False)):
        req = urllib.request.Request(f"{http_server}/mcp", data=body, headers={
            "Host": host, "Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
        try:
            urllib.request.urlopen(req).close()
            code = 200
        except urllib.error.HTTPError as e:
            code = e.code
        assert (code not in (403, 421)) == ok, (host, code)


# ---------- the in-chat card (MCP App) ----------

def test_card_is_attached_to_search_and_ask(db):
    from mcp.server.apps import APP_MIME_TYPE
    from leaseapp.mcp_server import CARD, mcp

    async def run():
        async with Client(mcp) as c:
            tools = {t.name: t for t in (await c.list_tools()).tools}
            for name in ("search_apartments", "ask_landlord"):
                assert tools[name].meta["ui"]["resourceUri"] == CARD
            for name in ("get_apartment", "send_question_to_landlord", "check_landlord_reply"):
                assert not (tools[name].meta or {}).get("ui")
            res = await c.read_resource(CARD)
            assert res.contents[0].mime_type == APP_MIME_TYPE
            assert "ui/initialize" in res.contents[0].text and "send_question_to_landlord" in res.contents[0].text
    asyncio.run(run())
