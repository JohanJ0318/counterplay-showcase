"""Which detectors in counterplay/decisions.py may speak, and how common each is.

    python tools/decision_evidence.py            # facts cached in data/ml/
    python tools/decision_evidence.py --refresh  # re-measure every death

Over every college death with vision data, two things per detector:

RATE: the share of college deaths it fires on. decisions.season() holds a
team's rate against it, so a habit is "more than college teams", the same
test the site uses for every other college comparison.

PROOF, by what the mistake directly causes (DETECTORS[code]["proof"]), not
by the final round result, which is too far downstream: on 2026-10-14 every
detector moved round results by under 5 points per death, while spacing
moved the trade rate from 41% to 1%.

  trade  its deaths are traded less often than other deaths (within the
         same side), by at least TRADE_GAP points, p < P_MAX. A trade is
         worth 13 to 16 points of round win (measured, printed below).
  duel   in duels where both players faced each other, the dead player had
         the worse crosshair more than half the time, by DUEL_GAP, p < P_MAX.
  round  from the same win chance just before the death (the scorer's
         model, cross-fitted by match), its deaths end in lost rounds more
         often than OTHER DEATHS IN THE SAME KIND OF MOMENT (CONTEXT below:
         a re-peek against other deaths just after a kill, a retake without
         utility against retakes with it), by ROUND_GAP points, p < P_MAX.
  death  nothing to prove: the detector says how the player died.
  economy  not measured yet; such a detector does not speak.

Comparing within the same kind of moment matters: against all deaths, "went
into a site without the usual utility" came out 18 points GOOD, because the
others included every round that never reached a site.
"""
from __future__ import annotations

import json
import pickle
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import binomtest, ttest_ind

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402
from counterplay import decisions as D  # noqa: E402

P_MAX = 0.20
TRADE_GAP = 5.0
DUEL_GAP = 3.0
ROUND_GAP = 3.0
MIN_FIRED = 30
TRADE_SECONDS = 5.0
FOLDS = 5
CACHE = ROOT / "data" / "ml" / "decision_facts_v2.pkl"

# For a "round" detector: which deaths it is fairly compared with.
CONTEXT = {
    "repeek": lambda f: f.get("repeek") is not None and _had_kill(f),
    "outnumbered": lambda f: f["side"] == "ct" and f.get("known_enemies_near") is not None,
    "no_site_utility": lambda f: f.get("exec_site") is not None and f.get("std_util_thrown") is not None,
    "no_site_utility_retake": lambda f: f.get("retake_site") is not None and f.get("std_util_thrown") is not None,
    "staggered_retake": lambda f: f.get("retake_spread") is not None,
    "stacked": lambda f: f.get("stacked") is not None,
}


def _had_kill(f):
    return f.get("_had_kill", False)


def college_deaths():
    keys = [r["match_key"] for r in db.query(
        """SELECT DISTINCT p.match_key FROM round_positions p
             JOIN corpus_matches m ON m.match_key = p.match_key
            WHERE m.tier = 'league' AND hex(substr(p.data, 1, 1)) = '02'""")]
    marks = ",".join("?" * len(keys))
    won = {(r["match_key"], r["round_num"]): bool(r["ct_won"]) for r in db.query(
        f"SELECT match_key, round_num, ct_won FROM rounds WHERE match_key IN ({marks})", *keys)}
    by_round = defaultdict(list)
    for e in db.query(f"""SELECT match_key, round_num, seconds, victim_side,
                                 victim_steamid, attacker_steamid
                            FROM events WHERE type = 'death' AND match_key IN ({marks})
                        ORDER BY match_key, round_num, seconds""", *keys):
        by_round[(e["match_key"], e["round_num"])].append(e)
    for (mk, rn), deaths in by_round.items():
        rf = D.RoundFacts(mk, rn)
        for e in deaths:
            side = e["victim_side"]
            if side not in ("ct", "t"):
                continue
            other = "t" if side == "ct" else "ct"
            t = float(e["seconds"])
            traded = any(d["victim_steamid"] == e["attacker_steamid"] and d["victim_side"] == other
                         and t < float(d["seconds"]) <= t + TRADE_SECONDS for d in deaths)
            had_kill = any(d["attacker_steamid"] == e["victim_steamid"]
                           and t - D.REPEEK_SECONDS <= float(d["seconds"]) < t for d in deaths)
            f = D.facts(mk, rn, t, side, rf)
            if f is None or not f["vision"]:
                continue
            f["_had_kill"] = had_kill
            yield {"mk": mk, "rn": rn, "seconds": t, "side": side, "facts": f,
                   "traded": traded, "won": won.get((mk, rn)) == (side == "ct")}


def win_chance_before() -> dict:
    """(match, round, seconds, victim side) -> that side's win chance on the
    state just before the death, cross-fitted by match."""
    from app import corpus
    from counterplay import model as M
    from counterplay import posfeat
    from counterplay import state as state_mod
    states = posfeat.attach(state_mod.build_states(*corpus.load_frames(tier="league")))
    states = states.sort_values(["match_id", "round_num", "event_idx"]).reset_index(drop=True)
    ids = np.array(sorted(states["match_id"].unique()))
    fold_of = dict(zip(ids, np.random.default_rng(7).permutation(len(ids)) % FOLDS))
    folds = states["match_id"].map(fold_of).to_numpy()
    wp_ct = np.empty(len(states))
    for k in range(FOLDS):
        model, _r, _c = M.train(states[folds != k].reset_index(drop=True), seed=7 + k)
        wp_ct[folds == k] = model.predict(states[folds == k])
    states["wp_prev"] = pd_shift(states, wp_ct)
    out = {}
    for r in states[states["event_type"] == "death"].itertuples(index=False):
        if r.wp_prev == r.wp_prev:
            out[(r.match_id, int(r.round_num), round(float(r.seconds), 3), r.victim_side)] = (
                r.wp_prev if r.victim_side == "ct" else 1.0 - r.wp_prev)
    return out


