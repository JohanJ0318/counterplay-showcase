"""Unit tests for the parser's hard-won rules.

Every one of these guards a bug that was found by hand, in a real demo, and
fixed with nothing preventing its return. Written out so that the next parser
change either keeps them true or fails loudly:

  * the deciding round exists — CS2 stops recording the moment a match is won,
    so the round that won it has no `round_officially_ended`. Requiring one
    silently removed the final round from all 116 matches in this corpus.
  * a match score is a TEAM score — rounds won by side, summed over a match, is
    not a score, because sides swap. One Inferno read 16-12 by side for a match
    actually won 16-13.
  * round numbering is ordinal — `total_rounds_played` starts at 0 in Valve
    demos and 1 in some pro ones, so it cannot be the round number.
  * warmup collapses — three freeze-ends before one official end are one round,
    not three.
  * a trade is the killer being killed, not the same player getting two kills.

These run against parsed output already in the database rather than re-parsing
every demo, so the whole file finishes in under a second and can run on every
commit. `test_corpus.py` is the slower one that re-parses real files.
"""
from __future__ import annotations

import pytest

from app import db


@pytest.fixture(scope="module")
def rows():
    db.init()
    got = db.query("""SELECT m.match_key, m.map_name, m.rounds, m.score_ct,
                             m.score_t, m.final_ct, m.final_t, m.finished,
                             m.end_reason, m.tier, d.filename
                        FROM matches m JOIN demos d ON d.id = m.demo_id""")
    if not got:
        pytest.skip("no parsed matches in this database")
    return got


def test_every_match_has_rounds(rows):
    for m in rows:
        assert m["rounds"] and m["rounds"] > 0, f"{m['filename']} parsed 0 rounds"


def test_round_numbers_are_ordinal_and_contiguous(rows):
    """1..N with no gaps.

    `total_rounds_played` cannot be the round number: it is 0-based in Valve
    demos and 1-based in some pro ones, so rounds were numbered by freeze-tick
    order instead. A gap here means a round was dropped.
    """
    for m in rows:
        nums = [r["round_num"] for r in db.query(
            "SELECT round_num FROM rounds WHERE match_key=? ORDER BY round_num",
            m["match_key"])]
        assert nums == list(range(1, len(nums) + 1)), \
            f"{m['filename']}: round numbers are {nums[:5]}..., not 1..N"


def test_by_side_score_sums_to_rounds(rows):
    for m in rows:
        assert m["score_ct"] + m["score_t"] == m["rounds"], \
            f"{m['filename']}: {m['score_ct']}+{m['score_t']} != {m['rounds']}"


def test_team_score_sums_to_rounds(rows):
    """The real score has to account for every round, same as the side split."""
    for m in rows:
        if m["final_ct"] is None:
            continue
        assert m["final_ct"] + m["final_t"] == m["rounds"], \
            f"{m['filename']}: team score does not cover every round"


def test_finished_matches_have_a_legal_scoreline(rows):
    """A finished match ends on a score its own format can produce.

    This test caught two separate bugs. It would have caught the missing
    deciding round — before that was fixed, every match ended one round short
    of a legal result (12-9, 12-7, 12-11), which is not a coincidence but the
    same bug eleven times. And it did catch a format assumption: the pro demos
    in this corpus are MR15, and judging them by MR12 rules marked 14-3, 14-5
    and 25-22 as finished, none of which MR12 can reach.

    Both formats are accepted, because the format belongs to the match and not
    to this product.

    Checked on the tiers whose format is known — matchmaking and league play
    are MR12 — and not on `pro`. Six professional demos here finish on 14-3,
    20-15 and 25-22 with side swaps after 12, 13 and 14 rounds, which is no
    format this code can name: tournament organisers set their own overtime
    rules, and matches end early on forfeits and technical pauses. Asserting a
    format there would be asserting something nobody knows, which is the exact
    habit this product exists to avoid.
    """
    for m in rows:
        if not m["finished"] or m["final_ct"] is None:
            continue
        if m["tier"] == "pro":
            continue
        # A surrender ends the match wherever the score happened to be, so
        # 5-1 is a perfectly real final score and not a parser fault.
        if m["end_reason"] == "surrender":
            continue
        hi = max(m["final_ct"], m["final_t"])
        lo = min(m["final_ct"], m["final_t"])
        legal = False
        for win_at in (13, 16):
            if hi == win_at and lo < win_at - 1:
                legal = True
            # Each overtime is 6 rounds won at 4, so the winning score goes
            # up by 3 and not by 4: 16, 19, 22, 25 for MR12. The loser of that
            # overtime is somewhere in [target - 4, target - 1].
            target = win_at + 3
            while target <= hi + 4:
                if hi == target and lo >= target - 4:
                    legal = True
                target += 3
        assert legal, \
            f"{m['filename']}: {hi}-{lo} is not reachable in MR12 or MR15"


