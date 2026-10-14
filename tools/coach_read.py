"""Coach's read from the command line. The pipeline is app/coach.py; the
server runs it after each parse (app.worker). This is for running it by hand.

    python tools/coach_read.py evidence TEAM_ID > pack.json   # where the DB is
    python tools/coach_read.py scorer pack.json               # PC only: add the
                                                              # scorer's moments
    python tools/coach_read.py write pack.json > note.json    # draft, edit, review
    python tools/coach_read.py check pack.json note.json      # the checker
    python tools/coach_read.py show pack.json note.json       # print it readable

`/coach-read <team>` (.claude/skills/coach-read) runs all of it in one go.

The decision scorer is an input only here, on the PC where the collegiate
corpus is, as "experimental" facts (verdict null) allowed only in a "check"
point. It passed its first held-out calibration test on 2026-10-13 but fails
the shuffled sweep 8 of 20 and its single verdicts have not been checked by
a person yet (TODO.md), so the server does not use it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import coach  # noqa: E402

# Kept as names here: tests and older notes refer to them.
check = coach.check
MAX_POINTS = coach.MAX_POINTS
LIMITS = coach.LIMITS


def add_scorer(pack: dict, n: int = 3) -> int:
    """Append the scorer's costliest moments as experimental facts. Runs
    where the collegiate corpus is (the PC), using the pack's anchors to
    find the team's maps there. Returns how many were added."""
    sys.path.insert(0, str(ROOT / "tools"))
    import verdicts

    moments = verdicts.moments(pack.get("anchors", []), n=n,
                               demos=pack.get("demos"))
    for m in moments:
        pack["facts"].append({
            "id": f"F{len(pack['facts']) + 1}", "kind": "scorer",
            "scope": f"{m['map']} {m['side'].upper()}",
            "text": (f"Experimental scorer, not yet checked by a person: "
                     f"{m['map']} round {m['round']} as {m['side'].upper()}, "
                     f"{m['situation']}; win chance fell from {m['before']}% "
                     f"to {m['after']}%, where that situation usually costs "
                     f"{m['usual']} points."),
            "verdict": None, "rounds": [f"{m['map']} {m['round']}"]})
    return len(moments)


def write(pack: dict) -> dict:
    if not coach.api_key():
        raise SystemExit("ANTHROPIC_API_KEY is not set")
    pipe = coach.Pipeline(coach.make_client())
    note, problems = pipe.run(pack)
    return {"model": coach.MODEL, "cost_usd": round(pipe.cost, 4),
            "problems": problems, **note}


def show(pack: dict, note: dict) -> str:
    out = [f"COACH'S READ: {pack['team']}", "", note["summary"], ""]
    for p in note["points"]:
        tag = {"keep": "KEEP: ", "check": "WORTH CHECKING: "}.get(p["kind"], "")
        out.append(tag + p["headline"])
        out.append("  " + p["what_happens"])
        out.append("  Practice: " + p["practice"])
        if p["rounds_to_watch"]:
            out.append("  Watch: " + ", ".join(p["rounds_to_watch"]))
        out.append("")
    return "\n".join(out)


def main() -> int:
    cmd, *args = sys.argv[1:] or ["help"]
    if cmd == "evidence":
        from app import db
        db.init()
        pack = coach.evidence(int(args[0]))
        if pack is None:
            raise SystemExit(f"no team {args[0]} or no rounds with a known side")
        json.dump(pack, sys.stdout, indent=1)
    elif cmd == "scorer":
        path = Path(args[0])
        pack = json.loads(path.read_text(encoding="utf-8"))
        added = add_scorer(pack)
        path.write_text(json.dumps(pack, indent=1), encoding="utf-8")
        print(f"added {added} experimental scorer facts")
    elif cmd == "write":
        pack = json.loads(Path(args[0]).read_text(encoding="utf-8"))
        json.dump(write(pack), sys.stdout, indent=1)
    elif cmd in ("check", "show"):
        pack = json.loads(Path(args[0]).read_text(encoding="utf-8"))
        note = json.loads(Path(args[1]).read_text(encoding="utf-8"))
        if cmd == "show":
            print(show(pack, note))
        problems = check(pack, note)
        print("\n".join(problems) if problems else "CHECK PASSED")
        return 1 if problems else 0
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
