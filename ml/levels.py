"""The skill level each side played at, in every college and ESEA round.

    python -m ml.levels          # fetch rosters (cached), write the table

NC State Red's captain pointed out (2026-10-14) that NECC's divisions are
far apart in skill and that some ESEA divisions sit close to some NECC
ones. A model that pools them all is averaging a D1 retake with a D4 one.
This gives every round a level for each side, so a model can tell them
apart:

  necc_d1..necc_d4   the team's NECC Fall 2026 division
                     (outreach/fall-2026-divisions.csv), placement matches
                     included: the division is the team's, not the match's
  esea_open, esea_intermediate, esea_main
                     the ESEA Season 58 division the match was played in
                     (data/esea-s58-na.csv)
  pro                every pro round
  unknown            a team that never got a division, or a match FACEIT
                     could not be asked about

Which team was CT in a round comes from FACEIT's roster for the match (the
Data API lists each team's players by Steam ID) joined to player_rounds,
which records each player's side every round. Rosters are cached in
data/ml/faceit/, one file per match, so this asks FACEIT once per match.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from app import db  # noqa: E402

LEVELS = ["unknown", "necc_d1", "necc_d2", "necc_d3", "necc_d4",
          "esea_open", "esea_intermediate", "esea_main", "pro"]
LEVEL_IDS = {name: i for i, name in enumerate(LEVELS)}

CACHE = ROOT / "data" / "ml" / "faceit"
TABLE = ROOT / "data" / "ml" / "levels_v1.pkl"
DIVISIONS = ROOT / "outreach" / "fall-2026-divisions.csv"
ESEA_LIST = ROOT / "data" / "esea-s58-na.csv"


def _match_id(filename: str) -> str | None:
    return filename[:38] if filename and filename.startswith("1-") else None


def roster(match_id: str) -> dict | None:
    """{team name: [steamids]} for a FACEIT match, cached on disk."""
    path = CACHE / f"{match_id}.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        import esea                               # tools/esea.py: the API client
        try:
            data = esea.get(f"/matches/{match_id}")
        except Exception:                         # noqa: BLE001
            return None
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
        time.sleep(0.2)                           # be gentle with the API
    return {t.get("name", "?"): [str(p.get("game_player_id", ""))
                                for p in t.get("roster", [])]
            for t in (data.get("teams") or {}).values()}


def build() -> pd.DataFrame:
    db.init()
    team_div = {}
    with DIVISIONS.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            team_div[r["team"]] = "necc_" + r["division"].lower()
    esea_div = {}
    if ESEA_LIST.exists():
        with ESEA_LIST.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                d = r["division"].lower()
                esea_div[r["match_id"]] = ("esea_main" if d.startswith("main") else
                                           "esea_intermediate" if d.startswith("inter")
                                           else "esea_open")
    rows = []
    matches = db.query("""SELECT m.match_key, m.tier, d.filename FROM corpus_matches m
                            JOIN demos d ON d.id = m.demo_id
                           WHERE m.tier IN ('league', 'esea', 'pro')""")
    for i, m in enumerate(matches, 1):
        rounds = [r["round_num"] for r in db.query(
            "SELECT round_num FROM rounds WHERE match_key = ?", m["match_key"])]
        if m["tier"] == "pro":
            rows += [(m["match_key"], rn, "pro", "pro") for rn in rounds]
            continue
        mid = _match_id(m["filename"])
        teams = roster(mid) if mid else None
        if not teams:
            rows += [(m["match_key"], rn, "unknown", "unknown") for rn in rounds]
            continue
        team_of = {sid: name for name, sids in teams.items() for sid in sids}
        if m["tier"] == "esea":
            lvl = esea_div.get(mid, "unknown")
            level_of = {name: lvl for name in teams}
        else:
            level_of = {name: team_div.get(name, "unknown") for name in teams}
        sides: dict = {}
        for r in db.query("""SELECT round_num, steamid, side FROM player_rounds
                              WHERE match_key = ?""", m["match_key"]):
            name = team_of.get(str(r["steamid"]))
            if name and r["side"] in ("ct", "t"):
                sides.setdefault((r["round_num"], r["side"]), Counter())[name] += 1
        for rn in rounds:
            ct = sides.get((rn, "ct"))
            t = sides.get((rn, "t"))
            rows.append((m["match_key"], rn,
                         level_of[ct.most_common(1)[0][0]] if ct else "unknown",
                         level_of[t.most_common(1)[0][0]] if t else "unknown"))
        if i % 50 == 0:
            print(f"  {i}/{len(matches)} matches", file=sys.stderr, flush=True)
    return pd.DataFrame(rows, columns=["match_id", "round_num", "level_ct", "level_t"])


def load(rebuild: bool = False) -> pd.DataFrame:
    if TABLE.exists() and not rebuild:
        return pd.read_pickle(TABLE)
    table = build()
    TABLE.parent.mkdir(parents=True, exist_ok=True)
    table.to_pickle(TABLE)
    return table


if __name__ == "__main__":
    os.environ.setdefault("COUNTERPLAY_DB", str(ROOT / "data" / "counterplay.db"))
    t = load(rebuild=True)
    print(f"{len(t)} rounds")
    print(pd.crosstab(t["level_ct"], t["level_t"]).to_string())