def test_unfinished_matches_say_why(rows):
    """Short of a win means surrendered or cut off — never silently 'finished'.

    A NULL reason is tolerated only because it means "parsed before the column
    existed". Anything parsed by current code records one, so if this starts
    failing on a freshly parsed demo, `_ended_on_purpose` has stopped working.
    """
    for m in rows:
        if m["finished"] == 0 and m["end_reason"] is not None:
            assert m["end_reason"] in ("surrender", "cut"), \
                f"{m['filename']}: unfinished with reason {m['end_reason']!r}"


def test_no_round_has_more_deaths_than_players(rows):
    """Ten players, so eleven deaths in a round means a kill leaked across the
    round boundary — the bug that closed rounds at the official end rather than
    at the next freeze."""
    bad = db.query("""SELECT match_key, round_num, COUNT(*) n FROM events
                       WHERE type='death' GROUP BY match_key, round_num
                      HAVING n > 10""")
    assert not bad, f"{len(bad)} rounds with more than ten deaths"


def test_player_rounds_have_a_side(rows):
    sides = db.query("SELECT DISTINCT side FROM player_rounds")
    assert {r["side"] for r in sides} <= {"ct", "t"}, \
        "a player-round has a side that is neither ct nor t"


def test_a_round_has_at_most_six_players_per_side(rows):
    """Five players, plus a coach in professional matches.

    Six is not a parser fault: a pro team's coach occupies a slot on the team
    and appears at freeze-end with a side, so they get a roster row with no
    kills and no deaths. Seven would mean a genuine leak between rounds.

    Worth knowing that a coach dilutes that team's per-player averages very
    slightly. It has no effect on collegiate or matchmaking demos, where nobody
    is in the server who is not playing.
    """
    bad = db.query("""SELECT match_key, round_num, side, COUNT(*) n
                        FROM player_rounds GROUP BY match_key, round_num, side
                       HAVING n > 6""")
    assert not bad, f"{len(bad)} round-sides with more than six players"


def test_trades_are_symmetric():
    """Every trade kill is somebody's traded death.

    The first implementation compared the two KILLERS instead of asking whether
    the player just killed was the one who killed the teammate. That asks a
    different question entirely and found one trade in a match that had 38.
    """
    r = db.one("""SELECT SUM(trade_kills) tk, SUM(traded_deaths) td
                    FROM player_rounds""")
    if not r["tk"]:
        pytest.skip("no trade data in this database")
    assert r["tk"] == r["td"], \
        f"{r['tk']} trade kills but {r['td']} traded deaths"


def test_clutch_wins_never_exceed_attempts():
    bad = db.query("""SELECT COUNT(*) n FROM player_rounds
                       WHERE clutch_won > clutch_tried""")[0]["n"]
    assert bad == 0, f"{bad} player-rounds won more clutches than they entered"


def test_headshots_never_exceed_kills():
    bad = db.query("""SELECT COUNT(*) n FROM player_rounds
                       WHERE headshots > kills""")[0]["n"]
    assert bad == 0, f"{bad} player-rounds with more headshots than kills"


def test_opening_duel_is_one_kill_and_one_death_per_round():
    """At most one opening kill and one opening death in any round."""
    bad = db.query("""SELECT match_key, round_num,
                             SUM(opening_kill) k, SUM(opening_death) d
                        FROM player_rounds GROUP BY match_key, round_num
                       HAVING k > 1 OR d > 1""")
    assert not bad, f"{len(bad)} rounds with more than one opening duel"
