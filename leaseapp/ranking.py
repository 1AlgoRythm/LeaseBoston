"""Rank listings for one renter.

Hard filters remove what cannot work (over budget, too few bedrooms, no pets,
not free by the move-in date, missing a must-have). The rest get a 0-100 score
from three parts, each 0..1, averaged with weights over the parts that apply:

  budget   (weight 0.4)  more room under the max rent is better, full marks at 25% under
  commute  (weight 0.4)  straight-line distance to the place they named; full at 0 km, zero at 5 km
  extras   (weight 0.2)  share of their nice-to-have amenities the listing has

Each part also writes a plain reason, so the AI can say WHY a place fits.
"""

import math

from .seed_data import LANDMARKS

WALK_M_PER_MIN = 80  # about 5 km/h


def km_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    (lat1, lon1), (lat2, lon2) = map(lambda p: (math.radians(p[0]), math.radians(p[1])), (a, b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


PET_OK = {"none": {"none", "cats", "cats_and_dogs"}, "cat": {"cats", "cats_and_dogs"}, "dog": {"cats_and_dogs"}}


def why_not(listing: dict, f: dict) -> list[str]:
    """Hard-filter failures, in words. Empty list = passes."""
    out = []
    if f.get("max_rent") and listing["rent"] > f["max_rent"]:
        out.append(f"${listing['rent'] - f['max_rent']} over budget")
    if listing["beds"] < f.get("min_beds", 0):
        out.append(f"only {listing['beds'] or 'studio'} bedroom(s)")
    if listing["pets"] not in PET_OK[f.get("pets", "none")]:
        out.append(f"no {f['pets']}s allowed")
    if f.get("move_in_by") and listing["available_from"] > f["move_in_by"]:
        out.append(f"not free until {listing['available_from']}")
    missing = [a for a in f.get("must_have") or [] if a not in listing["amenities"]]
    if missing:
        out.append("missing " + ", ".join(missing))
    if f.get("neighborhoods") and listing["neighborhood"].lower() not in {n.lower() for n in f["neighborhoods"]}:
        out.append(f"in {listing['neighborhood']}, not a chosen area")
    return out


def score(listing: dict, f: dict) -> tuple[int, list[str]]:
    parts, reasons = [], []
    if f.get("max_rent"):
        under = f["max_rent"] - listing["rent"]
        parts.append((0.4, min(1.0, under / (0.25 * f["max_rent"]))))
        reasons.append(f"${under} under your budget" if under else "exactly at your budget")
    if f.get("near"):
        km = km_between((listing["lat"], listing["lon"]), LANDMARKS[f["near"]])
        parts.append((0.4, max(0.0, 1 - km / 5)))
        reasons.append(f"{km:.1f} km from {f['near']} (about {round(km * 1000 / WALK_M_PER_MIN)} min walk, straight line)")
    if f.get("nice_to_have"):
        have = [a for a in f["nice_to_have"] if a in listing["amenities"]]
        parts.append((0.2, len(have) / len(f["nice_to_have"])))
        if have:
            reasons.append("has " + ", ".join(have))
    if not parts:
        return 50, ["matches your filters"]
    total = sum(w for w, _ in parts)
    return round(100 * sum(w * s for w, s in parts) / total), reasons


def rank(listings: list[dict], f: dict, limit: int) -> dict:
    fits, misses = [], []
    for l in listings:
        fails = why_not(l, f)
        if fails:
            misses.append((len(fails), l, fails))
        else:
            s, reasons = score(l, f)
            fits.append({**_card(l), "fit_score": s, "why_it_fits": reasons})
    fits.sort(key=lambda x: (-x["fit_score"], x["rent"]))
    result = {"matches": fits[:limit], "total_matching": len(fits)}
    if len(fits) < limit:  # say what nearly fit, so the renter can loosen a filter
        misses.sort(key=lambda m: (m[0], m[1]["rent"]))
        one_off = [(l, fails) for n, l, fails in misses if n == 1]  # fails exactly one filter
        result["near_misses"] = [{**_card(l), "why_not": fails} for l, fails in one_off[: limit - len(fits)]]
    return result


def _card(l: dict) -> dict:
    keep = ("id", "title", "neighborhood", "rent", "beds", "baths", "sqft", "available_from", "pets", "amenities")
    return {k: l[k] for k in keep}
