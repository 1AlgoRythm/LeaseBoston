"""The landlord's end: an inbox where renter questions arrive.

Plain HTML pages added to the same web app that serves /mcp. They answer only
on localhost, so a public tunnel for ChatGPT exposes /mcp but never this page
(it shows renters' contact details and has no login yet).

Style: Snugd's own tokens, measured from snugd.ai on 2026-11-22.
"""

from datetime import datetime, timezone
from html import escape as e
from urllib.parse import parse_qs

from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from . import service
from .db import connect
from .mcp_server import mcp

LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}

STYLE = """<style>
:root{--green:#2D6A4F;--green-dark:#1B4332;--green-soft:#E7F1EC;--page:#FAFAF8;--ink:#1A1A1A;--grey:#6B7280;
--line:#E8E5E0;--amber:#B7791F;--amber-soft:#FBF3E4;--blue:#3B6FB6;--blue-soft:#E8F0FA}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--ink);font:14px/1.45 "DM Sans",system-ui,-apple-system,sans-serif}
a{color:inherit;text-decoration:none}
header{display:flex;align-items:center;gap:14px;padding:14px 20px;background:#fff;border-bottom:1px solid var(--line);flex-wrap:wrap}
.logo{font-weight:700;font-size:16px}.logo .heart{color:#E4572E;margin-right:4px}.logo small{font-weight:500;color:var(--grey)}
nav{display:flex;gap:4px;margin-left:auto}nav a{padding:6px 12px;border-radius:10px;color:var(--grey);font-weight:600;font-size:13px}
nav a.on,nav a:hover{background:var(--green-soft);color:var(--green-dark)}
main{padding:16px 20px}h1{font-size:20px;margin:0 0 12px;letter-spacing:-.01em}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:14px}
.stat{background:#fff;border:1px solid var(--line);border-radius:14px;padding:10px 14px}
.stat b{display:block;font-size:22px;letter-spacing:-.02em}.stat span{color:var(--grey);font-size:12px}
.inbox{display:grid;grid-template-columns:minmax(200px,38%) 1fr;background:#fff;border:1px solid var(--line);border-radius:16px;overflow:hidden;min-height:430px}
.list{border-right:1px solid var(--line);overflow-y:auto;max-height:640px}
.item{display:block;padding:11px 14px;border-bottom:1px solid var(--line)}.item:hover{background:var(--page)}
.item.on{background:var(--green-soft)}.item .t{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.item .m{color:var(--grey);font-size:12px;display:flex;gap:6px;align-items:center}
.dot{width:8px;height:8px;border-radius:99px;display:inline-block;flex:none}
.waiting{background:var(--amber)}.replied{background:var(--green)}.auto_answered{background:var(--blue)}.not_sent{background:#B9B4AC}
.detail{padding:18px 20px}.q{font-size:18px;font-weight:600;margin:6px 0 10px;letter-spacing:-.01em}
.pill{display:inline-flex;gap:6px;align-items:center;font-size:11.5px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;padding:3px 9px;border-radius:99px}
.p-waiting{background:var(--amber-soft);color:var(--amber)}.p-replied{background:var(--green-soft);color:var(--green)}
.p-auto_answered{background:var(--blue-soft);color:var(--blue)}.p-not_sent{background:#F1F0ED;color:var(--grey)}
.who{display:flex;gap:18px;flex-wrap:wrap;color:var(--grey);font-size:13px;margin-bottom:14px}.who b{color:var(--ink);font-weight:600}
.box{border:1px solid var(--line);border-radius:12px;padding:12px 14px;background:var(--page);margin:10px 0}
textarea,input[type=text],select{font:inherit;width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:12px;background:#fff;color:var(--ink)}
textarea{min-height:96px;resize:vertical}textarea:focus,input:focus{outline:2px solid var(--green-soft);border-color:var(--green)}
.bar{display:flex;align-items:center;gap:12px;margin-top:10px;flex-wrap:wrap}.bar label{color:var(--grey);font-size:13px}
button{font:inherit;font-weight:600;cursor:pointer;border-radius:12px;padding:9px 18px;border:none;background:var(--green);color:#fff;margin-left:auto}
button:hover{background:var(--green-dark)}.muted{color:var(--grey);font-size:12.5px}.empty{padding:40px 20px;color:var(--grey);text-align:center}
table{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--line);border-radius:14px;overflow:hidden;margin-bottom:18px}
td,th{padding:9px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;font-size:13px}th{background:var(--page);color:var(--grey);font-weight:600}
pre{white-space:pre-wrap;font:inherit;margin:4px 0 0;color:#374151}
@media (max-width:640px){.inbox{grid-template-columns:1fr}.list{border-right:none;max-height:220px}.stats{grid-template-columns:repeat(2,1fr)}}
</style>"""

