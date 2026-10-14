"""The coach's read: a short note a coach can act on, at the top of Overview.

Why (Johan, 2026-10-13): the site showed coaches statistics and almost no
coaching. NC State Red's captain called it Leetify with a benchmark; UCF's
page had no "What to work on" at all. The only output that read like
coaching was Claude drafting a message to a coach, from numbers the site
already had. This does that for every team, with the guard rails the site's
one promise needs (no number it cannot back):

  CODE COMPUTES. evidence() packs every fact from report/advice/why/league,
  each with an id, a scope (all maps, or one map and side) and a verdict
  from league.judge (-1 worse than college teams, +1 better, 0 unclear).

  CLAUDE DRAFTS, EDITS AND REVIEWS. A draft picks at most three points; an
  editor call cuts it and removes claims the facts do not make; a reviewer
  call reads it as the team's captain would (meaning, scope, overload,
  voice) and says SHIP or FIX.

  THE CHECKER DECIDES. check() refuses a note whose numbers, rounds, kinds
  or word limits do not match its facts. A FIX or a failed check gets one
  rewrite with the problems listed; a second failure stores the note as
  failed and nothing is shown.

  A PERSON APPROVES, AT FIRST. A note that passes waits as pending until the
  master account approves it on /account (or edits and approves it). After
  AUTO_APPROVE_AFTER approvals in a row with no edits, notes publish
  themselves; one edit or rejection turns the queue back on.

Written by app.worker after a pass that parsed anything (refresh()), never
during a request. Without ANTHROPIC_API_KEY it does nothing and says so once.
What leaves the server is the team name and the fact sentences: no demo
file, no player names, no steamids (user_message() is the whole payload).

tools/coach_read.py is the command line around this, and adds the decision
scorer's moments on the PC, where the collegiate corpus is.
"""
from __future__ import annotations

import json
import os
import re
import sys

from . import db

MODEL = "claude-opus-5-5"
# Claude Opus 5.5 list prices, dollars per token, for the cost column.
PRICE_IN, PRICE_OUT = 4e-6, 20e-6
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
# Approvals in a row, none edited, before notes stop waiting for a person.
AUTO_APPROVE_AFTER = 20

# ---------------------------------------------------------------- evidence


def evidence(team_id: int) -> dict | None:
    """Every fact the note may use, each with an id, a scope, a sentence and
    the rounds behind it. None for a team with nothing parsed."""
    from . import advice, league, report, why

    team = db.one("SELECT id, name FROM teams WHERE id = ?", team_id)
    st = report.team_stats(team_id)
    if team is None or st is None or not st["you"]["rounds"]:
        return None
    you = st["you"]
    facts: list[dict] = []

    def fact(kind, scope, text, *, verdict=None, rounds=None):
        facts.append({"id": f"F{len(facts) + 1}", "kind": kind, "scope": scope,
                      "text": text, "verdict": verdict, "rounds": rounds or []})

    def pc(h, o):
        return round(100.0 * h / o) if o else 0

    fact("record", "all maps", f"Won {you['won']} of {you['rounds']} rounds "
         f"({pc(you['won'], you['rounds'])}%) across {st['matches']} maps.")
    # Each map's result. Without these the model wrote "you lost Anubis",
    # true and on the page, and the reviewer refused it as uncited: two of
    # the first four notes on the box failed on exactly that.
    for m in report.team_matches(team_id):
        if m["status"] == "parsed" and m["result"] in ("W", "L", "T"):
            word = {"W": "won", "L": "lost", "T": "tied"}[m["result"]]
            fact("result", m["map"], f"{m['map']}: you {word} the map "
                 f"{m['us']} to {m['them']}.")
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
    # The demos behind every fact, by file hash, so facts added elsewhere
    # (the scorer, on the PC) can be limited to the same games: a UCF note
    # once carried a scorer moment from a division map that was in the PC's
    # corpus but never uploaded to UCF's page.
    shas = [r["sha256"] for r in db.query(
        """SELECT DISTINCT d.sha256 FROM demos d JOIN matches m ON m.demo_id = d.id
            WHERE d.team_id = ?""", team_id)]
    return {"team": team["name"], "team_id": team_id, "anchors": anchors,
            "demos": shas,
            "reference": "NECC collegiate teams, "
                         f"{league.ref().get('matches', 0)} matches",
            "facts": facts}


