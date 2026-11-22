"""The rules, in one place. The MCP tools and the landlord page both call these."""

import os
import re

from . import matcher, notify, ranking
from .db import connect, listing_dict, new_ref, now

DASHBOARD_URL = os.environ.get("LEASE_DASHBOARD_URL", "http://127.0.0.1:8000")
RELATED_FLOOR = 0.25  # below the match cut-off but worth showing as "related"


class UserError(ValueError):
    """A problem the renter or the AI can fix (bad id, bad contact). Shown to the model."""


# ---------- renter side: Snugd's own feature ----------

def search(filters: dict, limit: int = 5) -> dict:
    with connect() as conn:
        listings = [listing_dict(r) for r in conn.execute("SELECT * FROM listings")]
        result = ranking.rank(listings, filters, limit)
        conn.executemany(
            "INSERT INTO impressions VALUES (?, ?)", [(m["id"], now()) for m in result["matches"]]
        )
    result["note"] = "Demo data: every listing is synthetic."
    return result


def get_listing(listing_id: str) -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT l.*, d.company AS landlord FROM listings l JOIN landlords d ON d.id = l.landlord_id"
            " WHERE l.id = ?", (listing_id.upper(),)
        ).fetchone()
    if not row:
        raise UserError(f"No listing with id {listing_id}. Use an id from search_apartments.")
    d = listing_dict(row)
    d.pop("lat"), d.pop("lon"), d.pop("landlord_id")
    return d


# ---------- renter side: the Within-style layer ----------

def ask_landlord(listing_id: str, question: str) -> dict:
    listing = get_listing(listing_id)
    with connect() as conn:
        lid = conn.execute("SELECT landlord_id FROM listings WHERE id = ?", (listing["id"],)).fetchone()[0]
        # Listing-specific answers first, so they win a tie against the landlord-wide ones.
        candidates = [dict(r) for r in conn.execute(
            "SELECT id, question, answer FROM saved_answers WHERE landlord_id = ?"
            " AND (listing_id IS NULL OR listing_id = ?) ORDER BY listing_id IS NULL",
            (lid, listing["id"]),
        )]
        idf = matcher.idf_weights([r[0] for r in conn.execute("SELECT question FROM saved_answers")])
        best = matcher.best_match(question, candidates, idf)
        ref = new_ref(conn)
        hit = best is not None and best.score >= matcher.MATCH_THRESHOLD
        conn.execute(
            "INSERT INTO questions (ref, listing_id, landlord_id, question, status, matched_answer_id,"
            " match_score, asked_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ref, listing["id"], lid, question, "auto_answered" if hit else "not_sent",
             best.answer_id if hit else None, best.score if best else None, now()),
        )
    if hit:
        return {
            "status": "answered",
            "answer": best.answer,
            "source": f"{listing['landlord']}'s saved answer to: \"{best.saved_question}\"",
            "match_score": best.score,
            "reference_code": ref,
            "next_step": "Give the answer word for word and say it is the landlord's own saved answer. "
                         "If it does not fully answer the renter, offer to send the question to the landlord.",
        }
    out = {
        "status": "not_answered",
        "reference_code": ref,
        "landlord": listing["landlord"],
        "next_step": "Tell the renter the landlord has not answered this yet. Do not guess. Ask if they want "
                     "it sent to the landlord, their name, and how to hear back: email, sms, snugd_app, "
                     "or chat_only (check back here). Only after they say yes, call send_question_to_landlord.",
    }
    if best and best.score >= RELATED_FLOOR:
        out["related_saved_answer"] = {"question": best.saved_question, "answer": best.answer,
                                       "caution": "Related, not the same question. Say so if you mention it."}
    return out