STATUS = {
    "waiting": "Waiting for you",
    "replied": "You replied",
    "auto_answered": "Auto-answered",
    "not_sent": "Asked, not sent to you",
}


def local_only(handler):
    async def inner(request: Request):
        if request.headers.get("host", "").rsplit(":", 1)[0] not in LOCAL_HOSTS:
            return PlainTextResponse("The landlord page is only available on localhost.", status_code=403)
        return await handler(request)
    return inner


def ago(ts: str | None) -> str:
    if not ts:
        return ""
    s = (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).total_seconds()
    return "just now" if s < 60 else f"{int(s // 60)}m ago" if s < 3600 else f"{int(s // 3600)}h ago" if s < 86400 else f"{int(s // 86400)}d ago"


def page(title: str, body: str, landlord=None, tab: str = "") -> HTMLResponse:
    nav = ""
    if landlord is not None:
        lid = landlord["id"]
        nav = (f"<nav><a class='{'on' if tab == 'inbox' else ''}' href='/landlord/{lid}'>Inbox</a>"
               f"<a class='{'on' if tab == 'answers' else ''}' href='/landlord/{lid}/answers'>Saved answers</a>"
               f"<a class='{'on' if tab == 'outbox' else ''}' href='/outbox?l={lid}'>Outbox</a>"
               f"<a href='/landlord'>Switch landlord</a></nav>")
    who = f"<small> for landlords{' · ' + e(landlord['company']) if landlord is not None else ''}</small>"
    return HTMLResponse(f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
                        f"<title>{e(title)}</title>{STYLE}<header><span class=logo><span class=heart>♥</span>snugd{who}</span>"
                        f"{nav}</header><main>{body}<p class=muted style='margin-top:16px'>Demo data: every landlord, "
                        f"listing and renter here is synthetic.</p></main>")


async def form(request: Request) -> dict[str, str]:
    raw = (await request.body()).decode()
    return {k: v[0] for k, v in parse_qs(raw).items()}


def get_landlord(conn, lid):
    return conn.execute("SELECT * FROM landlords WHERE id = ?", (lid,)).fetchone()


@mcp.custom_route("/", methods=["GET"])
@local_only
async def home(request: Request):
    return RedirectResponse("/landlord")


@mcp.custom_route("/landlord", methods=["GET"])
@local_only
async def landlords(request: Request):
    with connect() as conn:
        rows = conn.execute(
            "SELECT d.*, SUM(q.status = 'waiting') AS waiting, COUNT(q.ref) AS asked FROM landlords d"
            " LEFT JOIN questions q ON q.landlord_id = d.id GROUP BY d.id ORDER BY d.id").fetchall()
    items = "".join(
        f"<tr><td><a href='/landlord/{r['id']}'><b>{e(r['company'])}</b></a></td><td>{e(r['name'])}</td>"
        f"<td>{r['waiting'] or 0}</td><td>{r['asked']}</td></tr>" for r in rows)
    return page("Landlords", "<h1>Pick a landlord</h1><table><tr><th>Company</th><th>Contact</th>"
                f"<th>Waiting</th><th>Questions</th></tr>{items}</table>")