# ---------------------------------------------------------------- prompts

VOICE = """Write like a coach talking to five players at the start of
practice: short, direct, plain words they would say themselves. Address the
team as "you" everywhere, never "we" or "our". No hedging
boilerplate ("it is worth noting", "this suggests"), no talk about
statistics, tests or samples (the point's label already says whether it is
proven), no "it is not X, it is Y" constructions, no lists of three for
rhythm, no praise padding. No dashes as punctuation. US spelling. Never
"he", "him" or "his" for a player: "they", "their", or name the role
("the entry", "the player who got the opener"). A league
team plays scheduled matches: no matchmaking words like "queue"."""

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
  One idea per point, at most two numbers and the college rate. The site
  shows every statistic already.
- practice: one concrete thing to do (a drill, a default, a call), with no
  numbers in it at all, aimed at what the facts show. Do not slip in a
  cause they do not show: a fact that counts lost Nuke CT rounds does not
  say rotations are the problem, so "review the lost rounds and fix where
  they break" is fine and "drill rotations" is not.
- Never call a habit "working" unless a fact shows the rounds are won: a
  high trade rate is a habit, and if the rounds after it are still lost,
  say the habit is good and the rounds are not.
- If the team lost a map, the note mentions it, even in one clause of the
  summary, when no fact makes it a fix or a check.
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
before a coach sees it. You get the draft, the facts it cites and sometimes
a list of problems a reviewer or checker found. Return the note, edited, in
the same format.

Fix, in this order:
1. Every listed problem.
2. Meaning. Remove any claim the cited facts do not make, including links
   between facts of different scope (a figure across all maps offered as the
   reason for one map). Never add a number or a fact.
3. Overload. Cut to one idea per point and the word limits. If a point is
   weak, drop it: two good points beat three.
4. Voice. Make it read like a coach wrote it, not a model.

{VOICE}

The same rules bind the edit:
{RULES}
"""

REVIEWER = f"""You review a coach's read for a collegiate Counter-Strike 2 team
before it is shown to the team. You get the note and the facts it cites. A
code checker has already proven every number appears in a cited fact. You
judge what it cannot:

1. Meaning: each sentence says only what its cited facts say. No cause, no
   "because", no comparison or ranking the facts do not state. The practice
   line must not assume a cause the facts do not show.
2. Scope: a fact scoped "all maps" is never the reason for something on one
   map or side.
3. Overload: one idea per point; no number that adds nothing; a weak point
   should go.
4. Voice: a coach talking to players, not a model. {VOICE}
5. Sense: read it as the team's captain. Would they know what to do at the
   next practice? Does it miss something they already know, like a map they
   lost?

Only real problems a coach would notice. Return verdict SHIP when there are
none, FIX otherwise, with one short line per problem saying what to change.
"""

NOTE_SCHEMA = {
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

REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "problems"],
    "properties": {
        "verdict": {"type": "string", "enum": ["SHIP", "FIX"]},
        "problems": {"type": "array", "items": {"type": "string"}},
    },
}


def user_message(pack: dict) -> str:
    """Everything sent for a draft: team name and fact sentences. No
    anchors, no demo hashes, no player names."""
    return ("Team: " + pack["team"] + "\nReference: " + pack["reference"]
            + "\n\nFacts (verdict: -1 clearly worse than college teams, +1 "
              "clearly better, 0 no clear difference, null not tested):\n"
            + json.dumps(pack["facts"], indent=1))


def _cited(pack: dict, note: dict) -> list[dict]:
    ids = {fid for p in note.get("points", []) for fid in p.get("facts", [])}
    return [f for f in pack["facts"] if f["id"] in ids]


def _note_only(note: dict) -> dict:
    return {"summary": note.get("summary", ""), "points": note.get("points", [])}


def edit_message(pack: dict, note: dict, problems: list[str] | None = None) -> str:
    out = ("Team: " + pack["team"] + "\n\nDraft:\n"
           + json.dumps(_note_only(note), indent=1)
           + "\n\nFacts it cites:\n" + json.dumps(_cited(pack, note), indent=1))
    if problems:
        out += "\n\nProblems to fix:\n" + "\n".join(f"- {p}" for p in problems)
    return out


def review_message(pack: dict, note: dict) -> str:
    return ("Team: " + pack["team"] + "\n\nNote:\n"
            + json.dumps(_note_only(note), indent=1)
            + "\n\nFacts it cites:\n" + json.dumps(_cited(pack, note), indent=1))


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
    if not note.get("points"):
        problems.append("no points")
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


# ---------------------------------------------------------------- Claude

def api_key() -> str:
    """ANTHROPIC_API_KEY from the environment (/etc/counterplay.env on the
    box). On Johan's PC, also the Windows user environment, for a process
    started before it was set. Read, never printed."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key and os.name == "nt":
        import subprocess
        key = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[Environment]::GetEnvironmentVariable('ANTHROPIC_API_KEY','User')"],
            capture_output=True, text=True).stdout.strip()
    return key


