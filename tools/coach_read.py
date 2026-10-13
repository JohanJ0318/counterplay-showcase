"""Coach's read: a short note a coach can act on, written by Claude from facts
this codebase computed. PROTOTYPE, not served by the app.

    python tools/coach_read.py evidence TEAM_ID > pack.json   # where the DB is
    python tools/coach_read.py scorer pack.json               # PC only: add the
                                                              # scorer's moments
    python tools/coach_read.py write pack.json > note.json    # draft, then edit
    python tools/coach_read.py check pack.json note.json      # the checker
    python tools/coach_read.py show pack.json note.json       # print it readable

`/coach-read <team>` (.claude/skills/coach-read) runs all of it in one go.

Why (Johan, 2026-10-13): looking for a "why" on the site gives either
nothing or the longest list of statistics, and the only time the output
reads like coaching is when Claude drafts a message to a coach. Those drafts
use no number the site cannot count. What they add is choosing the one or
two things that matter and saying them as practice. So:

  CODE COMPUTES. Every number comes from report/advice/why/league, packed
  into one evidence file, each fact with an id and a SCOPE (all maps, or one
  map and side), so a figure about every map cannot be passed off as the
  reason for one map.

  CLAUDE DRAFTS, THEN EDITS. The draft picks at most three points; a second
  call reads the draft against its facts as an editor: cuts it down, removes
  claims the facts do not make (or that mix scopes), and rewrites it to read
  like a coach talking to players rather than like a model.

  THE CHECKER DECIDES WHETHER IT SHOWS. Every number in a point must appear
  in the facts it cites, every round to watch must be theirs, each point's
  kind must match its facts, and each field has a word limit. A note that
  fails is not shown.

The decision scorer is an input only as "experimental" facts (verdict null),
allowed only in a "check" point. It passed its first held-out calibration
test on 2026-10-13 but fails the shuffled sweep 8 of 20 and its single
verdicts have not been checked by a human yet (TODO.md).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MODEL = "claude-opus-5-5"
MAX_POINTS = 3
# fix: clearly worse than college teams; keep: clearly better; check: a lead
# that did not pass the test, labelled as one (UCF lost Anubis, and a note
# that said nothing about it failed the first thing a coach would ask).
KINDS = ("fix", "keep", "check")
# Word limits, enforced. Johan on the first live notes: too much information.
LIMITS = {"summary": 25, "headline": 8, "what_happens": 35, "practice": 35}
# Ranking words a note may not use on its own authority: the first live note
# called Nuke CT "the weakest half you play" when Inferno CT was lower.
RANKING = re.compile(r"\b(weakest|strongest|worst|best|biggest|smallest|"
                     r"highest|lowest)\b", re.I)
EM_DASH = chr(8212)

# ---------------------------------------------------------------- evidence


def evidence(team_id: int) -> dict:
    """Every fact the note may use, each with an id, a scope, a sentence and
    the rounds behind it. Built from the same functions the pages use."""
    from app import advice, db, league, report, why

    db.init()
    team = db.one("SELECT id, name FROM teams WHERE id = ?", team_id)
    st = report.team_stats(team_id)
    if team is None or st is None:
        raise SystemExit(f"no team {team_id} or no parsed matches")
    you = st["you"]
    facts: list[dict] = []

    def fact(kind, scope, text, *, verdict=None, rounds=None):
        facts.append({"id": f"F{len(facts) + 1}", "kind": kind, "scope": scope,
                      "text": text, "verdict": verdict, "rounds": rounds or []})

    def pc(h, o):
        return round(100.0 * h / o) if o else 0

    fact("record", "all maps", f"Won {you['won']} of {you['rounds']} rounds "
         f"({pc(you['won'], you['rounds'])}%) across {st['matches']} maps.")
    for side in ("ct", "t"):
        s = you[side]
        if s["rounds"]:
            fact("record", f"all maps, {side.upper()}", f"{side.upper()} side: "
                 f"won {s['won']} of {s['rounds']} rounds "
                 f"({pc(s['won'], s['rounds'])}%).")
    for mp, m in sorted(st["maps"].items()):
        name = mp.replace("de_", "")
        for side, key in (("ct", "you_ct"), ("t", "you_t")):
            n, w = m.get(key, 0), m.get(key + "_won", 0)
            if not n:
                continue
            ref = league.side_on_map(side, mp)
            v = league.judge(w, n, ref) if ref else 0
            fact("map_side", f"{name} {side.upper()}",
                 f"{name} {side.upper()}: won {w} of {n} rounds "
                 f"({pc(w, n)}%)" + (f"; college teams win {ref[0]:.0f}% "
                                     f"on {name} {side.upper()}" if ref else "")
                 + ".", verdict=v)

    for p in report.recurring_patterns(team_id):
        ref = p.get("ref")
        scope = "all maps" + (f", {p['side'].upper()}" if p.get("side") else "")
        fact("pattern", scope, f"{p['name']}: {p['hit']} of {p['of']} "
             f"({p['pct']:.0f}%)" + (f"; college teams {ref[0]:.0f}%"
                                     if ref else "") + ".",
             verdict=p.get("verdict"))

    for role, e in why.for_team(team_id).items():
        if not e:
            continue
        head = ("after losing the opening duel" if role == "lost"
                else "after winning the opening duel")
        culprit = e["culprits"][0] if e["culprits"] else None
        for i, l in enumerate(e["links"]):
            rounds = ([f"{mp} {rn}" for mp, rn, _ in e["rounds"]]
                      if i == culprit else [])
            fact("chain", "all maps", f"{head}, {l['label'].lower()}: "
                 f"{l['hit']} of {l['of']} ({l['pct']:.0f}%); college teams "
                 f"{l['college']:.0f}%.", verdict=l["verdict"], rounds=rounds)

    for it in advice.monday(team_id)["items"]:
        scope = " ".join(x for x in (it.get("map"), (it.get("side") or "").upper(),
                                     it.get("zone")) if x) or "all maps"
        fact("finding", scope, f"{it['do']}: {'; '.join(it['evidence'])}.",
             verdict=1 if it["good"] else -1)

    anchors = list(report.team_anchors(team_id).get("anchors", {}))
    return {"team": team["name"], "team_id": team_id, "anchors": anchors,
            "reference": "NECC collegiate teams, "
                         f"{league.ref().get('matches', 0)} matches",
            "facts": facts}


def add_scorer(pack: dict, n: int = 3) -> int:
    """Append the scorer's costliest moments as experimental facts. Runs
    where the collegiate corpus is (the PC), using the pack's anchors to
    find the team's maps there. Returns how many were added."""
    sys.path.insert(0, str(ROOT / "tools"))
    import verdicts

    moments = verdicts.moments(pack.get("anchors", []), n=n)
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