@mcp.custom_route("/landlord/{lid}", methods=["GET"])
@local_only
async def inbox(request: Request):
    lid = request.path_params["lid"]
    with connect() as conn:
        landlord = get_landlord(conn, lid)
        if not landlord:
            return PlainTextResponse("No such landlord", status_code=404)
        qs = conn.execute(
            "SELECT q.*, s.question AS matched_q, s.answer AS matched_a, l.title AS listing_title FROM questions q"
            " JOIN listings l ON l.id = q.listing_id LEFT JOIN saved_answers s ON s.id = q.matched_answer_id"
            " WHERE q.landlord_id = ? ORDER BY q.status = 'waiting' DESC, q.asked_at DESC", (lid,)).fetchall()
        views = conn.execute("SELECT COUNT(*) FROM impressions i JOIN listings l ON l.id = i.listing_id"
                             " WHERE l.landlord_id = ?", (lid,)).fetchone()[0]
    count = lambda st: sum(q["status"] == st for q in qs)
    stats = (f"<div class=stats><div class=stat><b>{count('waiting')}</b><span>waiting for you</span></div>"
             f"<div class=stat><b>{count('auto_answered')}</b><span>auto-answered</span></div>"
             f"<div class=stat><b>{count('not_sent')}</b><span>asked, not sent</span></div>"
             f"<div class=stat><b>{views}</b><span>search views</span></div></div>")
    if not qs:
        body = f"{stats}<div class=inbox style='display:block'><div class=empty>No renter questions yet. They appear here as renters ask in Claude or ChatGPT.<br><br><a href='/landlord/{lid}'><b>Refresh</b></a></div></div>"
        return page(landlord["company"], body, landlord, "inbox")
    sel_ref = request.query_params.get("q") or qs[0]["ref"]
    sel = next((q for q in qs if q["ref"] == sel_ref), qs[0])
    items = "".join(
        f"<a class='item{' on' if q['ref'] == sel['ref'] else ''}' href='/landlord/{lid}?q={q['ref']}'>"
        f"<div class=t>{e(q['question'])}</div><div class=m><span class='dot {q['status']}'></span>"
        f"{STATUS[q['status']]}{' · ' + e(q['renter_name']) if q['renter_name'] else ''} · {q['listing_id']}"
        f" · {ago(q['sent_at'] or q['asked_at'])}</div></a>"
        for q in qs)
    return page(landlord["company"], stats + f"<div class=inbox><div class=list>{items}</div>"
                f"<div class=detail>{detail(lid, sel)}</div></div>"
                f"<p class=muted><a href='/landlord/{lid}?q={sel['ref']}'><b>Refresh</b></a> to see new questions.</p>",
                landlord, "inbox")


def detail(lid: str, q) -> str:
    head = (f"<span class='pill p-{q['status']}'>{STATUS[q['status']]}</span>"
            f"<div class=q>“{e(q['question'])}”</div>"
            f"<div class=who><span>Listing <b>{q['listing_id']} · {e(q['listing_title'])}</b></span>"
            + (f"<span>Renter <b>{e(q['renter_name'])}</b></span><span>Reply by <b>{e(q['channel'])}"
               f"{': ' + e(q['contact']) if q['contact'] else ''}</b></span>" if q["renter_name"] else "")
            + f"<span>Ref <b>{q['ref']}</b> · {ago(q['asked_at'])}</span></div>")
    if q["status"] == "waiting":
        body = (f"<form method=post action='/landlord/{lid}/reply/{q['ref']}'>"
                f"<textarea name=reply required placeholder='Type your reply…'></textarea>"
                f"<div class=bar><label><input type=checkbox name=save checked> Save as an answer for</label>"
                f"<select name=save_as style='width:auto'><option value=listing>this unit</option>"
                f"<option value=all>all my units</option></select><button>Send reply</button></div>"
                f"<p class=muted>Goes to the renter by {e(q['channel'])}, and shows in their chat. A saved answer is "
                f"given to the next renter instantly.</p></form>")
    elif q["status"] == "replied":
        body = f"<div class=box><div class=muted>Your reply</div>{e(q['reply'])}</div>"
    elif q["status"] == "auto_answered":
        body = (f"<div class=box><div class=muted>Answered instantly with your saved answer to “{e(q['matched_q'])}” "
                f"(match {q['match_score']})</div>{e(q['matched_a'])}</div>")
    else:
        body = (f"<div class=box>The renter asked this but chose not to send it to you. Add an answer and the next "
                f"renter who asks gets it instantly.</div><form method=post action='/landlord/{lid}/saved'>"
                f"<input type=hidden name=question value='{e(q['question'])}'><input type=hidden name=back value='{q['ref']}'>"
                f"<input type=text name=answer required placeholder='Add a saved answer…'>"
                f"<div class=bar><label>Applies to all your units</label><button>Save answer</button></div></form>")
    return head + body


