"""What cost a team a match, and the habits behind its season, for the pages.

    match_loss(match_key, team_id)  -> the causes that cost this match most,
                                       against a typical college team
    season_habits(team_id)          -> the proven mistakes this team makes
                                       more than college teams

Both read the scorer's model as trained on the PC (tools/ship_scorer.py,
counterplay/scorer_model.pkl) and the detectors in counterplay/decisions.py,
which use only what the team could have known. A match with no vision data
(positions parsed before version 2) gets None, never a guess.

The words are coaching, not statistics: a cause, about how many rounds it
cost, one thing to practice, and the rounds to watch.
"""
from __future__ import annotations

import json
import pickle
from collections import Counter
from pathlib import Path

from . import db, memo
from . import report as report_mod

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / "counterplay" / "scorer_model.pkl"
BASELINE = ROOT / "counterplay" / "whylost_baseline.json"

# A cause is shown for a match when it cost at least this many rounds more
# than a typical college team over the same rounds.
MIN_EXCESS = 0.5
MAX_CAUSES = 3

_loaded: dict = {}


def _model():
    if "model" not in _loaded:
        try:
            _loaded["model"] = pickle.loads(MODEL.read_bytes())
        except (OSError, pickle.UnpicklingError, AttributeError, ModuleNotFoundError):
            _loaded["model"] = None
    return _loaded["model"]


def _baseline():
    if "baseline" not in _loaded:
        try:
            _loaded["baseline"] = json.loads(BASELINE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _loaded["baseline"] = None
    return _loaded["baseline"]


def has_vision(match_key: str) -> bool:
    r = db.one("""SELECT hex(substr(data, 1, 1)) v FROM round_positions
                   WHERE match_key = ? LIMIT 1""", match_key)
    return bool(r and r["v"] == "02")


def _rounds_text(x: float) -> str:
    """About how many rounds, to the half: precision a coach can use."""
    half = round(x * 2) / 2
    if half <= 0.5:
        return "about half a round"
    if half == 1:
        return "about a round"
    n = f"{half:g}"
    return f"about {n} rounds"


def _clock(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d} in"


def _where(rn: int, seconds: float) -> str:
    """'round 9, 1:44 in', or just 'round 9' for something that happened at
    the start (a buy) rather than at a moment in it."""
    return f"round {rn}" if seconds <= 0 else f"round {rn}, {_clock(seconds)}"


@memo.by_team
def _match_loss(team_id: int, match_key: str):
    from app import corpus
    from counterplay import posfeat, whylost
    from counterplay import state as state_mod

    model, base = _model(), _baseline()
    if model is None or base is None or not has_vision(match_key):
        return None
    sides = {k: v for k, v in report_mod.our_sides(team_id).items() if k[0] == match_key}
    if not sides:
        return None
    rounds, events = corpus.load_frames(match_keys=[match_key])
    if not len(rounds):
        return None
    st = posfeat.attach(state_mod.build_states(rounds, events)).sort_values(
        ["round_num", "event_idx"])
    b = whylost.explain_match(st, model.predict(st), sides)
    n = Counter(sides.values())

    def merged(src):
        d = dict(src)
        d["duels"] = d.pop("our_kills", 0) + d.pop("lost_duel", 0)
        return d

    excess: dict = {}
    for side in ("ct", "t"):
        actual, expect = merged(b.by_side[side]), merged(base.get(side, {}))
        for c in set(actual) | set(expect):
            excess[c] = excess.get(c, 0.0) + actual.get(c, 0.0) - expect.get(c, 0.0) * n[side]
    causes = []
    for c, v in sorted(excess.items(), key=lambda cv: cv[1]):
        if v > -MIN_EXCESS or len(causes) >= MAX_CAUSES:
            break
        ex = b.examples.get("lost_duel" if c == "duels" else c, [])[:3]
        causes.append({
            "cause": c,
            "label": ("Losing the fights themselves" if c == "duels"
                      else whylost.LABEL.get(c, c)),
            "rounds": -v, "rounds_text": _rounds_text(-v),
            "practice": whylost.PRACTICE["lost_duel" if c == "duels" else c],
            "watch": [_where(e[1], e[2]) for e in ex]})
    return {"won": b.rounds_won, "lost": b.rounds_lost, "causes": causes}


def match_loss(match_key: str, team_id: int):
    """{"won", "lost", "causes": [...]} or None. Never raises: a page must
    render without it."""
    try:
        return _match_loss(team_id, match_key)
    except Exception:                                # noqa: BLE001
        return None


@memo.by_team
def _season_habits(team_id: int):
    from counterplay import decisions as D
    sides = report_mod.our_sides(team_id)
    if not sides:
        return None
    keys = sorted({k for k, _ in sides})
    if not any(has_vision(k) for k in keys):
        return None
    marks = ",".join("?" * len(keys))
    deaths = [(e["match_key"], e["round_num"], float(e["seconds"]), e["victim_side"])
              for e in db.query(f"""SELECT match_key, round_num, seconds, victim_side
                                      FROM events WHERE type = 'death'
                                       AND match_key IN ({marks})""", *keys)
              if sides.get((e["match_key"], e["round_num"])) == e["victim_side"]]
    res = D.season(deaths)
    maps = {r["match_key"]: (r["map_name"] or "").replace("de_", "")
            for r in db.query(f"SELECT match_key, map_name FROM matches WHERE match_key IN ({marks})",
                              *keys)}
    habits = []
    for code, r in res.items():
        if not r["habit"]:
            continue
        habits.append({
            "code": code, "sentence": D.DETECTORS[code]["habit"],
            "n": r["n"], "of": r["of"], "rate": r["rate"], "college": r["college"],
            "watch": [f"{maps.get(mk, '?')} round {rn}, {_clock(s)}"
                      for mk, rn, s in r["examples"][:3]]})
    return {"deaths": next(iter(res.values()))["of"] if res else 0, "habits": habits}


def season_habits(team_id: int):
    """{"deaths", "habits": [...]} or None. Never raises."""
    try:
        return _season_habits(team_id)
    except Exception:                                # noqa: BLE001
        return None