# ---------------------------------------------------------------- prompts

VOICE = """Write like a coach talking to five players at the start of
practice: short, direct, plain words they would say themselves. Address the
team as "you" everywhere, never "we" or "our". No hedging
boilerplate ("it is worth noting", "this suggests"), no talk about
statistics, tests or samples (the point's label already says whether it is
proven), no "it is not X, it is Y" constructions, no lists of three for
rhythm, no praise padding. No dashes as punctuation. US spelling."""

RULES = f"""- Use ONLY the facts provided. Every number you write must appear in a fact
  you cite for that point, written the same way. Never compute a new number.
- Each fact has a SCOPE (all maps, or one map and side). Never use a fact as
  the reason for something in a narrower scope: a trade rate across all maps
  does not explain Nuke CT. Say "across all your maps" if you use it at all.
- Every point has a kind:
  "fix": rests on a fact with verdict -1 (clearly worse than college teams).
  "keep": rests on a fact with verdict +1 (clearly better). At most one.
  "check": at most one, for the gap that matters most to the team among
  facts that did not pass the test (verdict 0) or come from the experimental
  scorer, for example the side of a map they lost. It names the rounds it
  rests on ("4 of 11 rounds") so the coach can weigh it.
- Experimental scorer facts may appear only in a "check" point.
- Make no comparison or ranking the facts do not state: no "weakest",
  "best", "worst" or "biggest" unless a cited fact says so.
- At most {MAX_POINTS} points, most rounds at stake first. Fewer is better.
- Word limits: summary {LIMITS['summary']}, headline {LIMITS['headline']},
  what_happens {LIMITS['what_happens']}, practice {LIMITS['practice']}.
  One idea per point. The site shows every statistic already.
- what_happens: the one or two numbers that matter and the college rate.
  practice: one concrete thing to do (a drill, a default, a call), with no
  numbers in it at all.
- Comparisons are with other college teams, never with professionals."""

