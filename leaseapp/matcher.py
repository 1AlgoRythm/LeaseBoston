"""Decide whether a landlord already answered a renter's question.

Plain code, no model: the same question always gives the same result.

1. Turn each question into a set of key words (drop filler words, fold
   synonyms: "dog" and "cats" both become "pet").
2. Weight each word by how rare it is across all saved questions (IDF), so
   "parking" counts more than "rent", which appears everywhere.
3. Score = average of
     overlap  = shared weight / weight of all words in either question
     coverage = shared weight / weight of the renter's words
   Coverage rewards short questions ("can I park?") that a longer saved
   question fully covers.
4. No match unless the two share a topic word (not one of GENERIC).
5. At or above MATCH_THRESHOLD, return the landlord's saved answer word for word.
"""

import math
import re
from dataclasses import dataclass

MATCH_THRESHOLD = 0.5

# Words that say little about the topic. A match must share at least one word
# NOT in this set. Without it, "is parking included in rent?" matched the saved
# answer to "are utilities included in the rent?" on "include" and "rent", and
# "is that allowed?" matched "are pets allowed?".
GENERIC = {"include", "rent", "cost", "allow", "month", "schedule", "sign"}

STOPWORDS = set("""
a an the is are was be been do does did can could would will should i i'm im me my we us our you your
it its it's there this that these those what whats how much many any some for of to in on at by with
from about if or and as so just there's per please hi hello thanks get have has need also
available unit apartment apartments place listing here without when where which who why what's
""".split())

# Variants -> one canonical word. Keys are lower-case raw words.
SYNONYMS = {
    **dict.fromkeys(["park", "parking", "car", "cars", "garage", "driveway", "spot", "spots"], "parking"),
    **dict.fromkeys(["pet", "pets", "dog", "dogs", "cat", "cats", "animal", "animals"], "pet"),
    **dict.fromkeys(["utility", "utilities", "heat", "heating", "electric", "electricity", "water",
                     "gas", "internet", "wifi", "bills"], "utilities"),
    **dict.fromkeys(["deposit", "deposits", "security"], "deposit"),
    **dict.fromkeys(["sublet", "sublets", "sublease", "subletting", "subleasing"], "sublet"),
    **dict.fromkeys(["tour", "tours", "visit", "viewing", "showing", "view"], "tour"),
    **dict.fromkeys(["cosigner", "co-signer", "cosigners", "guarantor", "guarantors"], "guarantor"),
    **dict.fromkeys(["international", "visa", "f1", "f-1"], "international"),
    **dict.fromkeys(["students", "student"], "student"),
    **dict.fromkeys(["lease", "leases", "term", "contract"], "lease"),
    **dict.fromkeys(["short", "shorter"], "short"),
    **dict.fromkeys(["include", "included", "includes", "including"], "include"),
    **dict.fromkeys(["allow", "allowed", "permit", "permitted", "accept", "accepted",
                     "ok", "okay"], "allow"),
    **dict.fromkeys(["laundry", "washer", "dryer"], "laundry"),
    **dict.fromkeys(["fee", "fees", "cost", "costs", "price", "charge", "pay"], "cost"),
    **dict.fromkeys(["month", "months", "monthly"], "month"),
    **dict.fromkeys(["schedule", "book"], "schedule"),
}

LISTING_ID = re.compile(r"^[a-z]\d{3}$")


def keywords(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9][a-z0-9\-']*", text.lower())
    out = set()
    for w in words:
        if w in STOPWORDS or LISTING_ID.match(w):
            continue
        out.add(SYNONYMS.get(w, _stem(w)))
    return out


def _stem(w: str) -> str:
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


@dataclass
class Match:
    answer_id: int
    saved_question: str
    answer: str
    score: float


def idf_weights(all_saved_questions: list[str]) -> dict[str, float]:
    n = len(all_saved_questions)
    df: dict[str, int] = {}
    for q in all_saved_questions:
        for w in keywords(q):
            df[w] = df.get(w, 0) + 1
    return {w: math.log((n + 1) / (c + 1)) + 1 for w, c in df.items()}


def score(question: str, saved_question: str, idf: dict[str, float]) -> float:
    q, s = keywords(question), keywords(saved_question)
    if not q or not s:
        return 0.0
    if not (q & s) - GENERIC:  # no shared topic word
        return 0.0
    unseen = max(idf.values(), default=1.0)  # a word no saved question uses counts as rare
    w = lambda words: sum(idf.get(x, unseen) for x in words)
    shared = w(q & s)
    return 0.5 * (shared / w(q | s) + shared / w(q))


def best_match(question: str, candidates: list[dict], idf: dict[str, float]) -> Match | None:
    """candidates: dicts with id, question, answer. Returns the top one, whatever its score."""
    best = None
    for c in candidates:
        sc = score(question, c["question"], idf)
        if best is None or sc > best.score:
            best = Match(c["id"], c["question"], c["answer"], round(sc, 3))
    return best
