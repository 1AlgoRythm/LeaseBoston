"""Mutation check: break each safety guard on purpose and confirm a test fails.

A test suite that passes proves little until you know it can fail. For each guard
below, this script removes the guard from the source, runs the one test that
should notice, restores the file, and reports CAUGHT or MISSED.

Run from the repo root:  uv run python tests/mutation_check.py
"""

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# (file, exact guard text, replacement that disables it, pytest -k selector)
MUTATIONS = [
    ("leaseapp/matcher.py",
     "    if not (q & s) - GENERIC:  # no shared topic word\n        return 0.0\n", "",
     "allowed"),                                            # topic-word guard
    ("leaseapp/landlord_web.py",
     '        if request.headers.get("host", "").rsplit(":", 1)[0] not in LOCAL_HOSTS:', "        if False:",
     "localhost_only"),                                     # landlord page is localhost-only
    ("leaseapp/service.py",
     '        if q["status"] in ("waiting", "replied"):', "        if False:",
     "idempotent"),                                         # send is never repeated
    ("leaseapp/service.py",
     '        if save_as in ("listing", "all"):', "        if False:",
     "journey_over_stdio"),                                 # a reply becomes a saved answer
    ("leaseapp/service.py",
     '        if q["landlord_id"] != landlord_id or q["status"] != "waiting":', '        if q["status"] != "waiting":',
     "another_landlords"),                                  # a landlord answers only their own questions
]


def main() -> int:
    missed = 0
    for rel, guard, broken, selector in MUTATIONS:
        path = ROOT / rel
        original = path.read_text()
        if original.count(guard) != 1:
            print(f"{selector:22} GUARD NOT FOUND in {rel}")
            missed += 1
            continue
        path.write_text(original.replace(guard, broken, 1))
        try:
            r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-k", selector],
                               cwd=ROOT, capture_output=True, text=True)
        finally:
            path.write_text(original)        # always restore the real code
        caught = r.returncode != 0
        missed += not caught
        print(f"{selector:22} {'CAUGHT' if caught else 'MISSED'}  ({rel})")
    print(f"{len(MUTATIONS) - missed} of {len(MUTATIONS)} guards are protected by a failing test")
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