SYSTEM = f"""You write the coach's read for a collegiate Counter-Strike 2 team:
a short note their captain or coach reads before practice. The site already
shows every statistic; your job is the part it cannot do. Choose what matters
and say it as coaching.

{VOICE}

Rules:
{RULES}
"""

EDITOR = f"""You edit a coach's read for a collegiate Counter-Strike 2 team
before a coach sees it. You get the draft and the facts it cites. Return the
note, edited, in the same format.

Fix, in this order:
1. Meaning. Remove any claim the cited facts do not make, including links
   between facts of different scope (a figure across all maps offered as the
   reason for one map). Never add a number or a fact.
2. Overload. Cut to one idea per point and the word limits. If a point is
   weak, drop it: two good points beat three.
3. Voice. Make it read like a coach wrote it, not a model.

{VOICE}

The same rules bind the edit:
{RULES}
"""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "points"],
    "properties": {
        "summary": {"type": "string",
                    "description": "One sentence, no numbers: the main thing."},
        "points": {
            # No maxItems: structured outputs reject it. The prompt asks for
            # at most MAX_POINTS and check() refuses a note with more.
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["headline", "what_happens", "practice",
                             "rounds_to_watch", "facts", "kind"],
                "properties": {
                    "headline": {"type": "string"},
                    "what_happens": {"type": "string"},
                    "practice": {"type": "string"},
                    "rounds_to_watch": {"type": "array", "items": {"type": "string"}},
                    "facts": {"type": "array", "items": {"type": "string"}},
                    "kind": {"type": "string", "enum": list(KINDS)},
                },
            },
        },
    },
}


def user_message(pack: dict) -> str:
    return ("Team: " + pack["team"] + "\nReference: " + pack["reference"]
            + "\n\nFacts (verdict: -1 clearly worse than college teams, +1 "
              "clearly better, 0 no clear difference, null not tested):\n"
            + json.dumps(pack["facts"], indent=1))


def edit_message(pack: dict, note: dict) -> str:
    ids = {fid for p in note["points"] for fid in p["facts"]}
    cited = [f for f in pack["facts"] if f["id"] in ids]
    draft = {"summary": note["summary"], "points": note["points"]}
    return ("Team: " + pack["team"] + "\n\nDraft:\n" + json.dumps(draft, indent=1)
            + "\n\nFacts it cites:\n" + json.dumps(cited, indent=1))


def _api_key() -> str:
    """ANTHROPIC_API_KEY from this process, or from the Windows user
    environment when it was set after this process started (a running app
    does not see new variables). Read, never printed."""
    import os
    import subprocess
    return os.environ.get("ANTHROPIC_API_KEY") or subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "[Environment]::GetEnvironmentVariable('ANTHROPIC_API_KEY','User')"],
        capture_output=True, text=True).stdout.strip()


def _call(client, system: str, content: str) -> tuple[dict, dict]:
    # A declined request is retried server-side on a fallback model, in the
    # same call, instead of the note simply failing.
    msg = client.beta.messages.create(
        model=MODEL, max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        output_config={"effort": "high",
                       "format": {"type": "json_schema", "schema": SCHEMA}},
        system=system, messages=[{"role": "user", "content": content}])
    if msg.stop_reason == "refusal":
        raise SystemExit("refused")
    text = next(b.text for b in msg.content if b.type == "text")
    return json.loads(text), msg.usage.to_dict()


def write(pack: dict, edit: bool = True) -> dict:
    import anthropic                         # pip install anthropic

    key = _api_key()
    if not key:
        raise SystemExit("ANTHROPIC_API_KEY is not set")
    client = anthropic.Anthropic(api_key=key)
    draft, u1 = _call(client, SYSTEM, user_message(pack))
    if not edit:
        return {"model": MODEL, "usage": [u1], **draft}
    final, u2 = _call(client, EDITOR, edit_message(pack, draft))
    return {"model": MODEL, "usage": [u1, u2], "draft": draft, **final}