def pd_shift(states, wp_ct):
    states = states.assign(wp_ct=wp_ct)
    return states.groupby(["match_id", "round_num"])["wp_ct"].shift()


def main():
    db.init()
    if CACHE.exists() and "--refresh" not in sys.argv:
        rows = pickle.loads(CACHE.read_bytes())
    else:
        rows = list(college_deaths())
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_bytes(pickle.dumps(rows))
    for r in rows:
        r["fired"] = set(D.detect(r["facts"]))
    print(f"{len(rows)} college deaths with vision", flush=True)

    traded = np.array([r["traded"] for r in rows])
    wp = win_chance_before()
    for r in rows:
        r["wp"] = wp.get((r["mk"], r["rn"], round(r["seconds"], 3), r["side"]))
    with_wp = [r for r in rows if r["wp"] is not None]
    tv = {}
    for side in ("t", "ct"):
        a = [r["won"] - r["wp"] for r in with_wp if r["side"] == side and r["traded"]]
        b = [r["won"] - r["wp"] for r in with_wp if r["side"] == side and not r["traded"]]
        tv[side] = 100 * (np.mean(a) - np.mean(b))
    print(f"a trade is worth {tv['t']:+.1f} points of round win as T, {tv['ct']:+.1f} as CT\n")

    out = {"_meta": {"deaths": len(rows), "trade_value_points": tv,
                     "trade_far": D.TRADE_FAR}}
    print(f"{'detector':24s} {'rate':>6s}  proof    result")
    for code, det in D.DETECTORS.items():
        fired = [r for r in rows if code in r["fired"]]
        rate = len(fired) / len(rows)
        e = {"rate": round(rate, 4), "fired": len(fired), "proof": det["proof"]}
        proof = det["proof"]
        if proof == "death":
            e.update(proven=True, why="describes how the player died")
        elif len(fired) < MIN_FIRED:
            e.update(proven=False, why=f"fewer than {MIN_FIRED} college deaths")
        elif proof == "trade":
            # Within the same side, traded less often than the other deaths.
            gaps, ps = [], []
            for side in ("t", "ct"):
                f_side = [r["traded"] for r in fired if r["side"] == side]
                o_side = [r["traded"] for r in rows if r["side"] == side and code not in r["fired"]]
                if len(f_side) >= MIN_FIRED and o_side:
                    gaps.append(100 * (np.mean(f_side) - np.mean(o_side)))
                    ps.append(binomtest(sum(f_side), len(f_side), np.mean(o_side)).pvalue)
            gap = float(np.mean(gaps)) if gaps else 0.0
            e.update(gap_points=round(gap, 1), p=round(min(ps), 4) if ps else 1.0,
                     proven=bool(gaps and gap <= -TRADE_GAP and max(ps) < P_MAX),
                     why="traded less often than other deaths on the same side")
        elif proof == "duel":
            duels = [r for r in rows if r["facts"].get("angle_to_killer") is not None
                     and r["facts"].get("killer_angle") is not None
                     and r["facts"]["angle_to_killer"] <= D.FRONT
                     and r["facts"]["killer_angle"] <= D.FRONT]
            worse = sum(r["facts"]["angle_to_killer"] > r["facts"]["killer_angle"] for r in duels)
            share = worse / len(duels) if duels else 0.5
            p = binomtest(worse, len(duels), 0.5).pvalue if duels else 1.0
            e.update(duels=len(duels), loser_had_worse_crosshair=round(share, 3),
                     p=round(p, 4), proven=bool(100 * (share - 0.5) >= DUEL_GAP and p < P_MAX),
                     why="in face-to-face duels the dead player had the worse crosshair")
        elif proof == "round":
            ctx = [r for r in with_wp if CONTEXT.get(code, lambda f: True)(r["facts"])]
            a = np.array([r["won"] - r["wp"] for r in ctx if code in r["fired"]])
            b = np.array([r["won"] - r["wp"] for r in ctx if code not in r["fired"]])
            if len(a) >= MIN_FIRED and len(b) >= MIN_FIRED:
                gap = 100 * (a.mean() - b.mean())
                p = float(ttest_ind(a, b, equal_var=False).pvalue)
                e.update(gap_points=round(gap, 1), p=round(p, 4), compared_with=len(b),
                         proven=bool(gap <= -ROUND_GAP and p < P_MAX),
                         why="from the same win chance, lost more rounds than the same kind of moment")
            else:
                e.update(proven=False, why="too few deaths in its kind of moment to compare")
        else:
            e.update(proven=False, why="its proof is not measured yet")
        out[code] = e
        detail = ("" if proof == "death" else
                  f"gap {e.get('gap_points', '')}  p {e.get('p', '')}" if "gap_points" in e else
                  f"loser worse {e['loser_had_worse_crosshair']:.0%} of {e['duels']} duels, p {e['p']}"
                  if "duels" in e else e["why"])
        print(f"{code:24s} {rate:6.1%}  {proof:7s}  {'PROVEN' if e['proven'] else 'no':6s}  {detail}")
    D.EVIDENCE.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"\nwrote {D.EVIDENCE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
