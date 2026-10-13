"""The decision scorer's worst moments for one team, for a human to check.

    python tools/verdicts.py STEAMID [STEAMID ...] > verdicts.txt

Calibration (tools/holdout.py) says the probabilities are honest on
average. It does not say a verdict on one round makes sense, and that is the
part a coach would read. This prints the N moments the scorer calls most
costly for a team, relative to what that situation normally costs
(rank.add_excess_cost), so someone who knows the game can watch each round
and say right or wrong. tools/coach_read.py uses moments() for its
experimental facts.

The team's own maps are LEFT OUT of training: the scorer judges games it
has never seen, the way it would in use. The team is found by the given
steamids (its recurring players) in the collegiate corpus on this PC; its
side in each round is the side most of them stood on.

Times are seconds after freeze time ends: on the in-game clock (1:55 at the
start) "0:29 into the round" is about 1:26 on the timer.
"""
from __future__ import annotations

import os
import sys
from collections import Counter

sys.path.insert(0, r"C:/Users/Johan/counterplay")
os.environ.setdefault("COUNTERPLAY_DB", r"C:/Users/Johan/counterplay/data/counterplay.db")

# rank.describe joins its two halves with an em dash; the output uses a comma.
DASH = f" {chr(8212)} "


def moments(steamids: list[str], n: int = 10) -> list[dict]:
    """The n costliest moments for the team these players form, or [] when
    none of their maps are in the corpus here."""
    from app import corpus, db
    from counterplay import model as M
    from counterplay import rank
    from counterplay import state as state_mod

    if not steamids:
        return []
    db.init()
    marks = ",".join("?" * len(steamids))
    rows = db.query(f"""SELECT pr.match_key, pr.round_num, pr.side
                          FROM player_rounds pr
                          JOIN corpus_matches m ON m.match_key = pr.match_key
                         WHERE m.tier = 'league' AND pr.steamid IN ({marks})""",
                    *steamids)
    votes: dict = {}
    for r in rows:
        votes.setdefault((r["match_key"], r["round_num"]), Counter())[r["side"]] += 1
    side_of = {k: c.most_common(1)[0][0] for k, c in votes.items()}
    theirs = {k for k, _ in side_of}
    if not theirs:
        return []
    maps = {r["match_key"]: r["map_name"].replace("de_", "") for r in db.query(
        f"SELECT match_key, map_name FROM corpus_matches WHERE match_key IN "
        f"({','.join('?' * len(theirs))})", *theirs)}

    rounds, events = corpus.load_frames(tier="league")
    states = state_mod.build_states(rounds, events)
    model, _report, _ = M.train(states[~states["match_id"].isin(theirs)], seed=7)

    picked = []
    for side in ("ct", "t"):
        scored = rank.add_excess_cost(rank.score_moments(model, states, side=side), side)
        mine = scored[[side_of.get((m, r)) == side for m, r in
                       zip(scored["match_id"], scored["round_num"])]]
        costly = mine[(mine["wp_delta"] < 0) & mine["kind"].isin(["loss", "plant"])]
        picked += [(r.excess_cost, side, r) for r in costly.itertuples(index=False)]
    picked.sort(key=lambda x: x[0])

    out = []
    for _excess, side, r in picked[:n]:
        out.append({
            "map": maps[r.match_id], "round": int(r.round_num), "side": side,
            "seconds": int(r.seconds),
            "situation": rank.describe(r, side).replace(DASH, ", "),
            "before": round(100 * r.wp_before),
            "after": round(100 * (r.wp_before + r.wp_delta)),
            "usual": round(-100 * r.expected_delta),
            "baseline_n": int(r.baseline_n)})
    return out


def main() -> int:
    ms = moments(sys.argv[1:])
    if not ms:
        print("none of these players' maps are in the corpus on this PC")
        return 1
    for i, m in enumerate(ms, 1):
        mins, secs = divmod(m["seconds"], 60)
        print(f"{i:2d}. {m['map']} round {m['round']}, {mins}:{secs:02d} into the "
              f"round, as {m['side'].upper()}: {m['situation']}")
        print(f"    win chance {m['before']}% -> {m['after']}% (cost "
              f"{m['before'] - m['after']} points; this situation usually costs "
              f"{m['usual']}, compared over {m['baseline_n']} moments)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