# ---------------------------------------------------------------- checker

# A number on its own. Digits inside a word (dust2, cs2) are names, not
# statistics, and the first live note failed on "dust2".
NUM = re.compile(r"(?<![A-Za-z])\d+(?:\.\d+)?")


def _words(text: str) -> int:
    return len(text.split())


def check(pack: dict, note: dict) -> list[str]:
    """Every problem with the note; empty means it may be shown."""
    facts = {f["id"]: f for f in pack["facts"]}
    problems = []
    if len(note.get("points", [])) > MAX_POINTS:
        problems.append(f"more than {MAX_POINTS} points")
    if NUM.search(note.get("summary", "")):
        problems.append("the summary carries a number")
    if _words(note.get("summary", "")) > LIMITS["summary"]:
        problems.append("the summary is too long")
    for i, p in enumerate(note.get("points", []), 1):
        cited = [facts.get(fid) for fid in p.get("facts", [])]
        if not cited or None in cited:
            problems.append(f"point {i}: cites no fact or an unknown id")
            continue
        allowed, rounds = set(), set()
        for f in cited:
            allowed |= set(NUM.findall(f["text"]))
            rounds |= set(f["rounds"])
        for field in ("headline", "what_happens", "practice"):
            text = p.get(field, "")
            if _words(text) > LIMITS[field]:
                problems.append(f"point {i} {field}: over {LIMITS[field]} words")
            # 4v5, 5v4 and the like are game states, not statistics.
            nums = NUM.findall(re.sub(r"\b\d+v\d+\b", "", text))
            if field == "practice" and nums:
                problems.append(f"point {i} practice: carries a number")
            for n in nums:
                if n not in allowed:
                    problems.append(f"point {i} {field}: {n} is in none of "
                                    f"its facts")
            if EM_DASH in text:
                problems.append(f"point {i} {field}: em dash")
        for r in p.get("rounds_to_watch", []):
            if r not in rounds:
                problems.append(f"point {i}: round '{r}' is not in its facts")
        verdicts = [f["verdict"] or 0 for f in cited]
        kind = p.get("kind")
        if kind not in KINDS:
            problems.append(f"point {i}: kind {kind!r}")
        elif kind == "fix" and -1 not in verdicts:
            problems.append(f"point {i}: a fix with no -1 fact behind it")
        elif kind == "keep" and 1 not in verdicts:
            problems.append(f"point {i}: a keep with no +1 fact behind it")
        elif kind == "check":
            # A lead must say what it rests on: the round count of a cited
            # fact has to be in the text, so the coach can weigh it.
            dens = {m for f in cited for m in re.findall(r"of (\d+)", f["text"])}
            if dens and not any(re.search(rf"\b{d}\b", p.get("what_happens", ""))
                                for d in dens):
                problems.append(f"point {i}: a check that does not say how "
                                f"many rounds it rests on")
        if kind != "check" and any(f.get("kind") == "scorer" for f in cited):
            problems.append(f"point {i}: experimental scorer facts outside a check")
        for field in ("headline", "what_happens"):
            for w in RANKING.findall(p.get(field, "")):
                if not any(re.search(rf"\b{w}\b", f["text"], re.I)
                           for f in cited):
                    problems.append(f"point {i} {field}: '{w}' ranks "
                                    f"something no cited fact ranks")
    kinds = [p.get("kind") for p in note.get("points", [])]
    for k in ("keep", "check"):
        if kinds.count(k) > 1:
            problems.append(f"more than one {k}")
    return problems


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
        json.dump(evidence(int(args[0])), sys.stdout, indent=1)
    elif cmd == "scorer":
        path = Path(args[0])
        pack = json.loads(path.read_text(encoding="utf-8"))
        added = add_scorer(pack)
        path.write_text(json.dumps(pack, indent=1), encoding="utf-8")
        print(f"added {added} experimental scorer facts")
    elif cmd == "write":
        pack = json.loads(Path(args[0]).read_text(encoding="utf-8"))
        json.dump(write(pack, edit="--no-edit" not in args), sys.stdout, indent=1)
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