def make_client():
    import anthropic                       # requirements.txt
    return anthropic.Anthropic(api_key=api_key())


class Pipeline:
    """The Claude calls for one note, with token counts for the cost."""

    def __init__(self, client):
        self.client = client
        self.tokens_in = self.tokens_out = 0

    def call(self, system: str, content: str, schema: dict) -> dict:
        # A declined request is retried server-side on a fallback model, in
        # the same call, instead of the note simply failing.
        msg = self.client.beta.messages.create(
            model=MODEL, max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            output_config={"effort": "high",
                           "format": {"type": "json_schema", "schema": schema}},
            system=system, messages=[{"role": "user", "content": content}])
        self.tokens_in += getattr(msg.usage, "input_tokens", 0) or 0
        self.tokens_out += getattr(msg.usage, "output_tokens", 0) or 0
        if msg.stop_reason == "refusal":
            raise RuntimeError("refused")
        text = next(b.text for b in msg.content if b.type == "text")
        return json.loads(text)

    @property
    def cost(self) -> float:
        return self.tokens_in * PRICE_IN + self.tokens_out * PRICE_OUT

    def run(self, pack: dict) -> tuple[dict, list[str]]:
        """(note, problems): draft, edit, check and review; one rewrite with
        the problems listed when either refuses. Empty problems means it
        passed both."""
        draft = self.call(SYSTEM, user_message(pack), NOTE_SCHEMA)
        note = self.call(EDITOR, edit_message(pack, draft), NOTE_SCHEMA)
        problems = self._judge(pack, note)
        if problems:
            note = self.call(EDITOR, edit_message(pack, note, problems), NOTE_SCHEMA)
            problems = self._judge(pack, note)
        note["draft"] = _note_only(draft)
        return note, problems

    def _judge(self, pack: dict, note: dict) -> list[str]:
        problems = check(pack, note)
        if problems:                       # no review of a note that cannot ship
            return problems
        review = self.call(REVIEWER, review_message(pack, note), REVIEW_SCHEMA)
        if review.get("verdict") == "FIX":
            return [f"reviewer: {p}" for p in review.get("problems", [])] or \
                   ["reviewer: FIX with no reason given"]
        return []


# ---------------------------------------------------------------- storage

def _auto_approve() -> bool:
    """True once the last AUTO_APPROVE_AFTER decisions by a person were all
    approvals with no edit. One edit or rejection resets the count."""
    rows = db.query("""SELECT status, edited FROM coach_notes
                        WHERE decided_by IS NOT NULL
                          AND status IN ('approved', 'rejected')
                     ORDER BY decided_at DESC, id DESC LIMIT ?""",
                    AUTO_APPROVE_AFTER)
    return (len(rows) == AUTO_APPROVE_AFTER
            and all(r["status"] == "approved" and not r["edited"] for r in rows))