def send_to_landlord(ref: str, renter_name: str, channel: str, contact: str | None) -> dict:
    channel, contact = channel.strip().lower(), (contact or "").strip()
    _check_contact(channel, contact)
    with connect() as conn:
        q = _question(conn, ref)
        if q["status"] in ("waiting", "replied"):
            return {"status": q["status"], "reference_code": q["ref"], "note": "Already sent. Nothing sent twice."}
        landlord = conn.execute("SELECT * FROM landlords WHERE id = ?", (q["landlord_id"],)).fetchone()
        conn.execute(
            "UPDATE questions SET status = 'waiting', renter_name = ?, channel = ?, contact = ?, sent_at = ?"
            " WHERE ref = ?", (renter_name.strip(), channel, contact or None, now(), q["ref"]),
        )
        # How the question reaches the landlord: an email plus their queue on the landlord page.
        notify.send(conn, channel="email", recipient=landlord["email"], question_ref=q["ref"],
                    subject=f"New renter question about {q['listing_id']} ({q['ref']})",
                    body=f"{renter_name} asked about {q['listing_id']}:\n\n  {q['question']}\n\n"
                         f"Reply here: {DASHBOARD_URL}/landlord/{landlord['id']}\n")
        notify.send(conn, channel=channel, recipient=contact, question_ref=q["ref"],
                    subject=f"Your question was sent to {landlord['company']} ({q['ref']})",
                    body=f"Hi {renter_name}, we sent your question about {q['listing_id']} to "
                         f"{landlord['company']}. We'll message you here when they reply. Reference: {q['ref']}.")
    return {
        "status": "waiting",
        "reference_code": q["ref"],
        "landlord": landlord["company"],
        "how_reply_arrives": "in this chat via check_landlord_reply" if channel == "chat_only"
                             else f"by {channel} to {contact}, and in this chat via check_landlord_reply",
    }


def check_reply(ref: str) -> dict:
    with connect() as conn:
        q = _question(conn, ref)
    out = {"reference_code": q["ref"], "listing_id": q["listing_id"], "question": q["question"],
           "status": q["status"]}
    if q["status"] == "replied":
        out["landlord_reply"] = q["reply"]
        out["replied_at"] = q["replied_at"]
    elif q["status"] == "not_sent":
        out["note"] = "This question was never sent to the landlord. Use send_question_to_landlord."
    return out


def _check_contact(channel: str, contact: str) -> None:
    if channel not in notify.CHANNELS:
        raise UserError(f"channel must be one of {', '.join(notify.CHANNELS)}")
    if channel == "email" and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", contact):
        raise UserError("That does not look like an email address.")
    if channel == "sms" and len(re.sub(r"\D", "", contact)) < 10:
        raise UserError("A phone number needs at least 10 digits.")
    if channel == "snugd_app" and not contact:
        raise UserError("Give the renter's Snugd account email or username.")


def _question(conn, ref: str):
    q = conn.execute("SELECT * FROM questions WHERE ref = ?", (ref.strip().upper(),)).fetchone()
    if not q:
        raise UserError(f"No question with reference code {ref}.")
    return q


# ---------- landlord side ----------

def landlord_reply(landlord_id: str, ref: str, reply: str, save_as: str | None) -> str:
    """save_as: None, 'listing' (this unit only) or 'all' (all their units). Returns delivery status."""
    reply = reply.strip()
    if not reply:
        raise UserError("The reply is empty.")
    with connect() as conn:
        q = _question(conn, ref)
        if q["landlord_id"] != landlord_id or q["status"] != "waiting":
            raise UserError("That question is not waiting for this landlord.")
        landlord = conn.execute("SELECT * FROM landlords WHERE id = ?", (landlord_id,)).fetchone()
        conn.execute("UPDATE questions SET status = 'replied', reply = ?, replied_at = ? WHERE ref = ?",
                     (reply, now(), q["ref"]))
        if save_as in ("listing", "all"):
            _save_answer(conn, landlord_id, q["listing_id"] if save_as == "listing" else None,
                         q["question"], reply, "from_reply")
        return notify.send(conn, channel=q["channel"], recipient=q["contact"] or "", question_ref=q["ref"],
                           subject=f"{landlord['company']} replied about {q['listing_id']} ({q['ref']})",
                           body=f"Hi {q['renter_name']},\n\nYou asked: {q['question']}\n\n"
                                f"{landlord['company']} replied: {reply}\n")


def add_saved_answer(landlord_id: str, listing_id: str | None, question: str, answer: str) -> None:
    if not question.strip() or not answer.strip():
        raise UserError("Both the question and the answer are needed.")
    with connect() as conn:
        _save_answer(conn, landlord_id, listing_id or None, question.strip(), answer.strip(), "landlord")


def _save_answer(conn, landlord_id, listing_id, question, answer, source) -> None:
    conn.execute(
        "INSERT INTO saved_answers (landlord_id, listing_id, question, answer, source, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)", (landlord_id, listing_id, question, answer, source, now()),
    )