@mcp.custom_route("/landlord/{lid}/answers", methods=["GET"])
@local_only
async def answers(request: Request):
    lid = request.path_params["lid"]
    with connect() as conn:
        landlord = get_landlord(conn, lid)
        if not landlord:
            return PlainTextResponse("No such landlord", status_code=404)
        saved = conn.execute("SELECT * FROM saved_answers WHERE landlord_id = ? ORDER BY id DESC", (lid,)).fetchall()
        units = conn.execute(
            "SELECT l.id, l.title, l.rent, (SELECT COUNT(*) FROM impressions i WHERE i.listing_id = l.id) AS shown,"
            " (SELECT COUNT(*) FROM questions q WHERE q.listing_id = l.id) AS asked"
            " FROM listings l WHERE l.landlord_id = ? ORDER BY l.id", (lid,)).fetchall()
    opts = "".join(f"<option value={u['id']}>{u['id']} only</option>" for u in units)
    rows = "".join(f"<tr><td><b>{e(s['question'])}</b><div class=muted>{s['listing_id'] or 'all units'} · "
                   f"{s['source'].replace('_', ' ')}</div></td><td>{e(s['answer'])}</td></tr>" for s in saved)
    unit_rows = "".join(f"<tr><td>{u['id']}</td><td>{e(u['title'])}</td><td>${u['rent']:,}</td><td>{u['shown']}</td>"
                        f"<td>{u['asked']}</td></tr>" for u in units)
    return page(landlord["company"], f"""<h1>Saved answers</h1>
<form method=post action='/landlord/{lid}/saved' class=box style='background:#fff'><div class=bar style='margin:0'>
<input type=text name=question required placeholder='A question renters ask' style='flex:1'>
<input type=text name=answer required placeholder='Your answer' style='flex:2'>
<select name=listing_id style='width:auto'><option value=''>all units</option>{opts}</select><button>Add</button></div></form>
<table><tr><th style='width:40%'>Question</th><th>Answer given to renters</th></tr>{rows}</table>
<h1>Your units</h1><table><tr><th>Id</th><th>Title</th><th>Rent</th><th>Search views</th><th>Questions</th></tr>{unit_rows}</table>""",
                landlord, "answers")


@mcp.custom_route("/landlord/{lid}/reply/{ref}", methods=["POST"])
@local_only
async def reply(request: Request):
    lid, ref = request.path_params["lid"], request.path_params["ref"]
    f = await form(request)
    save_as = f.get("save_as") if f.get("save") and f.get("save_as") in ("listing", "all") else None
    try:
        service.landlord_reply(lid, ref, f.get("reply", ""), save_as)
    except service.UserError as err:
        return PlainTextResponse(str(err), status_code=400)
    return RedirectResponse(f"/landlord/{lid}?q={ref}", status_code=303)


@mcp.custom_route("/landlord/{lid}/saved", methods=["POST"])
@local_only
async def add_saved(request: Request):
    lid = request.path_params["lid"]
    f = await form(request)
    try:
        service.add_saved_answer(lid, f.get("listing_id") or None, f.get("question", ""), f.get("answer", ""))
    except service.UserError as err:
        return PlainTextResponse(str(err), status_code=400)
    back = f.get("back")
    return RedirectResponse(f"/landlord/{lid}?q={back}" if back else f"/landlord/{lid}/answers", status_code=303)


@mcp.custom_route("/outbox", methods=["GET"])
@local_only
async def outbox(request: Request):
    lid = request.query_params.get("l")
    with connect() as conn:
        rows = conn.execute("SELECT * FROM outbox ORDER BY id DESC LIMIT 200").fetchall()
        landlord = get_landlord(conn, lid) if lid else None
    items = "".join(f"<tr><td>{ago(r['created_at'])}</td><td><b>{r['channel']}</b><div class=muted>{e(r['recipient'])}</div></td>"
                    f"<td><b>{e(r['subject'])}</b><pre>{e(r['body'])}</pre></td><td>{r['status']}"
                    f"{'<div class=muted>' + e(r['detail']) + '</div>' if r['detail'] else ''}</td></tr>" for r in rows)
    return page("Outbox", "<h1>Outbox</h1><p class=muted>Every message sent or simulated. <b>simulated</b> = written "
                "here instead of really sent (no email account set up, or an example.com address).</p>"
                f"<table><tr><th>When</th><th>To</th><th>Message</th><th>Status</th></tr>{items}</table>",
                landlord, "outbox")
