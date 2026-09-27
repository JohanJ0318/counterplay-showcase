"""Stored rounds → the frames the engine expects.

The bridge back out of the database. `parse.py` produces two dataframes,
`state.py` and `model.py` consume exactly those, and `ingest.py` writes them to
tables in between. This reads them back in the same shape, so a corpus assembled
from 780 league matches is indistinguishable to the model from one parsed in
memory — and `run.py --db` trains on it with no other changes.

The filters exist to keep one promise. `tier` selects the population the model
conditions on. `team_id` restricts to a team's own matches, which is what a
report is built from. Aggregate baselines come from everything; a team's report
comes only from that team's rows. Nothing here can produce a profile of a team
that never signed up, because there is no argument that asks for one.
"""
from __future__ import annotations

import pandas as pd

from . import db

# Every match once: the `corpus_matches` view (migration 25) drops a second
# team's parse of bytes already parsed for another team.
CORPUS_KEYS = "SELECT match_key FROM corpus_matches"


def load_frames(tier: str | None = None, team_id: int | None = None,
                match_keys: list[str] | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (rounds, events) shaped exactly like parse.py's output.

    `team_id` restricts to demos that team uploaded or that were attributed to
    them. Leave it None for the whole corpus, which is what training wants.
    """
    where, args = [], []
    if tier:
        where.append("r.tier = ?")
        args.append(tier)
    if team_id is not None:
        where.append("""r.match_key IN (SELECT m.match_key FROM matches m
                          JOIN demos d ON d.id = m.demo_id
                         WHERE d.team_id = ?)""")
        args.append(team_id)
    if match_keys:
        marks = ",".join("?" * len(match_keys))
        where.append(f"r.match_key IN ({marks})")
        args.extend(match_keys)
    elif team_id is None:
        # Across every team, a match two teams both uploaded is one match.
        # Twice in the corpus it could sit in train and in test at once.
        where.append(f"r.match_key IN ({CORPUS_KEYS})")
    clause = (" WHERE " + " AND ".join(where)) if where else ""

    rounds = pd.DataFrame(
        [dict(x) for x in db.query(
            f"""SELECT r.match_key AS match_id, r.round_num, r.map_name,
                       r.equip_ct, r.equip_t, r.ct_won, r.tier, r.plant_site
                  FROM rounds r{clause}
              ORDER BY r.match_key, r.round_num""", *args)],
        columns=["match_id", "round_num", "map_name", "equip_ct", "equip_t",
                 "ct_won", "tier", "plant_site"])

    if rounds.empty:
        return rounds, pd.DataFrame(
            columns=["match_id", "round_num", "seconds", "type", "victim_side"])

    keys = rounds["match_id"].unique().tolist()
    marks = ",".join("?" * len(keys))
    events = pd.DataFrame(
        [dict(x) for x in db.query(
            f"""SELECT match_key AS match_id, round_num, seconds, type, victim_side
                  FROM events WHERE match_key IN ({marks})
              ORDER BY match_key, round_num, seconds""", *keys)],
        columns=["match_id", "round_num", "seconds", "type", "victim_side"])

    # ct_won is stored as 0/1; the engine treats it as a boolean label.
    rounds["ct_won"] = rounds["ct_won"].astype(bool)
    return rounds, events


def summary() -> dict:
    """What the corpus currently holds. For the CLI and the dashboard."""
    once = f"WHERE match_key IN ({CORPUS_KEYS})"
    row = db.one(f"""SELECT COUNT(DISTINCT match_key) matches,
                            COUNT(*) rounds FROM rounds {once}""")
    ev = db.one(f"SELECT COUNT(*) n FROM events {once}")
    by_tier = db.query(f"""SELECT tier, COUNT(DISTINCT match_key) m, COUNT(*) r
                             FROM rounds {once} GROUP BY tier ORDER BY r DESC""")
    by_map = db.query(f"""SELECT map_name, COUNT(*) r FROM rounds {once}
                        GROUP BY map_name ORDER BY r DESC""")
    status = db.query("""SELECT status, COUNT(*) n FROM demos
                       GROUP BY status ORDER BY n DESC""")
    return {
        "matches": row["matches"] or 0,
        "rounds": row["rounds"] or 0,
        "events": ev["n"] or 0,
        "by_tier": [(r["tier"], r["m"], r["r"]) for r in by_tier],
        "by_map": [(r["map_name"], r["r"]) for r in by_map],
        "demo_status": [(r["status"], r["n"]) for r in status],
    }


def print_summary() -> None:
    s = summary()
    print(f"\n  corpus: {s['matches']} matches, {s['rounds']} rounds, "
          f"{s['events']} events")
    if s["by_tier"]:
        print("\n  by tier")
        for tier, m, r in s["by_tier"]:
            print(f"    {tier:<12} {m:>5} matches  {r:>7} rounds")
    if s["by_map"]:
        print("\n  by map")
        for name, r in s["by_map"][:10]:
            print(f"    {name:<14} {r:>7} rounds")
    if s["demo_status"]:
        print("\n  demo queue")
        for st, n in s["demo_status"]:
            print(f"    {st:<12} {n:>6}")
    # A model needs a few hundred matches before its numbers describe anything.
    # Saying so here is cheaper than finding out from a calibration failure.
    if s["matches"] and s["matches"] < 200:
        print(f"\n  {s['matches']} matches is enough to SCORE with a model fitted "
              f"elsewhere,\n  but not to train one. Aim for a few hundred before "
              f"trusting a retrain.")


if __name__ == "__main__":
    db.init()
    print_summary()
