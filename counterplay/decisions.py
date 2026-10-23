"""What could have been done differently, in plain words, for a death and a season.

The scorer (counterplay/rank.py, tools/verdicts.py) finds the moments that
cost a team most. This says what the team controlled and did badly, using
ONLY what the team could have known (counterplay/vision.py): its own
players, and enemies as far as the game had shown them.

Every detector is a rule written from how the game is coached, not something
a model invented, so a coach can be told it and check it in the demo. The
data sets the thresholds and decides which rules may speak:

  1. PROOF through what the mistake directly causes (DETECTORS[code]
     ["proof"]), measured over college deaths by tools/decision_evidence.py:
       trade    the death was traded less often (spacing)
       duel     the player with the worse crosshair lost the duel
       round    from the same win chance, the round was lost more often
                (decisions made before a fight: saves, retakes, setups)
       death    the detector describes how the player died; the death is
                the cost, nothing more to prove (awareness, utility)
  2. HABIT: a team hears it only when it happens on more of its deaths than
     college teams', by HABIT_POINTS and a binomial test (season()).

Then the season page says the habit once, in habit words, and every match
report shows where it happened, in single-moment words.

Detectors, by what a coach would call them:

  spacing    no_trade, entry_alone, repeek
  awareness  from_behind, from_side, through_smoke, wallbang, known_angle,
             outnumbered (CT only: Ts executing into known CTs is the plan)
  aim        crosshair
  utility    utility_unused, fought_blind, no_site_utility,
             no_site_utility_retake
  teamplay   staggered_retake, stacked
  economy    missed_save

Split on 2026-10-16 from one "killed by someone nobody had spotted": two
thirds of those were kills the instant the enemy appeared (a duel, so aim),
and the rest were through smoke, from the side or behind, or wallbangs,
each a different coaching point.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app import db

from . import positions as P
from . import vision as V

HERE = Path(__file__).resolve().parent
EVIDENCE = HERE / "decision_evidence.json"
STANDARDS = HERE / "utility_standards.json"
SITES = HERE / "site_centres.json"

# Distances in world units, times in seconds.
TRADE_FAR = 900.0       # college deaths past this are traded 12% of the time
                        # or less, against 41% inside 300 (decision_evidence)
FIGHT_RADIUS = 1200.0
KNOWN_RECENT = 4.0      # an enemy seen this recently is "known"
KNOWN_MIN_AHEAD = 1.0   # the team must have known at least this much earlier
CROSSHAIR_OFF = 25.0    # degrees from his head, with him in front of you
FRONT = 60.0            # within this many degrees he is in front of you
BEHIND = 110.0          # beyond this he is behind you
REPEEK_SECONDS = 4.0
REPEEK_RADIUS = 350.0
UTIL_WINDOW = 15.0
EXEC_WINDOW = 30.0
STAGGER = 4.0           # seconds between the first and last CT onto the site
SAVE_DOWN = 3           # outnumbered by this many or more
HOLD_REACH = 900.0      # a CT this far past a site's edge still holds it
GRENADES = {"Flashbang", "Smoke Grenade", "High Explosive Grenade",
            "Incendiary Grenade", "Molotov"}
RIFLES = {"AK-47", "M4A1-S", "M4A4", "AWP", "AUG", "SG 553", "FAMAS", "Galil AR"}

# A season speaks of a habit only past both: this many points more of its
# deaths than college teams', and at least half as much again as their rate.
HABIT_POINTS = 4.0
HABIT_RATIO = 1.5
HABIT_P = 0.20
HABIT_MIN = 4

DETECTORS = {
    "no_trade": dict(
        area="spacing", proof="trade",
        once="No one was close enough to trade you.",
        habit="You keep dying with no one close enough to trade you."),
    "entry_alone": dict(
        area="spacing", proof="trade",
        once="You went onto the site first with no one right behind you.",
        habit="Your first player onto a site keeps going in alone."),
    "repeek": dict(
        area="spacing", proof="round",
        once="You re-peeked the same angle right after getting a kill there.",
        habit="After a kill you keep re-peeking the same angle instead of moving."),
    "from_behind": dict(
        area="awareness", proof="death",
        once="You were shot from behind.",
        habit="You keep getting shot from behind."),
    "from_side": dict(
        area="awareness", proof="death",
        once="You were shot from the side, from an angle no one was watching.",
        habit="You keep dying to angles beside you that no one is covering."),
    "through_smoke": dict(
        area="awareness", proof="death",
        once="You were killed through a smoke.",
        habit="You keep dying through smokes."),
    "wallbang": dict(
        area="awareness", proof="death",
        once="You were killed through a wall.",
        habit="You keep standing where you can be shot through the wall."),
    "known_angle": dict(
        area="awareness", proof="death",
        once="Your team had seen him near there seconds earlier, and that "
             "angle wasn't checked.",
        habit="Your team spots enemies and then someone walks into them anyway."),
    "outnumbered": dict(
        area="awareness", proof="round",
        once="You took the fight where your team had already seen more of "
             "them than you had there.",
        habit="On CT you keep taking fights you can see you're outnumbered in."),
    "crosshair": dict(
        area="aim", proof="duel",
        once="He was in front of you, but your crosshair wasn't on him.",
        habit="When enemies appear in front of you, your crosshair often "
              "isn't on them."),
    "utility_unused": dict(
        area="utility", proof="death",
        once="You died with utility still in hand.",
        habit="You keep dying with grenades you never threw."),
    "fought_blind": dict(
        area="utility", proof="death",
        once="You fought while blinded.",
        habit="You keep taking fights while flashed."),
    "no_site_utility": dict(
        area="utility", proof="round",
        once="You went in without any of the usual smokes or flashes for "
             "that site.",
        habit="Your executes go in without the site's usual utility."),
    "no_site_utility_retake": dict(
        area="utility", proof="round",
        once="You retook without any of the usual utility for that site.",
        habit="Your retakes go in without the site's usual utility."),
    "staggered_retake": dict(
        area="teamplay", proof="round",
        once="You retook one at a time instead of together.",
        habit="Your retakes arrive one player at a time."),
    "stacked": dict(
        area="teamplay", proof="round",
        once="The bomb went down where no one was; three or more of you "
             "were at the other site.",
        habit="Your CT setups leave a site empty, and the bomb goes there."),
    "missed_save": dict(
        area="economy", proof="economy",
        once="The round was gone; that rifle was worth saving.",
        habit="You keep fighting lost rounds instead of saving your rifles."),
}
# Kept for older callers: the single-moment sentence per code.
SENTENCES = {code: d["once"] for code, d in DETECTORS.items()}


@dataclass
class Finding:
    code: str
    sentence: str
    detail: dict = field(default_factory=dict)
    checked: bool = False       # passed its proof on college deaths


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


_cache: dict = {}


def evidence() -> dict:
    if "evidence" not in _cache:
        _cache["evidence"] = _load(EVIDENCE)
    return _cache["evidence"]


def standards() -> dict:
    if "standards" not in _cache:
        _cache["standards"] = _load(STANDARDS)
    return _cache["standards"]


def sites() -> dict:
    """map -> "1"/"2" -> centre and radius (tools/site_centres.py)."""
    if "sites" not in _cache:
        _cache["sites"] = _load(SITES)
    return _cache["sites"]


# ----------------------------------------------------------------- one round

class RoundFacts:
    """Everything about a round that more than one death needs: positions,
    kills in order, the plant, grenades. Built once per round."""

    def __init__(self, match_key: str, round_num: int):
        self.mk, self.rn = match_key, round_num
        b = db.one("SELECT data FROM round_positions WHERE match_key = ? AND round_num = ?",
                   match_key, round_num)
        self.rnd = V.Round(b["data"]) if b else None
        self.kills = [dict(r) for r in db.query(
            """SELECT seconds, victim_side, victim_steamid, attacker_steamid,
                      thrusmoke, penetrated, distance
                 FROM events WHERE type = 'death' AND match_key = ? AND round_num = ?
             ORDER BY seconds""", match_key, round_num)]
        pl = db.one("""SELECT e.seconds, r.plant_site FROM events e
                        JOIN rounds r ON r.match_key = e.match_key AND r.round_num = e.round_num
                       WHERE e.type = 'plant' AND e.match_key = ? AND e.round_num = ?""",
                    match_key, round_num)
        self.plant_t = float(pl["seconds"]) if pl else None
        self.plant_site = int(pl["plant_site"]) if pl and pl["plant_site"] else None
        m = db.one("SELECT map_name FROM matches WHERE match_key = ?", match_key)
        self.map_name = m["map_name"] if m else None
        self.loadout = {str(r["steamid"]): r["loadout"] or "" for r in db.query(
            "SELECT steamid, loadout FROM player_rounds WHERE match_key = ? AND round_num = ?",
            match_key, round_num)}
        self._retake = None
        self._stacked = None

    def alive_before(self, side: str, t: float) -> int:
        return 5 - sum(1 for k in self.kills
                       if k["victim_side"] == side and float(k["seconds"]) < t)

    def zone(self, i: int, s: int) -> int:
        return int((self.rnd.samples["flags"][s, i] & P.ZONE_MASK) >> P.ZONE_SHIFT)

    def retake_spread(self) -> float | None:
        """Seconds between the first and last living CT reaching the planted
        site, or None if fewer than two got there or there was no plant."""
        if self._retake is None:
            self._retake = (None,)
            if self.rnd and self.plant_t is not None and self.plant_site:
                s0 = self.rnd.at(self.plant_t)
                arrive = []
                for i in self.rnd.team("ct"):
                    if not self.rnd.alive(i, s0):
                        continue
                    for s in range(s0, self.rnd.meta["n_samples"]):
                        if not self.rnd.alive(i, s):
                            break
                        if self.zone(i, s) == self.plant_site:
                            arrive.append(float(self.rnd.secs[s]))
                            break
                if len(arrive) >= 2:
                    self._retake = (max(arrive) - min(arrive),)
        return self._retake[0]

    def holds(self, i: int, s: int, site: int) -> bool:
        """Whether player i at sample s is within reach of a site, in 3D
        (Nuke's sites are one above the other)."""
        c = sites().get(self.map_name or "", {}).get(str(site))
        if c is None:
            return False
        p = self.rnd.pos(i, s)
        return float(np.linalg.norm(p - np.array([c["x"], c["y"], c["z"]]))) <= c["radius"] + HOLD_REACH

    def stacked(self) -> bool | None:
        """At the plant: no living CT within reach of the planted site and
        three or more within reach of the other one. The game's own
        bombsite flag covers only the plant area, which made this never
        fire (2026-10-16), so reach is from the site's centre instead."""
        if self._stacked is None:
            self._stacked = (None,)
            if (self.rnd and self.plant_t is not None and self.plant_site
                    and str(self.plant_site) in sites().get(self.map_name or "", {})):
                s0 = self.rnd.at(self.plant_t)
                cts = [i for i in self.rnd.team("ct") if self.rnd.alive(i, s0)]
                here = sum(self.holds(i, s0, self.plant_site) for i in cts)
                other = sum(self.holds(i, s0, 3 - self.plant_site) for i in cts)
                self._stacked = (here == 0 and other >= 3,)
        return self._stacked[0]

    def site_utility(self, side: str, site: int, t: float) -> int | None:
        spots = [sp for kind in standards().get(self.map_name or "", {}).get(side, {}).values()
                 for sp in kind if sp["site"] == site]
        if not spots:
            return None
        n = 0
        for g in db.query("""SELECT x, y FROM grenades WHERE match_key = ? AND round_num = ?
                              AND side = ? AND seconds BETWEEN ? AND ?""",
                          self.mk, self.rn, side, t - UTIL_WINDOW, t):
            if any(np.hypot(g["x"] - sp["x"], g["y"] - sp["y"]) <= sp["radius"] + 100
                   for sp in spots):
                n += 1
        return n


# ------------------------------------------------------------------ one death

def facts(match_key: str, round_num: int, seconds: float, victim_side: str,
          rf: RoundFacts | None = None) -> dict | None:
    """Every measurement the detectors read, for one of our deaths."""
    rf = rf or RoundFacts(match_key, round_num)
    if rf.rnd is None:
        return None
    cands = [k for k in rf.kills if k["victim_side"] == victim_side]
    if not cands:
        return None
    k = min(cands, key=lambda r: abs(float(r["seconds"]) - seconds))
    rnd = rf.rnd
    victim = rnd.index.get(str(k["victim_steamid"]))
    killer = rnd.index.get(str(k["attacker_steamid"] or ""))
    if victim is None:
        return None
    t = float(k["seconds"])
    s = rnd.at(t - 0.13)                    # the last sample before he fell
    side, other = victim_side, ("t" if victim_side == "ct" else "ct")
    team, enemies = rnd.team(side), rnd.team(other)
    vp = rnd.pos(victim, s)

    mates = [i for i in team if i != victim and rnd.alive(i, s)]
    dist = [float(np.linalg.norm(rnd.pos(i, s)[:2] - vp[:2])) for i in mates]
    f = {"vision": rnd.vision, "seconds": t, "side": side,
         "nearest_mate": min(dist) if dist else None,
         "mates_near": sum(d <= FIGHT_RADIUS for d in dist) + 1,
         "alive_us": rf.alive_before(side, t), "alive_them": rf.alive_before(other, t),
         "thrusmoke": k["thrusmoke"], "penetrated": k["penetrated"],
         "distance": k["distance"], "in_zone": rf.zone(victim, s),
         "plant_t": rf.plant_t, "plant_site": rf.plant_site}

    # Where the killer was relative to where the victim was looking, and
    # where the killer was looking: the duel.
    if killer is not None:
        f["angle_to_killer"] = V.view_angle_to(rnd, victim, killer, s)
        f["killer_angle"] = V.view_angle_to(rnd, killer, victim, s)
    else:
        f["angle_to_killer"] = f["killer_angle"] = None

    # What the team knew about enemies near the fight, and the killer.
    f["known_enemies_near"] = None
    f.update(killer_known=None, mates_saw_killer_ago=None, victim_saw_killer=None)
    if rnd.vision:
        near = 0
        for e in enemies:
            if not rnd.alive(e, s):
                continue
            sg = rnd.sighting(e, team, s)
            if (sg and sg.state != "unknown" and sg.seconds_ago <= KNOWN_RECENT
                    and np.hypot(sg.x - vp[0], sg.y - vp[1]) <= FIGHT_RADIUS):
                near += 1
        f["known_enemies_near"] = near
        if killer is not None:
            sg = rnd.sighting(killer, team, s)
            f["killer_known"] = sg.state if sg else None
            first = next((i for i in range(max(0, s - 40), s + 1)
                          if victim in rnd.seen_by(killer, i)), None)
            f["victim_saw_killer"] = first is not None
            earlier = rnd.sighting(killer, [i for i in team if i != victim],
                                   max(0, (first if first is not None else s) - 1))
            f["mates_saw_killer_ago"] = (earlier.seconds_ago if earlier and
                                         earlier.state != "unknown" else None)

    # A kill of his own just before, close to where he died: the re-peek.
    sid = str(k["victim_steamid"])
    own = [x for x in rf.kills if x["attacker_steamid"] == sid
           and t - REPEEK_SECONDS <= float(x["seconds"]) < t]
    f["repeek"] = False
    if own:
        s_kill = rnd.at(float(own[-1]["seconds"]))
        f["repeek"] = bool(np.linalg.norm(rnd.pos(victim, s_kill)[:2] - vp[:2]) <= REPEEK_RADIUS)

    blind = db.one("""SELECT MAX(seconds + duration) until FROM blinds
                       WHERE match_key = ? AND round_num = ? AND victim_steamid = ?
                         AND seconds <= ?""", match_key, round_num, sid, t)
    f["blinded"] = bool(blind and blind["until"] is not None and blind["until"] >= t)

    items = [x.strip() for x in rf.loadout.get(sid, "").split(",") if x.strip()]
    f["nades_bought"] = sum(x in GRENADES for x in items)
    f["has_rifle"] = any(x in RIFLES for x in items)
    f["nades_thrown"] = db.one("""SELECT COUNT(*) n FROM grenades WHERE match_key = ?
                                   AND round_num = ? AND steamid = ? AND seconds < ?""",
                               match_key, round_num, sid, t)["n"]

    # The first T to die inside a bombsite before the plant.
    f["entry"] = bool(side == "t" and (rf.plant_t is None or t < rf.plant_t)
                      and f["in_zone"] in (1, 2)
                      and not any(x["victim_side"] == "t" and float(x["seconds"]) < t
                                  and rnd.index.get(str(x["victim_steamid"])) is not None
                                  and rf.zone(rnd.index[str(x["victim_steamid"])],
                                              rnd.at(float(x["seconds"]) - 0.13)) in (1, 2)
                                  for x in rf.kills))

    # Execute or retake, which site, and its standard utility.
    f["exec_site"] = f["retake_site"] = f["std_util_thrown"] = None
    f["retake_spread"] = f["stacked"] = None
    if rf.plant_t is not None and rf.plant_site:
        if side == "t" and 0 <= rf.plant_t - t <= EXEC_WINDOW:
            f["exec_site"] = rf.plant_site
        elif side == "ct" and t >= rf.plant_t:
            f["retake_site"] = rf.plant_site
            f["retake_spread"] = rf.retake_spread()
            f["stacked"] = rf.stacked()
        if f["exec_site"] or f["retake_site"]:
            f["std_util_thrown"] = rf.site_utility(side, rf.plant_site, t)
    return f


def detect(f: dict) -> list[str]:
    """Which detectors fire on these facts, in DETECTORS order."""
    a = f.get("angle_to_killer")
    special = bool(f.get("thrusmoke") or f.get("penetrated"))
    hits = {
        "no_trade": f["nearest_mate"] is None or f["nearest_mate"] > TRADE_FAR,
        "entry_alone": bool(f.get("entry")) and (f["nearest_mate"] is None
                                                 or f["nearest_mate"] > TRADE_FAR),
        "repeek": bool(f.get("repeek")),
        "from_behind": a is not None and not special and a > BEHIND,
        "from_side": a is not None and not special and FRONT < a <= BEHIND,
        "through_smoke": bool(f.get("thrusmoke")),
        "wallbang": bool(f.get("penetrated")),
        "known_angle": (f.get("mates_saw_killer_ago") is not None
                        and KNOWN_MIN_AHEAD <= f["mates_saw_killer_ago"] <= 10
                        and not f.get("victim_saw_killer")),
        "outnumbered": (f.get("side") == "ct" and f.get("known_enemies_near") is not None
                        and f["known_enemies_near"] > f["mates_near"]),
        "crosshair": a is not None and not special and CROSSHAIR_OFF < a <= FRONT,
        "utility_unused": f["nades_bought"] >= 2 and f["nades_thrown"] == 0,
        "fought_blind": bool(f.get("blinded")),
        "no_site_utility": f.get("exec_site") is not None and f.get("std_util_thrown") == 0,
        "no_site_utility_retake": (f.get("retake_site") is not None
                                   and f.get("std_util_thrown") == 0),
        "staggered_retake": (f.get("retake_spread") is not None
                             and f["retake_spread"] > STAGGER),
        "stacked": bool(f.get("stacked")),
        "missed_save": (bool(f.get("has_rifle")) and f.get("alive_them") is not None
                        and f["alive_them"] - f["alive_us"] >= SAVE_DOWN),
    }
    return [code for code in DETECTORS if hits.get(code)]


def proven(code: str) -> bool:
    """Whether college deaths back this detector (tools/decision_evidence.py).
    A 'death' detector needs no proof beyond the death itself."""
    if DETECTORS[code]["proof"] == "death":
        return True
    return bool(evidence().get(code, {}).get("proven"))


def explain(match_key: str, round_num: int, seconds: float,
            victim_side: str) -> list[Finding]:
    """The findings for one death, proven ones first."""
    f = facts(match_key, round_num, seconds, victim_side)
    if f is None:
        return []
    found = [Finding(c, DETECTORS[c]["once"], dict(f), checked=proven(c))
             for c in detect(f)]
    found.sort(key=lambda x: not x.checked)
    return found


# -------------------------------------------------------------------- a season

def season(deaths: list[tuple]) -> dict:
    """Habits over a team's deaths: (match_key, round_num, seconds, side) each.

    -> {code: {"n", "of", "rate", "college", "habit": bool, "examples": [...]}}
    A habit is a proven detector firing on more of the team's deaths than on
    college teams' (decision_evidence.json "rate"), by HABIT_POINTS and
    HABIT_RATIO, at least HABIT_MIN times, with a binomial p under HABIT_P.
    """
    from scipy.stats import binomtest
    rounds: dict = {}
    fired: dict = {c: [] for c in DETECTORS}
    counted = 0
    for mk, rn, secs, side in deaths:
        key = (mk, rn)
        if key not in rounds:
            rounds[key] = RoundFacts(mk, rn)
        f = facts(mk, rn, secs, side, rounds[key])
        if f is None or not f["vision"]:
            continue
        counted += 1
        for c in detect(f):
            fired[c].append((mk, rn, secs))
    ev = evidence()
    out = {}
    for c, hits in fired.items():
        base = ev.get(c, {}).get("rate")
        n = len(hits)
        rate = n / counted if counted else 0.0
        habit = False
        if base is not None and counted and proven(c) and n >= HABIT_MIN:
            p = binomtest(n, counted, base, alternative="greater").pvalue
            habit = (100 * (rate - base) >= HABIT_POINTS and rate >= HABIT_RATIO * base
                     and p < HABIT_P)
        out[c] = {"n": n, "of": counted, "rate": rate, "college": base,
                  "habit": habit, "examples": hits[:5]}
    return out