def generate(team_id: int, client=None) -> int | None:
    """Write, check and store one note for a team. Returns the row id, or
    None when the team has nothing to write from."""
    pack = evidence(team_id)
    if pack is None:
        return None
    pipe = Pipeline(client or make_client())
    try:
        note, problems = pipe.run(pack)
    except Exception as exc:               # an API error is a failed note
        note, problems = None, [f"error: {type(exc).__name__}: {exc}"[:300]]
    if problems:
        status, auto = "failed", 0
    elif _auto_approve():
        status, auto = "approved", 1
    else:
        status, auto = "pending", 0
    now = db.utcnow()
    return db.execute(
        """INSERT INTO coach_notes (team_id, created_at, status, note, pack,
                                    problems, cost_usd, auto, decided_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        team_id, now, status, json.dumps(note) if note else None,
        json.dumps(pack), json.dumps(problems) if problems else None,
        round(pipe.cost, 4), auto, now if auto else None)


_WARNED = False


def refresh(client=None) -> list[int]:
    """Notes for every team with a demo parsed since its last note (of any
    status, so a failing team is not retried every pass). Called by the
    worker; never raises."""
    global _WARNED
    if client is None and not api_key():
        if not _WARNED:
            print("coach's read: no ANTHROPIC_API_KEY, notes not written",
                  file=sys.stderr, flush=True)
            _WARNED = True
        return []
    made = []
    try:
        rows = db.query("""SELECT d.team_id, MAX(d.parsed_at) parsed
                             FROM demos d
                            WHERE d.team_id IS NOT NULL AND d.status = 'parsed'
                         GROUP BY d.team_id""")
        for r in rows:
            last = db.one("SELECT MAX(created_at) t FROM coach_notes WHERE team_id = ?",
                          r["team_id"])["t"]
            if last is None or (r["parsed"] or "") > last:
                nid = generate(r["team_id"], client)
                if nid:
                    made.append(nid)
    except Exception as exc:               # never take the worker down
        print(f"coach's read: {type(exc).__name__}: {exc}", file=sys.stderr,
              flush=True)
    return made


def latest(team_id: int) -> dict | None:
    """The approved note shown on a team's Overview, newest first."""
    row = db.one("""SELECT id, note, created_at FROM coach_notes
                     WHERE team_id = ? AND status = 'approved'
                  ORDER BY created_at DESC, id DESC LIMIT 1""", team_id)
    if row is None or not row["note"]:
        return None
    return {"id": row["id"], "created_at": row["created_at"], **json.loads(row["note"])}


def queue() -> list[dict]:
    """Notes waiting for the master account, newest first, with team names."""
    rows = db.query("""SELECT n.id, n.team_id, t.name team, n.created_at, n.note,
                              n.pack, n.cost_usd
                         FROM coach_notes n JOIN teams t ON t.id = n.team_id
                        WHERE n.status = 'pending'
                     ORDER BY n.created_at DESC, n.id DESC""")
    return [{**dict(r), "note": json.loads(r["note"]), "pack": json.loads(r["pack"])}
            for r in rows]


def decide(note_id: int, user_id: int, approve: bool,
           edited: dict | None = None) -> list[str]:
    """Approve (optionally with edits) or reject a pending note. Returns the
    checker's problems with an edit, in which case nothing is saved: an
    edit is held to the same rule as a note Claude wrote."""
    row = db.one("SELECT note, pack, status FROM coach_notes WHERE id = ?", note_id)
    if row is None or row["status"] != "pending":
        return ["not a pending note"]
    note = json.loads(row["note"])
    changed = 0
    if approve and edited is not None:
        merged = {**note, "summary": edited.get("summary", note["summary"])}
        merged["points"] = [{**p, **{k: v for k, v in e.items() if k in
                                     ("headline", "what_happens", "practice")}}
                            for p, e in zip(note["points"],
                                            edited.get("points", []))]
        problems = check(json.loads(row["pack"]), merged)
        if problems:
            return problems
        changed = int(_note_only(merged) != _note_only(note))
        note = merged
    db.execute("""UPDATE coach_notes SET status = ?, note = ?, edited = ?,
                         decided_by = ?, decided_at = ? WHERE id = ?""",
               "approved" if approve else "rejected", json.dumps(note), changed,
               user_id, db.utcnow(), note_id)
    db.audit(user_id, "coach_note_" + ("approve" if approve else "reject"),
             f"note={note_id} edited={changed}")
    return []
