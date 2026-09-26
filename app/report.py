"""Match reports.

Everything here is COUNTED. No model, no estimate, no prediction — arithmetic
over parsed rounds and events, with the denominator printed beside every rate
and the round numbers listed so a coach can open the demo and check.

That is not a limitation to apologise for, it is the point. A collegiate coach
handed a number they cannot verify has no reason to believe it. A number with
"8 of 11, rounds 2, 4, 5, 7, 9, 10, 11" beside it can be checked in ninety
seconds, and once they have checked one they will believe the rest.

Decision scoring — which decision cost you a round you were winning — is the
one thing on the report that needs a trained model, and it is deliberately
absent until there is a corpus to train on. It says so, rather than showing a
number that came from a simulator.
"""
from __future__ import annotations

from collections import defaultdict

from counterplay.schema import classify_round

from . import db, memo

# Below this many chances, a percentage is noise wearing a percent sign.
MIN_CHANCES = 8

# A role read off fewer rounds than this is a guess. Half a match is the floor.
MIN_ROUNDS_FOR_ROLE = 10


# Role rules, not clustering. Every label carries the number that produced it,
# so a coach can disagree with one and see exactly why it was applied.
def role_of(a: dict) -> tuple[str, str]:
    """A player's role and the figure behind it."""
    kills, rounds = a["kills"], a["rounds"]
    if rounds < MIN_ROUNDS_FOR_ROLE:
        return "–", f"only {rounds} rounds"
    if a["awp_kills"] >= 5 and kills and a["awp_kills"] / kills >= 0.20:
        return "AWP", f"{a['awp_kills']} of {kills} kills with the AWP"
    opens = a["opening_kills"] + a["opening_deaths"]
    if rounds and opens / rounds >= 0.30:
        return "Entry", f"took the opening duel {opens} of {rounds} rounds"
    # Support has to out-set-up its own fragging, not merely clear an assist
    # rate. Without the second clause a star rifler on 18 kills and 3 assists
    # came back "Support" purely because 3/11 rounds cleared 0.20 — the kind of
    # label a coach spots in one glance and stops trusting the page over.
    if rounds and a["assists"] / rounds >= 0.20 and a["assists"] * 2 >= kills:
        return "Support", (f"{a['assists']} assists to {kills} kills "
                           f"over {rounds} rounds")
    return "Rifle", f"{a['damage'] / rounds:.0f} ADR over {rounds} rounds"


def is_coach(a: dict) -> bool:
    """A FACEIT coach: present for the rounds, and never shot, died or hurt anyone.

    A coach occupies a slot in the demo and is alive all round without ever
    shooting, so they arrive like a player and every number computed for them
    is an artifact: role_of() calls them a Rifle because their ADR is zero, and
    the clutch counter calls them the last man alive in every long round, which
    reads as "0 of 22" against a man who cannot hold a gun.

    Filtering the "Coach|" name prefix would be trusting a convention anybody
    can type into their profile. This tests what a coach is. A real player
    does not go a whole match without dying once.

    `a` is any totals dict with kills, deaths and damage. Judge it over all of
    a person's rounds, never over a subset, or a real player's two quiet
    rounds on the other side would read as a coach.
    """
    return not (a["kills"] or a["deaths"] or a["damage"])


# A player has to appear in this share of a team's matches to be treated as one
# of theirs. Opponents change every match; the team does not.
ANCHOR_SHARE = 0.6


@memo.by_team
def team_anchors(team_id: int) -> dict:
    """Which players are this team's, inferred from who keeps turning up.

    A demo carries no team names — only which side each player was on, and
    sides swap at half. But a team plays every one of its own matches, and its
    opponents play one each. So the players who appear in most of a team's
    matches ARE the team, and whichever side they are on in a given round is
    that team's side for that round.

    One recurring player is enough to answer it. That matters, because in
    solo-queue Premier the roster changes every game and only the account
    holder recurs — which is exactly the case this was built against.

    Returns {} when there is nothing to infer from: a single match, where every
    player appears in 100% of them and the signal does not exist yet.
    """
    n_matches = db.one("""SELECT COUNT(DISTINCT m.match_key) n FROM matches m
                            JOIN demos d ON d.id = m.demo_id
                           WHERE d.team_id = ?""", team_id)["n"]
    if n_matches < 2:
        return {"anchors": {}, "matches": n_matches, "confident": False}

    rows = db.query("""SELECT pr.steamid, pr.name,
                              COUNT(DISTINCT pr.match_key) appearances
                         FROM player_rounds pr
                         JOIN matches m ON m.match_key = pr.match_key
                         JOIN demos d ON d.id = m.demo_id
                        WHERE d.team_id = ?
                     GROUP BY pr.steamid
                       HAVING appearances >= ?
                     ORDER BY appearances DESC""",
                    team_id, max(2, int(n_matches * ANCHOR_SHARE)))
    anchors = {r["steamid"]: {"name": r["name"], "appearances": r["appearances"]}
               for r in rows}
    return {"anchors": anchors, "matches": n_matches, "confident": bool(anchors)}


def _side_by_round(team_id: int, anchors: dict) -> dict:
    """(match_key, round_num) -> the side this team was on, for rounds we can tell.

    Uses whichever side the anchors were on. If they disagree — which happens
    when one is a stand-in on the other team — the majority wins, and a tie is
    left unknown rather than guessed.
    """
    if not anchors:
        return {}
    marks = ",".join("?" * len(anchors))
    rows = db.query(f"""SELECT pr.match_key, pr.round_num, pr.side, COUNT(*) n
                          FROM player_rounds pr
                          JOIN matches m ON m.match_key = pr.match_key
                          JOIN demos d ON d.id = m.demo_id
                         WHERE d.team_id = ? AND pr.steamid IN ({marks})
                      GROUP BY pr.match_key, pr.round_num, pr.side""",
                    team_id, *anchors.keys())
    tally = defaultdict(dict)
    for r in rows:
        tally[(r["match_key"], r["round_num"])][r["side"]] = r["n"]
    out = {}
    for key, counts in tally.items():
        ct, t = counts.get("ct", 0), counts.get("t", 0)
        if ct != t:
            out[key] = "ct" if ct > t else "t"
    return out


@memo.by_team
def our_sides(team_id: int) -> dict:
    """(match_key, round_num) -> the side this team was on. One call, one map.

    Every team-aware count on the site starts here, so they cannot disagree
    with each other about which rounds were whose.
    """
    return _side_by_round(team_id, team_anchors(team_id).get("anchors", {}))


def ours_by_round(team_id: int, match_key: str | None = None) -> set:
    """The (match_key, round_num, steamid) rows that are this team's.

    A player is ours in a round if they were on our side in it. That is the
    whole test, and unlike "appears in most of our matches" it is a reading
    rather than an inference: it gets the fifth who played once right, and it
    gets the stand-in who turned out for the other team right too.
    """
    sides = our_sides(team_id)
    if not sides:
        return set()
    where = "d.team_id = ?"
    args: list = [team_id]
    if match_key:
        where += " AND pr.match_key = ?"
        args.append(match_key)
    return {(r["match_key"], r["round_num"], r["steamid"])
            for r in db.query(f"""SELECT pr.match_key, pr.round_num, pr.steamid,
                                         pr.side
                                    FROM player_rounds pr
                                    JOIN matches m ON m.match_key = pr.match_key
                                    JOIN demos d ON d.id = m.demo_id
                                   WHERE {where}""", *args)
            if sides.get((r["match_key"], r["round_num"])) == r["side"]}


def _rounds_and_events(match_key: str):
    rounds = db.query("""SELECT * FROM rounds WHERE match_key = ?
                      ORDER BY round_num""", match_key)
    events = db.query("""SELECT * FROM events WHERE match_key = ?
                      ORDER BY round_num, seconds""", match_key)
    return rounds, events


def build(match_key: str, team_id: int | None = None) -> dict | None:
    """Everything the report page needs, counted.

    `team_id` is what turns a match into YOUR match: with it the opening-duel
    and buy tables are counted from this team's rounds rather than from a side
    that changes hands at the half.
    """
    match = db.one("SELECT * FROM matches WHERE match_key = ?", match_key)
    if match is None:
        return None
    rounds, events = _rounds_and_events(match_key)
    if not rounds:
        return None

    by_round = defaultdict(list)
    for e in events:
        by_round[e["round_num"]].append(e)

    rows = []
    for r in rounds:
        evs = by_round.get(r["round_num"], [])
        deaths = [e for e in evs if e["type"] == "death"]
        plant = next((e for e in evs if e["type"] == "plant"), None)
        first = deaths[0] if deaths else None

        rows.append({
            "round_num": r["round_num"],
            "ct_won": bool(r["ct_won"]),
            "equip_ct": r["equip_ct"],
            "equip_t": r["equip_t"],
            "buy_ct": classify_round(r["equip_ct"], r["round_num"]),
            "buy_t": classify_round(r["equip_t"], r["round_num"]),
            "deaths_ct": sum(1 for d in deaths if d["victim_side"] == "ct"),
            "deaths_t": sum(1 for d in deaths if d["victim_side"] == "t"),
            # The opening duel: who lost the first player. The single most
            # coachable thing on a scoreboard, and it needs no model at all.
            "opening_loser": first["victim_side"] if first else None,
            "opening_at": first["seconds"] if first else None,
            "planted": plant is not None,
            "plant_at": plant["seconds"] if plant else None,
            "duration": max((e["seconds"] for e in evs), default=0.0),
        })

    n = len(rows)
    ct_wins = sum(1 for x in rows if x["ct_won"])

    # --- opening duels ----------------------------------------------------
    # "You lost the first duel and then lost the round" is the finding a coach
    # can act on this week. Counted from both sides.
    opening = {}
    for side in ("ct", "t"):
        lost = [x for x in rows if x["opening_loser"] == side]
        won_anyway = [x for x in lost if (x["ct_won"] if side == "ct" else not x["ct_won"])]
        taken = [x for x in rows if x["opening_loser"] and x["opening_loser"] != side]
        converted = [x for x in taken if (x["ct_won"] if side == "ct" else not x["ct_won"])]
        opening[side] = {
            "lost": len(lost),
            "lost_rounds": [x["round_num"] for x in lost],
            "saved": len(won_anyway),
            "taken": len(taken),
            "taken_rounds": [x["round_num"] for x in taken],
            "converted": len(converted),
        }

    # --- buy types --------------------------------------------------------
    buys = {}
    for side in ("ct", "t"):
        agg = defaultdict(lambda: {"n": 0, "won": 0, "rounds": []})
        for x in rows:
            kind = x["buy_ct"] if side == "ct" else x["buy_t"]
            won = x["ct_won"] if side == "ct" else not x["ct_won"]
            agg[kind]["n"] += 1
            agg[kind]["won"] += int(won)
            agg[kind]["rounds"].append(x["round_num"])
        buys[side] = dict(agg)

    # ---- the same two tables, counted as a team rather than as a side
    #
    # Sides swap at the half, so a CT row spanning a whole match is this
    # team's first half and their opponent's second. Where the side is known
    # per round, both tables are rebuilt from the rounds that are actually
    # this team's; where it is not, they stay per side and the page says so.
    you_opening = you_buys = None
    if team_id is not None:
        sides = our_sides(team_id)
        mine = [(x, sides.get((match_key, x["round_num"]))) for x in rows]
        mine = [(x, sd) for x, sd in mine if sd in ("ct", "t")]
        if mine:
            def won(x, sd):
                return x["ct_won"] if sd == "ct" else not x["ct_won"]
            lost = [x for x, sd in mine if x["opening_loser"] == sd]
            took = [x for x, sd in mine
                    if x["opening_loser"] and x["opening_loser"] != sd]
            saved = [x for x, sd in mine
                     if x["opening_loser"] == sd and won(x, sd)]
            conv = [x for x, sd in mine
                    if x["opening_loser"] and x["opening_loser"] != sd
                    and won(x, sd)]
            you_opening = {
                "rounds": len(mine),
                "lost": len(lost), "lost_rounds": [x["round_num"] for x in lost],
                "saved": len(saved),
                "taken": len(took), "taken_rounds": [x["round_num"] for x in took],
                "converted": len(conv),
            }
            agg: dict = {}
            for x, sd in mine:
                kind = x["buy_ct"] if sd == "ct" else x["buy_t"]
                d = agg.setdefault(kind, {"n": 0, "won": 0, "rounds": []})
                d["n"] += 1
                d["won"] += int(won(x, sd))
                d["rounds"].append(x["round_num"])
            you_buys = agg

    return {
        "match": match,
        "rows": rows,
        "scoreboard": scoreboard(match_key, rows, team_id),
        "you_opening": you_opening,
        "you_buys": you_buys,
        "n_rounds": n,
        "score_ct": ct_wins,
        "score_t": n - ct_wins,
        "opening": opening,
        "buys": buys,
        "plants": sum(1 for x in rows if x["planted"]),
        "deaths": sum(x["deaths_ct"] + x["deaths_t"] for x in rows),
    }


def scoreboard(match_key: str, rows: list,
               team_id: int | None = None) -> list[dict]:
    """Both teams, players sorted by damage per round.

    Teams are identified by the side they started on, not by name: a demo
    carries no team identity, but players do not swap teams mid-match while
    sides swap every half. So "started CT" and "started T" are the two rosters,
    and each player's totals span both halves of their own match.
    """
    pr = db.query("""SELECT steamid, name, side, round_num, kills, deaths,
                            assists, headshots, damage, opening_kill,
                            opening_death, awp_kills, util_damage,
                            flashes_thrown, enemies_flashed, trade_kills,
                            traded_deaths, clutch_tried, clutch_won, multi_kills,
                            teammates_flashed, flash_assists, flash_kills,
                            nades_thrown, nades_start, nades_unused,
                            nades_value, nades_wasted
                       FROM player_rounds WHERE match_key = ?
                   ORDER BY round_num""", match_key)
    if not pr:
        return []

    first_round = min(r["round_num"] for r in pr)
    started: dict[str, str] = {}
    agg: dict[str, dict] = {}
    for r in pr:
        sid = r["steamid"]
        if r["round_num"] == first_round:
            started[sid] = r["side"]
        a = agg.setdefault(sid, {
            "steamid": sid, "name": r["name"], "rounds": 0, "kills": 0,
            "deaths": 0, "assists": 0, "headshots": 0, "damage": 0.0,
            "opening_kills": 0, "opening_deaths": 0, "awp_kills": 0,
            "trade_kills": 0, "traded_deaths": 0, "clutch_tried": 0,
            "clutch_won": 0, "multi_kills": 0, "util_damage": 0.0,
            "flashes_thrown": 0, "enemies_flashed": 0,
            "ct_rounds": 0, "t_rounds": 0, "util_damage": 0.0,
            "flashes_thrown": 0, "enemies_flashed": 0, "trade_kills": 0,
            "traded_deaths": 0, "clutch_tried": 0, "clutch_won": 0,
            "multi_kills": 0,
        })
        a["name"] = r["name"]
        a["rounds"] += 1
        a["ct_rounds" if r["side"] == "ct" else "t_rounds"] += 1
        a["kills"] += r["kills"]
        a["deaths"] += r["deaths"]
        a["assists"] += r["assists"]
        a["headshots"] += r["headshots"]
        a["damage"] += r["damage"]
        a["opening_kills"] += r["opening_kill"]
        a["opening_deaths"] += r["opening_death"]
        a["awp_kills"] += r["awp_kills"]
        for f in ("trade_kills", "traded_deaths", "clutch_tried",
                  "clutch_won", "multi_kills", "util_damage",
                  "flashes_thrown", "enemies_flashed"):
            a[f] = a.get(f, 0) + (r[f] or 0)
        for f in ("util_damage", "flashes_thrown", "enemies_flashed",
                  "trade_kills", "traded_deaths", "clutch_tried",
                  "clutch_won", "multi_kills"):
            a[f] += r[f] or 0
        for f in ("teammates_flashed", "flash_assists", "flash_kills",
                  "nades_thrown", "nades_start", "nades_unused",
                  "nades_value", "nades_wasted"):
            a[f] = a.get(f, 0) + (r[f] or 0)

    for a in agg.values():
        a["adr"] = a["damage"] / a["rounds"] if a["rounds"] else 0.0
        a["kd"] = a["kills"] / a["deaths"] if a["deaths"] else float(a["kills"])
        a["hs_pct"] = 100.0 * a["headshots"] / a["kills"] if a["kills"] else 0.0
        a["opens"] = a["opening_kills"] + a["opening_deaths"]
        a["util_adr"] = a["util_damage"] / a["rounds"] if a["rounds"] else 0.0
        # Enemies blinded PER FLASH, not a percentage: one flashbang can blind
        # three people, so this runs above 1.0 for a good flash and there is no
        # denominator that makes it a share.
        a["blind_per_flash"] = (a["enemies_flashed"] / a["flashes_thrown"]
                                if a["flashes_thrown"] else 0.0)
        # Traded share is out of DEATHS, not rounds: "when I die, does anyone
        # pick it up" is the question, and rounds a player survived are not
        # chances to be traded.
        a["traded_pct"] = (100.0 * a["traded_deaths"] / a["deaths"]
                           if a["deaths"] else 0.0)
        a["clutch_pct"] = (100.0 * a["clutch_won"] / a["clutch_tried"]
                           if a["clutch_tried"] else 0.0)
        # Utility. Own-side flashes are a share of flashes that LANDED, not
        # of flashes thrown: a flash that blinds nobody is a different mistake
        # from one that blinds your own entry, and averaging them hides both.
        landed = a["enemies_flashed"] + a["teammates_flashed"]
        a["flashes_landed"] = landed
        a["own_flash_pct"] = 100.0 * a["teammates_flashed"] / landed if landed else 0.0
        # Unused is out of grenades BOUGHT, and rounds with no inventory data
        # read zero bought, so they fall out of the denominator rather than
        # counting as a round where everything was thrown.
        a["unused_pct"] = (100.0 * a["nades_unused"] / a["nades_start"]
                           if a["nades_start"] else 0.0)
        # Dollars per round, which is the form a coach can weigh against a
        # rifle. A flashbang and a CT incendiary are both "one grenade" and one
        # is three times the other.
        a["wasted_per_round"] = (a["nades_wasted"] / a["rounds"]
                                 if a["rounds"] else 0.0)
        a["role"], a["role_why"] = role_of(a)

    agg = {sid: a for sid, a in agg.items() if not is_coach(a)}
    if not agg:
        return []

    # Which of the two rosters is the reader's. The side map says who was on
    # which side per round, so the roster that STARTED on our first-round side
    # is ours. Cheap to work out and the difference between a scoreboard and
    # your scoreboard.
    our_start = None
    if team_id is not None:
        sides = our_sides(team_id)
        our_start = sides.get((match_key, first_round))

    teams = []
    for side, label in (("ct", "Started CT"), ("t", "Started T")):
        members = [a for sid, a in agg.items() if started.get(sid) == side]
        if not members:
            continue
        if our_start:
            label = ("Your team" if side == our_start else "Opponents")
        # A team's round wins are the rounds their CURRENT side took, and their
        # side flips at half — so count from the round rows rather than assuming.
        teams.append({
            "side": side, "label": label,
            "players": sorted(members, key=lambda x: -x["adr"]),
        })
    # Anyone who joined after round one has no starting side. They still played,
    # so they go in their own group rather than vanishing from the scoreboard.
    late = [a for sid, a in agg.items() if sid not in started]
    if late:
        teams.append({"side": None, "label": "Joined after round 1",
                      "players": sorted(late, key=lambda x: -x["adr"])})
    # Yours first. A coach opening their own match report is looking for their
    # own five, and putting them second makes that a scroll every time.
    if our_start:
        teams.sort(key=lambda t: t["side"] != our_start)
    return teams


def count(hit: int, of: int) -> str:
    """A census, not a rate. For one match, where the denominator is everything.

    `rate` exists to answer "how often does this happen", and it prints a
    percentage off any denominator. That is right on a season page and wrong
    on a match report, where a team plays twenty-odd rounds and every split of
    them is small by construction: two pistol rounds, six forces, five rounds
    through apartments. A percentage off two rounds is 100% or 50% and says
    nothing either way.

    (`rate` used to refuse a percentage under MIN_CHANCES and print a "thin"
    pill instead. That went on 2026-09-24 for glance-ability. This function is
    where the same reasoning still lives, and it is where it mattered most.)

    Nothing about those numbers is unreliable. There WERE two CT pistol rounds
    and you DID win both. The denominator is not a sample of anything, it is
    the whole match. So a match prints the count and no percentage: 2 / 2 is
    the honest way to say it, and 100% is not.
    """
    if of == 0:
        return '<span class="rt nil"><b class="den">&ndash;</b></span>'
    return (f'<span class="rt tally"><b>{hit} / {of}</b></span>')


# A rate within this many points of its benchmark reads as "the same". Without
# a dead band every rounding wobble gets a colour and the page looks like it
# has an opinion about noise. Same reasoning as charts.NEUTRAL_BAND.
SAME_AS_BAND = 5.0


def pct(won: int, total: int) -> float | None:
    """The one place a percentage is worked out; None for no chances.

    `rate()` prints through this, and so does every figure that draws a
    percentage as a bar, so a chart and the table beside it cannot disagree.
    """
    if not total:
        return None
    return 100.0 * won / total


def rate(won: int, total: int, against: float | None = None) -> str:
    """A percentage, with its denominator one hover away.

    Every percentage in the product comes through here, so what is decided
    here is decided everywhere: the recurring patterns, the map pool, the
    scoreboard, both player tables and the positional tables.

    THE DENOMINATOR IS IN THE TITLE, NOT UNDER THE FIGURE. It used to print
    on a second line under every rate, and a table of them was twice as tall
    for a number most readers take on trust. It is still on every figure and
    still one hover away.

    THERE IS NO LONGER A THIN VARIANT. This used to refuse a percentage under
    MIN_CHANCES and print "5 / 7" with a "thin" pill, on the argument that a
    rate off seven chances overstates itself and a bar drawn at 71% overstates
    it further. That argument has not gone away; it lost to glance-ability on
    the owner's call. MIN_CHANCES still governs `count()` and the advice
    thresholds, which is where it does the most work.

    A zero denominator still draws a dash rather than 0%, because no chances
    is not the same as never.
    """
    if total == 0:
        return '<span class="rt nil"><b class="den">&ndash;</b></span>'
    pct_ = pct(won, total)
    # `against` is what this rate should be read next to, and it is ALWAYS
    # something this team did: the same map and side without the habit, or
    # their own season. Never a league figure and never a professional one.
    # A number with no comparison is why a coach glances at a table and does
    # not read it, and this is the one place every percentage passes through.
    cmp_cls = ""
    if against is not None:
        d = pct_ - against
        cmp_cls = " up" if d >= SAME_AS_BAND else (" down" if d <= -SAME_AS_BAND else "")
    return (f'<span class="rt{cmp_cls}" style="--f:{pct_:.0f}%" '
            f'title="{won} of {total}"><b>{pct_:.0f}%</b></span>')


@memo.by_team
def team_players(team_id: int, ours_only: bool | None = None) -> list[dict]:
    """Every player across every match this team has uploaded.

    Season totals, not one match. This is the thing a single demo structurally
    cannot tell a coach: whether a bad opening-duel record is one rough night
    or a habit. Side splits are kept apart because a player who is 90 ADR as CT
    and 60 as T has a specific problem, and an averaged 75 hides it.

    `ours_only` picks which rounds count: True for the rounds a player spent on
    this team's side, False for the rounds they spent against it, None for all
    of them. It matters for exactly one kind of player and it matters a lot for
    them -- the stand-in who turns out for you one week and for the opposition
    the next, whose totals would otherwise be both at once.
    """
    rows = db.query("""
        SELECT pr.steamid, pr.name, pr.side, pr.kills, pr.deaths, pr.assists,
               pr.headshots, pr.damage, pr.opening_kill, pr.opening_death,
               pr.awp_kills, pr.match_key, pr.util_damage, pr.flashes_thrown,
               pr.enemies_flashed, pr.trade_kills, pr.traded_deaths,
               pr.clutch_tried, pr.clutch_won, pr.multi_kills,
               pr.teammates_flashed, pr.flash_assists, pr.flash_kills,
               pr.nades_thrown, pr.nades_start, pr.nades_unused,
               pr.nades_value, pr.nades_wasted, pr.round_num
          FROM player_rounds pr
          JOIN matches m  ON m.match_key = pr.match_key
          JOIN demos   d  ON d.id = m.demo_id
         WHERE d.team_id = ?""", team_id)
    if not rows:
        return []

    # Coaches out, judged on every round they were in before `ours_only`
    # narrows anything. Without this the season roster listed the coach as
    # a Rifle on 0 ADR, which team_stats() had stopped doing a long time ago.
    whole: dict = defaultdict(lambda: {"kills": 0, "deaths": 0, "damage": 0.0})
    for r in rows:
        t = whole[r["steamid"]]
        t["kills"] += r["kills"]
        t["deaths"] += r["deaths"]
        t["damage"] += r["damage"]
    coaches = {sid for sid, t in whole.items() if is_coach(t)}

    keep = None
    if ours_only is not None:
        mine = ours_by_round(team_id)
        keep = (lambda r: (r["match_key"], r["round_num"], r["steamid"]) in mine)
        if not ours_only:
            inner = keep
            keep = (lambda r: not inner(r))

    agg: dict[str, dict] = {}
    for r in rows:
        if r["steamid"] in coaches or (keep and not keep(r)):
            continue
        a = agg.setdefault(r["steamid"], {
            "steamid": r["steamid"], "name": r["name"], "rounds": 0, "kills": 0,
            "deaths": 0, "assists": 0, "headshots": 0, "damage": 0.0,
            "opening_kills": 0, "opening_deaths": 0, "awp_kills": 0,
            "trade_kills": 0, "traded_deaths": 0, "clutch_tried": 0,
            "clutch_won": 0, "multi_kills": 0, "util_damage": 0.0,
            "flashes_thrown": 0, "enemies_flashed": 0,
            "ct_rounds": 0, "ct_damage": 0.0, "t_rounds": 0, "t_damage": 0.0,
            "util_damage": 0.0, "flashes_thrown": 0, "enemies_flashed": 0,
            "trade_kills": 0, "traded_deaths": 0, "clutch_tried": 0,
            "clutch_won": 0, "multi_kills": 0,
            "matches": set(),
        })
        a["name"] = r["name"]
        a["matches"].add(r["match_key"])
        a["rounds"] += 1
        a["kills"] += r["kills"]
        a["deaths"] += r["deaths"]
        a["assists"] += r["assists"]
        a["headshots"] += r["headshots"]
        a["damage"] += r["damage"]
        a["opening_kills"] += r["opening_kill"]
        a["opening_deaths"] += r["opening_death"]
        a["awp_kills"] += r["awp_kills"]
        for f in ("trade_kills", "traded_deaths", "clutch_tried",
                  "clutch_won", "multi_kills", "util_damage",
                  "flashes_thrown", "enemies_flashed"):
            a[f] = a.get(f, 0) + (r[f] or 0)
        for f in ("util_damage", "flashes_thrown", "enemies_flashed",
                  "trade_kills", "traded_deaths", "clutch_tried",
                  "clutch_won", "multi_kills"):
            a[f] += r[f] or 0
        for f in ("teammates_flashed", "flash_assists", "flash_kills",
                  "nades_thrown", "nades_start", "nades_unused",
                  "nades_value", "nades_wasted"):
            a[f] = a.get(f, 0) + (r[f] or 0)
        if r["side"] == "ct":
            a["ct_rounds"] += 1
            a["ct_damage"] += r["damage"]
        else:
            a["t_rounds"] += 1
            a["t_damage"] += r["damage"]

    out = []
    for a in agg.values():
        a["matches"] = len(a["matches"])
        a["adr"] = a["damage"] / a["rounds"] if a["rounds"] else 0.0
        a["ct_adr"] = a["ct_damage"] / a["ct_rounds"] if a["ct_rounds"] else 0.0
        a["t_adr"] = a["t_damage"] / a["t_rounds"] if a["t_rounds"] else 0.0
        a["kd"] = a["kills"] / a["deaths"] if a["deaths"] else float(a["kills"])
        a["hs_pct"] = 100.0 * a["headshots"] / a["kills"] if a["kills"] else 0.0
        a["opens"] = a["opening_kills"] + a["opening_deaths"]
        a["open_pct"] = 100.0 * a["opening_kills"] / a["opens"] if a["opens"] else 0.0
        a["util_adr"] = a["util_damage"] / a["rounds"] if a["rounds"] else 0.0
        # Enemies blinded PER FLASH, not a percentage: one flashbang can blind
        # three people, so this runs above 1.0 for a good flash and there is no
        # denominator that makes it a share.
        a["blind_per_flash"] = (a["enemies_flashed"] / a["flashes_thrown"]
                                if a["flashes_thrown"] else 0.0)
        # Traded share is out of DEATHS, not rounds: "when I die, does anyone
        # pick it up" is the question, and rounds a player survived are not
        # chances to be traded.
        a["traded_pct"] = (100.0 * a["traded_deaths"] / a["deaths"]
                           if a["deaths"] else 0.0)
        a["clutch_pct"] = (100.0 * a["clutch_won"] / a["clutch_tried"]
                           if a["clutch_tried"] else 0.0)
        # Utility. Own-side flashes are a share of flashes that LANDED, not
        # of flashes thrown: a flash that blinds nobody is a different mistake
        # from one that blinds your own entry, and averaging them hides both.
        landed = a["enemies_flashed"] + a["teammates_flashed"]
        a["flashes_landed"] = landed
        a["own_flash_pct"] = 100.0 * a["teammates_flashed"] / landed if landed else 0.0
        # Unused is out of grenades BOUGHT, and rounds with no inventory data
        # read zero bought, so they fall out of the denominator rather than
        # counting as a round where everything was thrown.
        a["unused_pct"] = (100.0 * a["nades_unused"] / a["nades_start"]
                           if a["nades_start"] else 0.0)
        # Dollars per round, which is the form a coach can weigh against a
        # rifle. A flashbang and a CT incendiary are both "one grenade" and one
        # is three times the other.
        a["wasted_per_round"] = (a["nades_wasted"] / a["rounds"]
                                 if a["rounds"] else 0.0)
        a["role"], a["role_why"] = role_of(a)
        # A rate off a handful of rounds is noise wearing a percent sign.
        a["thin"] = a["rounds"] < MIN_ROUNDS_FOR_ROLE
        out.append(a)
    # Most matches first, then most rounds, then damage. Sorting by ADR alone
    # buried the people who actually turn up behind opponents who played once
    # and had a good game — the players a coach cares about are the ones who
    # keep appearing, and they belong at the top.
    return sorted(out, key=lambda x: (-x["matches"], -x["rounds"], -x["adr"]))


def team_matches(team_id: int) -> list[dict]:
    """Every match this team has sent in, newest first, as a coach would name it.

    The demo list used to print the filename Valve gave the file
    (`003838914553828081689_1191066329.dem`) and nothing else, so eleven rows
    were eleven indistinguishable strings. Everything needed to name a match —
    map, score, result, how many rounds — was already in the database.
    """
    anchors = team_anchors(team_id).get("anchors", {})
    sides = _side_by_round(team_id, anchors)
    rows = db.query("""SELECT d.id AS demo_id, d.filename, d.status, d.status_note,
                              d.size_bytes, d.created_at, d.tier,
                              m.match_key, m.map_name, m.rounds, m.final_ct,
                              m.final_t, m.finished, m.end_reason, m.ingested_at
                         FROM demos d
                    LEFT JOIN matches m ON m.demo_id = d.id
                        WHERE d.team_id = ?
                     ORDER BY d.filename DESC""", team_id)
    out = []
    for r in rows:
        item = {"demo_id": r["demo_id"], "filename": r["filename"],
                "status": r["status"], "note": r["status_note"],
                "size_mb": (r["size_bytes"] or 0) / (1024 * 1024),
                "uploaded": (r["created_at"] or "")[:10],
                "match_key": r["match_key"], "tier": r["tier"],
                "map": (r["map_name"] or "").replace("de_", ""),
                "rounds": r["rounds"], "finished": r["finished"],
                "end_reason": r["end_reason"],
                "us": None, "them": None, "result": None}
        if r["match_key"] and r["final_ct"] is not None:
            first = db.one("SELECT MIN(round_num) n FROM rounds WHERE match_key = ?",
                           r["match_key"])
            started = sides.get((r["match_key"], first["n"] if first else 1))
            if started:
                item["us"] = r["final_ct"] if started == "ct" else r["final_t"]
                item["them"] = r["final_t"] if started == "ct" else r["final_ct"]
                item["result"] = ("W" if item["us"] > item["them"] else
                                  "L" if item["us"] < item["them"] else "T")
            else:
                item["us"], item["them"] = r["final_ct"], r["final_t"]
        out.append(item)
    return out


def team_coaches(team_id: int) -> list[dict]:
    """The coaches who sat on this team's side: [{steamid, name, matches}].

    A coach is kept out of every stat (is_coach), because their numbers are
    artifacts of standing still in a player slot. They still belong on the
    roster, named as a coach, so the page shows the whole team.
    """
    rows = db.query("""
        SELECT pr.steamid, pr.name, pr.match_key, pr.round_num,
               pr.kills, pr.deaths, pr.damage
          FROM player_rounds pr
          JOIN matches m ON m.match_key = pr.match_key
          JOIN demos   d ON d.id = m.demo_id
         WHERE d.team_id = ?""", team_id)
    whole: dict = defaultdict(lambda: {"kills": 0, "deaths": 0, "damage": 0.0})
    for r in rows:
        t = whole[r["steamid"]]
        t["kills"] += r["kills"]
        t["deaths"] += r["deaths"]
        t["damage"] += r["damage"]
    coaches = {sid for sid, t in whole.items() if is_coach(t)}
    if not coaches:
        return []
    ours = ours_by_round(team_id)
    out: dict = {}
    for r in rows:
        if (r["steamid"] in coaches and
                (r["match_key"], r["round_num"], r["steamid"]) in ours):
            c = out.setdefault(r["steamid"], {"steamid": r["steamid"],
                                              "name": r["name"], "keys": set()})
            c["name"] = r["name"]
            c["keys"].add(r["match_key"])
    return sorted(({"steamid": c["steamid"], "name": c["name"],
                    "matches": len(c["keys"])} for c in out.values()),
                  key=lambda c: -c["matches"])


def squad(team_id: int) -> dict:
    """Split the people in a team's demos into theirs and everyone else's.

    A team page that lists ninety-seven players is not a team page. Uploading
    eleven matches puts every opponent in the database too, and sorting the lot
    by ADR ranks a coach's own players below strangers who had one good night.

    The split needs no roster upload and no Steam IDs typed in at signup: a
    team plays all of its own matches and each opponent plays one, so the
    players who keep coming back ARE the team. Same reasoning as
    `team_anchors`, applied to the whole list rather than to one anchor.

    Returns {"yours": [...], "others": [...], "confident": bool}.
    """
    people = team_players(team_id)
    if not people:
        return {"yours": [], "others": [], "confident": False}

    n_matches = max((a["matches"] for a in people), default=0)
    if n_matches < 2:
        # One match: every player appears in all of it, so there is nothing to
        # infer a side from yet. Better to say so than to split on nothing.
        return {"yours": [], "others": people, "confident": False}

    # WHICH SIDE THEY STOOD ON. Not how often they turn up.
    #
    # The old test was "appears in more than one of your matches", which on a
    # league roster is right and on a solo-queue season quietly drops the four
    # people who played with you last night. Once the side is known per round
    # the question needs no heuristic at all: a player is yours if most of
    # their rounds were on your side, which also gets the stand-in who turned
    # out for the other team the one night.
    #
    # And the row a player gets is built from those rounds alone: a stand-in
    # filed under your roster carries the rounds they played FOR you, not an
    # average of both weeks.
    ours = ours_by_round(team_id)
    if not ours:
        return {"yours": [], "others": people, "confident": False}
    mine = {}
    for _mk, _rn, sid in ours:
        mine[sid] = mine.get(sid, 0) + 1
    for_us = {a["steamid"]: a for a in team_players(team_id, ours_only=True)}
    against = {a["steamid"]: a for a in team_players(team_id, ours_only=False)}
    yours = [for_us[a["steamid"]] for a in people
             if mine.get(a["steamid"], 0) * 2 > a["rounds"]
             and a["steamid"] in for_us]
    others = [against[a["steamid"]] for a in people
              if mine.get(a["steamid"], 0) * 2 <= a["rounds"]
              and a["steamid"] in against]
    # Regulars first: the five who keep coming back are the roster a coach is
    # looking for, and the one-night stand-in is still theirs but is not it.
    yours.sort(key=lambda a: (-a["matches"], -a["rounds"]))
    return {"yours": yours, "others": others, "confident": bool(yours)}


def recent_form(team_id: int, limit: int = 5) -> list[dict]:
    """The last few matches, most recent first, with the real result.

    Recent form is the one thing a season total cannot show: whether the thing
    a team fixed in practice actually held. Kept short on purpose — five is
    what a coach looks at.
    """
    anchors = team_anchors(team_id).get("anchors", {})
    sides = _side_by_round(team_id, anchors)
    rows = db.query("""SELECT m.match_key, m.map_name, m.ingested_at, m.rounds,
                              m.final_ct, m.final_t, m.finished, m.end_reason,
                              d.filename
                         FROM matches m JOIN demos d ON d.id = m.demo_id
                        WHERE d.team_id = ?
                     ORDER BY m.ingested_at DESC, d.filename DESC LIMIT ?""",
                    team_id, limit)
    out = []
    for m in rows:
        first = db.one("SELECT MIN(round_num) n FROM rounds WHERE match_key = ?",
                       m["match_key"])
        started = sides.get((m["match_key"], first["n"] if first else 1))
        us = them = None
        if started and m["final_ct"] is not None:
            us = m["final_ct"] if started == "ct" else m["final_t"]
            them = m["final_t"] if started == "ct" else m["final_ct"]
        out.append({
            "match_key": m["match_key"],
            "map": (m["map_name"] or "").replace("de_", ""),
            "uploaded": (m["ingested_at"] or "")[:10],
            "rounds": m["rounds"], "us": us, "them": them,
            "finished": m["finished"], "end_reason": m["end_reason"],
            "result": None if us is None else ("W" if us > them else
                                               "L" if us < them else "T"),
        })
    return out


def match_score(match_key: str, team_id: int | None = None) -> dict:
    """One match's real score, and which half of it is this team's.

    `score_ct`/`score_t` on the matches row are rounds won by side summed over
    the match, which is not a score — sides swap, so neither number belongs to
    a team. `final_ct`/`final_t` are the actual team totals, with final_ct
    belonging to whoever started on CT.
    """
    m = db.one("""SELECT map_name, rounds, score_ct, score_t, final_ct, final_t,
                         finished, end_reason, ingested_at, tier, competition
                    FROM matches WHERE match_key = ?""", match_key)
    if m is None:
        return {}
    out = {"map": (m["map_name"] or "").replace("de_", ""),
           "rounds": m["rounds"], "a": m["final_ct"], "b": m["final_t"],
           "finished": m["finished"], "end_reason": m["end_reason"],
           "added": (m["ingested_at"] or "")[:10],
           "by_side_ct": m["score_ct"], "by_side_t": m["score_t"],
           "us": None, "them": None, "result": None}
    if team_id is None or m["final_ct"] is None:
        return out
    anchors = team_anchors(team_id).get("anchors", {})
    sides = _side_by_round(team_id, anchors)
    first = db.one("SELECT MIN(round_num) n FROM rounds WHERE match_key = ?", match_key)
    started = sides.get((match_key, first["n"] if first else 1))
    if started:
        out["us"] = m["final_ct"] if started == "ct" else m["final_t"]
        out["them"] = m["final_t"] if started == "ct" else m["final_ct"]
        out["result"] = ("W" if out["us"] > out["them"] else
                         "L" if out["us"] < out["them"] else "T")
    return out


# A pattern seen fewer times than this is an anecdote. The landing page promises
# "counted across every match, not eyeballed from one", and this is where that
# promise is kept or broken.
MIN_PATTERN_CHANCES = 6

# One line per buy type, because they are four different questions. This used
# to be one template with "Full buys" hardcoded into it, so the eco, force and
# pistol lines all ended by warning about full buys.
BUY_ARTICLE = {"eco": "an", "force": "a", "full": "a", "pistol": "a"}
BUY_BLURB = {
    "full": "The round you are most expected to win.",
    "force": "Winning some is the point. Winning none means the force buys "
             "nothing.",
    "eco": "Meant to be lost cheaply. A win is a bonus.",
    "pistol": "Each pistol also sets up the two rounds after it.",
}
DEFAULT_BUY_BLURB = "How often this buy turns into a round."

# The four fixed patterns, named once. They are printed on the team stats page
# and again on the sample report, and while each lived as a literal at its one
# call site the preview drifted: the sample was still showing a shape the
# product had stopped using. A name in one place is the cheapest way to stop
# that happening twice.
PATTERNS = {
    "opening_won": (
        "You win the round after winning the opening duel",
        "How often you convert the first kill."),
    "opening_lost": (
        "You win the round after losing the opening duel",
        "Playing a player down. Low here points at trades and retakes."),
    "ct": ("You win the round as CT",
           "Your record on the defending side, across every map."),
    "t": ("You win the round as T",
          "Your record on the attacking side, across every map."),
}


def buy_pattern(kind: str) -> tuple[str, str]:
    """The name and the explanation for one buy type."""
    return (f"You win {BUY_ARTICLE.get(kind, 'a')} {kind} round",
            BUY_BLURB.get(kind, DEFAULT_BUY_BLURB))


def _team_match_keys(team_id: int) -> list[str]:
    return [r["match_key"] for r in db.query(
        """SELECT m.match_key FROM matches m JOIN demos d ON d.id = m.demo_id
            WHERE d.team_id = ? ORDER BY m.ingested_at""", team_id)]


@memo.by_team
def team_stats(team_id: int) -> dict | None:
    """Season aggregates across every match this team has sent in.

    Everything is reported BY SIDE rather than by team. A demo carries no team
    identity — only which side each player was on, and sides swap at half — so
    "CT" here means the CT side of your matches, not your opponents. Saying
    which of the two is yours needs the roster linked to Steam IDs, which is
    not built; claiming it without that link would be a guess printed as a fact.
    """
    keys = _team_match_keys(team_id)
    if not keys:
        return None
    marks = ",".join("?" * len(keys))
    anchor_info = team_anchors(team_id)
    ours = _side_by_round(team_id, anchor_info["anchors"])

    rounds = db.query(f"""SELECT * FROM rounds WHERE match_key IN ({marks})
                       ORDER BY match_key, round_num""", *keys)
    events = db.query(f"""SELECT * FROM events WHERE match_key IN ({marks})
                       ORDER BY match_key, round_num, seconds""", *keys)
    if not rounds:
        return None

    by_round = defaultdict(list)
    for e in events:
        by_round[(e["match_key"], e["round_num"])].append(e)

    # --- map pool ---------------------------------------------------------
    maps = defaultdict(lambda: {"rounds": 0, "ct_won": 0, "t_won": 0,
                                "matches": set(), "plants": 0, "t_rounds": 0,
                                "you_won": 0, "you_played": 0,
                                "you_ct": 0, "you_ct_won": 0,
                                "you_t": 0, "you_t_won": 0})
    you = {"rounds": 0, "won": 0,
           "ct": {"rounds": 0, "won": 0}, "t": {"rounds": 0, "won": 0},
           "opening_took": 0, "opening_converted": 0,
           "opening_lost": 0, "opening_saved": 0}
    you_buys = defaultdict(lambda: {"n": 0, "won": 0})
    sides = {"ct": {"rounds": 0, "won": 0}, "t": {"rounds": 0, "won": 0}}
    opening = {"ct": {"took": 0, "converted": 0, "lost": 0, "saved": 0},
               "t": {"took": 0, "converted": 0, "lost": 0, "saved": 0}}
    buys = defaultdict(lambda: {"n": 0, "won": 0})
    plants = 0

    prev = {}          # match_key -> (round_num, ct_won) of the previous round
    after_loss = {"ct": {"eco": 0, "force": 0, "full": 0, "pistol": 0},
                  "t": {"eco": 0, "force": 0, "full": 0, "pistol": 0}}
    pistol_followups = {"ct": {"n": 0, "force": 0}, "t": {"n": 0, "force": 0}}

    for r in rounds:
        key, rn = r["match_key"], r["round_num"]
        m = maps[r["map_name"]]
        m["rounds"] += 1
        m["matches"].add(key)
        ct_won = bool(r["ct_won"])
        m["ct_won" if ct_won else "t_won"] += 1

        for side in ("ct", "t"):
            won = ct_won if side == "ct" else not ct_won
            sides[side]["rounds"] += 1
            sides[side]["won"] += int(won)
            kind = classify_round(r["equip_ct"] if side == "ct" else r["equip_t"], rn)
            buys[(side, kind)]["n"] += 1
            buys[(side, kind)]["won"] += int(won)

        # --- the same round, from this team's point of view -----------------
        my_side = ours.get((key, rn))
        if my_side:
            i_won = ct_won if my_side == "ct" else not ct_won
            you["rounds"] += 1
            you["won"] += int(i_won)
            you[my_side]["rounds"] += 1
            you[my_side]["won"] += int(i_won)
            m["you_played"] += 1
            m["you_won"] += int(i_won)
            m["you_ct" if my_side == "ct" else "you_t"] += 1
            if i_won:
                m["you_ct_won" if my_side == "ct" else "you_t_won"] += 1
            kind = classify_round(
                r["equip_ct"] if my_side == "ct" else r["equip_t"], rn)
            you_buys[kind]["n"] += 1
            you_buys[kind]["won"] += int(i_won)

        evs = by_round.get((key, rn), [])
        deaths = [e for e in evs if e["type"] == "death"]
        if any(e["type"] == "plant" for e in evs):
            plants += 1
            m["plants"] += 1
        if deaths:
            first = deaths[0]
            loser = first["victim_side"]
            winner = "t" if loser == "ct" else "ct"
            if loser in opening:
                opening[loser]["lost"] += 1
                if (ct_won if loser == "ct" else not ct_won):
                    opening[loser]["saved"] += 1
            if winner in opening:
                opening[winner]["took"] += 1
                if (ct_won if winner == "ct" else not ct_won):
                    opening[winner]["converted"] += 1
            if my_side:
                i_won = ct_won if my_side == "ct" else not ct_won
                if winner == my_side:
                    you["opening_took"] += 1
                    you["opening_converted"] += int(i_won)
                else:
                    you["opening_lost"] += 1
                    you["opening_saved"] += int(i_won)

        # --- what each side buys after losing the round before --------------
        last = prev.get(key)
        if last is not None and last[0] == rn - 1:
            for side in ("ct", "t"):
                lost_previous = (not last[1]) if side == "ct" else last[1]
                if not lost_previous:
                    continue
                kind = classify_round(r["equip_ct"] if side == "ct" else r["equip_t"], rn)
                after_loss[side][kind] += 1
                # The round straight after a pistol round is the one every
                # coach argues about, so it gets counted on its own.
                if rn in (2, 14):
                    pistol_followups[side]["n"] += 1
                    if kind in ("force", "full"):
                        pistol_followups[side]["force"] += 1
        prev[key] = (rn, ct_won)

    for v in maps.values():
        v["matches"] = len(v["matches"])

    return {
        "matches": len(keys), "rounds": len(rounds),
        "maps": dict(sorted(maps.items(), key=lambda kv: -kv[1]["rounds"])),
        "sides": sides, "opening": opening,
        "buys": {k: v for k, v in sorted(buys.items())},
        "plants": plants,
        "after_loss": after_loss, "pistol_followups": pistol_followups,
        "you": you, "you_buys": dict(you_buys),
        "anchors": anchor_info,
    }


@memo.by_team
def recurring_patterns(team_id: int) -> list[dict]:
    """Things that happen over and over across a team's matches.

    Counted, never modeled. Each pattern is a thing that happened in a stated
    number of rounds out of a stated number of chances — no estimate anywhere,
    so there is nothing here to be wrong about. Anything under
    MIN_PATTERN_CHANCES is dropped rather than shown as a percentage of five.
    """
    st = team_stats(team_id)
    if st is None:
        return []

    out = []

    def add(name, hit, of, detail, side=None):
        if of >= MIN_PATTERN_CHANCES:
            out.append({"name": name, "hit": hit, "of": of, "pct": 100.0 * hit / of,
                        "detail": detail, "side": side})

    # When the roster is known, the patterns that matter are about THIS TEAM,
    # not about the CT and T sides of their matches. Fall through to the
    # side-based version only when there is nothing to infer a roster from.
    y = st["you"]
    if st["anchors"]["confident"] and y["rounds"]:
        for key, (hit, of) in (
                ("opening_won", (y["opening_converted"], y["opening_took"])),
                ("opening_lost", (y["opening_saved"], y["opening_lost"])),
                ("ct", (y["ct"]["won"], y["ct"]["rounds"])),
                ("t", (y["t"]["won"], y["t"]["rounds"]))):
            name, detail = PATTERNS[key]
            add(name, hit, of, detail)
        for kind, v in sorted(st["you_buys"].items()):
            name, detail = buy_pattern(kind)
            add(name, v["won"], v["n"], detail)
        # Utility, in the same shape and the same column as everything else.
        # Imported here rather than at the top: `app.utility` reads this
        # module's roster helpers, so the dependency only runs one way.
        from . import utility as _utility
        for name, hit, of, detail in _utility.round_patterns(team_id):
            add(name, hit, of, detail)
        return sorted(out, key=lambda x: -x["of"])

    for side in ("ct", "t"):
        o = st["opening"][side]
        add(f"Wins the round after winning the opening duel",
            o["converted"], o["took"],
            "The first kill of the round is the cheapest advantage there is. "
            "How often it is converted says more about a team than its aim does.",
            side)
        add(f"Wins the round after losing the opening duel",
            o["saved"], o["lost"],
            "Recovering a round down a player. Low here and the problem is "
            "retakes and trades, not the opening duel itself.", side)

        f = st["pistol_followups"][side]
        add("Buys after losing the pistol round",
            f["force"], f["n"],
            "Force or full buy rather than saving, in the round straight after "
            "a lost pistol. The most predictable decision an amateur team makes, "
            "and the cheapest one to punish.", side)

        al = st["after_loss"][side]
        total_after_loss = sum(al.values())
        add("Full saves after losing a round", al["eco"], total_after_loss,
            "Eco discipline. High means the economy is being managed; low means "
            "rounds are being bought into and lost twice.", side)

    t_rounds = st["sides"]["t"]["rounds"]
    add("Bomb planted on a T-side round", st["plants"], t_rounds,
        "Plant rate. Low means T rounds are ending in duels rather than in "
        "executes.")

    return sorted(out, key=lambda x: -x["of"])


def player_matches(team_id: int, steamid: str) -> dict | None:
    """One player, match by match, across everything this team has uploaded.

    Season totals hide the thing a coach most wants to see: whether a number is
    a level or an average of two very different nights. 94 ADR is a different
    conversation if it is 94 every week than if it is 140 and 50.
    """
    # Joined to `rounds` so each row knows whether THIS PLAYER won that round.
    #
    # An earlier version guessed the result from the match score and whichever
    # side the player spent more rounds on. That is wrong twice over.
    #
    # First, the split is nothing like even. Sides swap after round 12 and the
    # match is first to 13, so a shutout ends 12-0 at the swap having played a
    # single side the whole way; a match that ends early is lopsided for the
    # same reason. One match in this corpus is 6 rounds, all T, no CT at all,
    # and another is 16 rounds split 12 CT / 4 T. Overtime swaps again every
    # three rounds on top of that — the 28-round matches here swap after 12 and
    # again after 27. Across the corpus, 574 of 1,211 player-matches are not a
    # half-and-half split.
    #
    # Second, and worse: the split cannot identify a team even when it is
    # lopsided, because BOTH teams swap at the same moment. If a player was CT
    # for 12 of 16 rounds then every opponent was T for those same 12. The
    # proportion describes when the match ended, not who anyone played for.
    #
    # So the result is counted round by round from the side the player was
    # actually on, which needs no assumption about balance at all.
    rows = db.query("""
        SELECT pr.match_key, pr.round_num, pr.side, pr.kills, pr.deaths,
               pr.assists, pr.headshots, pr.damage, pr.opening_kill,
               pr.opening_death, pr.awp_kills, pr.trade_kills, pr.traded_deaths,
               pr.clutch_tried, pr.clutch_won, pr.multi_kills, pr.util_damage,
               pr.flashes_thrown, pr.enemies_flashed,
               pr.teammates_flashed, pr.flash_assists, pr.flash_kills,
               pr.nades_thrown, pr.nades_start, pr.nades_unused,
               pr.nades_value, pr.nades_wasted, r.ct_won,
               m.map_name, m.ingested_at, m.rounds AS match_rounds
          FROM player_rounds pr
          JOIN rounds  r ON r.match_key = pr.match_key
                        AND r.round_num = pr.round_num
          JOIN matches m ON m.match_key = pr.match_key
          JOIN demos   d ON d.id = m.demo_id
         WHERE d.team_id = ? AND pr.steamid = ?
      ORDER BY m.ingested_at, pr.match_key, pr.round_num""", team_id, steamid)
    if not rows:
        return None

    per: dict[str, dict] = {}
    name = ""
    for r in rows:
        m = per.setdefault(r["match_key"], {
            "match_key": r["match_key"], "map_name": r["map_name"],
            "added": r["ingested_at"], "match_rounds": r["match_rounds"],
            "rounds": 0, "won_rounds": 0, "kills": 0, "deaths": 0, "assists": 0, "headshots": 0,
            "damage": 0.0, "opening_kills": 0, "opening_deaths": 0,
            "awp_kills": 0, "ct_rounds": 0, "t_rounds": 0,
            "trade_kills": 0, "traded_deaths": 0, "clutch_tried": 0,
            "clutch_won": 0, "multi_kills": 0, "util_damage": 0.0,
            "flashes_thrown": 0, "enemies_flashed": 0,
            "teammates_flashed": 0, "flash_assists": 0, "flash_kills": 0,
            "nades_thrown": 0, "nades_start": 0, "nades_unused": 0,
            "nades_value": 0, "nades_wasted": 0,
        })
        m["rounds"] += 1
        m["ct_rounds" if r["side"] == "ct" else "t_rounds"] += 1
        # Won from this player's own side, round by round.
        if bool(r["ct_won"]) == (r["side"] == "ct"):
            m["won_rounds"] += 1
        m["kills"] += r["kills"]
        m["deaths"] += r["deaths"]
        m["assists"] += r["assists"]
        m["headshots"] += r["headshots"]
        m["damage"] += r["damage"]
        m["opening_kills"] += r["opening_kill"]
        m["opening_deaths"] += r["opening_death"]
        m["awp_kills"] += r["awp_kills"]
        for f in ("trade_kills", "traded_deaths", "clutch_tried", "clutch_won",
                  "multi_kills", "util_damage", "flashes_thrown",
                  "enemies_flashed", "teammates_flashed", "flash_assists",
                  "flash_kills", "nades_thrown", "nades_start",
                  "nades_unused", "nades_value", "nades_wasted"):
            m[f] += r[f] or 0

    # Which side was this player on for most of each match, so the row can say
    # whether they won it — the demo records sides, not teams.
    for m in per.values():
        m["adr"] = m["damage"] / m["rounds"] if m["rounds"] else 0.0
        m["kd"] = m["kills"] / m["deaths"] if m["deaths"] else float(m["kills"])
        m["hs_pct"] = 100.0 * m["headshots"] / m["kills"] if m["kills"] else 0.0
        m["util_adr"] = m["util_damage"] / m["rounds"] if m["rounds"] else 0.0
        m["blind_per_flash"] = (m["enemies_flashed"] / m["flashes_thrown"]
                                if m["flashes_thrown"] else 0.0)
        landed = m["enemies_flashed"] + m["teammates_flashed"]
        m["flashes_landed"] = landed
        m["own_flash_pct"] = 100.0 * m["teammates_flashed"] / landed if landed else 0.0
        m["unused_pct"] = (100.0 * m["nades_unused"] / m["nades_start"]
                           if m["nades_start"] else 0.0)
        m["wasted_per_round"] = (m["nades_wasted"] / m["rounds"]
                                 if m["rounds"] else 0.0)
        m["opens"] = m["opening_kills"] + m["opening_deaths"]
        lost = m["match_rounds"] - m["won_rounds"]
        m["result"] = ("won" if m["won_rounds"] > lost
                       else "lost" if lost > m["won_rounds"] else "drew")
        # Written from this player's side, so it reads the way they remember it.
        m["score"] = f'{m["won_rounds"]}\u2013{lost}'

    name = db.one("""SELECT name FROM player_rounds WHERE steamid = ?
                  ORDER BY rowid DESC LIMIT 1""", steamid)
    matches = sorted(per.values(), key=lambda x: (x["added"] or "", x["match_key"]))

    tot = {k: sum(m[k] for m in matches) for k in
           ("rounds", "kills", "deaths", "assists", "headshots",
            "opening_kills", "opening_deaths", "awp_kills",
            "flashes_thrown", "enemies_flashed", "teammates_flashed",
            "flash_assists", "flash_kills",
            "nades_thrown", "nades_start", "nades_unused",
                  "nades_value", "nades_wasted")}
    tot["damage"] = sum(m["damage"] for m in matches)
    tot["adr"] = tot["damage"] / tot["rounds"] if tot["rounds"] else 0.0
    tot["kd"] = tot["kills"] / tot["deaths"] if tot["deaths"] else float(tot["kills"])
    tot["hs_pct"] = 100.0 * tot["headshots"] / tot["kills"] if tot["kills"] else 0.0
    tot["opens"] = tot["opening_kills"] + tot["opening_deaths"]
    landed = tot["enemies_flashed"] + tot["teammates_flashed"]
    tot["flashes_landed"] = landed
    tot["own_flash_pct"] = 100.0 * tot["teammates_flashed"] / landed if landed else 0.0
    tot["unused_pct"] = (100.0 * tot["nades_unused"] / tot["nades_start"]
                         if tot["nades_start"] else 0.0)
    tot["wasted_per_round"] = (tot["nades_wasted"] / tot["rounds"]
                               if tot["rounds"] else 0.0)
    tot["role"], tot["role_why"] = role_of(tot)

    adrs = [m["adr"] for m in matches]
    return {
        "steamid": steamid,
        "name": (name["name"] if name else steamid),
        "matches": matches,
        "totals": tot,
        "best": max(adrs) if adrs else 0.0,
        "worst": min(adrs) if adrs else 0.0,
    }


def match_series(team_id: int, map_name: str | None = None,
                 limit: int | None = None) -> list[dict]:
    """One row per match, oldest first, with the measures worth tracking.

    The gap this fills: a season total and a single match, with nothing in
    between — and the in-between is where coaching happens. "Is the thing we
    fixed in practice holding?" is unanswerable from either end and trivial
    from the middle.

    Filtering by map matters more than it looks. A team's Mirage and its Nuke
    are different teams, and a season average across both hides a map getting
    better while another gets worse.
    """
    anchors = team_anchors(team_id).get("anchors", {})
    sides = _side_by_round(team_id, anchors)
    where = "d.team_id = ?"
    args: list = [team_id]
    if map_name:
        where += " AND m.map_name = ?"
        args.append(map_name)

    rows = db.query(f"""SELECT m.match_key, m.map_name, m.rounds, m.final_ct,
                               m.final_t, m.ingested_at, d.filename
                          FROM matches m JOIN demos d ON d.id = m.demo_id
                         WHERE {where}
                      ORDER BY m.ingested_at ASC, d.filename ASC""", *args)

    out = []
    for m in rows:
        mk = m["match_key"]
        rs = db.query("SELECT round_num, ct_won FROM rounds WHERE match_key = ?", mk)
        won = played = 0
        for r in rs:
            side = sides.get((mk, r["round_num"]))
            if side not in ("ct", "t"):
                continue
            played += 1
            won += bool(r["ct_won"]) == (side == "ct")
        if not played:
            continue

        # Opening duels and trades, from this team's own rows only.
        first = db.one("SELECT MIN(round_num) n FROM rounds WHERE match_key = ?", mk)
        started = sides.get((mk, first["n"] if first else 1))
        us = them = None
        if started and m["final_ct"] is not None:
            us = m["final_ct"] if started == "ct" else m["final_t"]
            them = m["final_t"] if started == "ct" else m["final_ct"]

        # EVERY PLAYER ON OUR SIDE THAT ROUND, not the players who recur
        # across the season. Aggregating over the anchors made a metric
        # labelled "your players only" into one man's damage on a solo-queue
        # season, and a team does not swing ninety points of ADR between
        # matches; one player does.
        agg = None
        rows_pr = db.query("""SELECT round_num, steamid, side, opening_kill,
                                     opening_death, trade_kills, traded_deaths,
                                     deaths, damage
                                FROM player_rounds WHERE match_key = ?""", mk)
        keep = [r for r in rows_pr if sides.get((mk, r["round_num"])) == r["side"]]
        if keep:
            agg = {
                "ok": sum(r["opening_kill"] or 0 for r in keep),
                "od": sum(r["opening_death"] or 0 for r in keep),
                "tk": sum(r["trade_kills"] or 0 for r in keep),
                "td": sum(r["traded_deaths"] or 0 for r in keep),
                "d": sum(r["deaths"] or 0 for r in keep),
                "dmg": sum(r["damage"] or 0.0 for r in keep),
                "n": len(keep),
            }

        out.append({
            "match_key": mk,
            "map": (m["map_name"] or "").replace("de_", ""),
            "rounds": played,
            "won": won,
            "win_pct": 100.0 * won / played,
            # The numerator and denominator behind every plotted figure, so a
            # band across several matches can be a total rather than a mean of
            # means. Six rounds and twenty-nine rounds are not the same
            # evidence and an average that treats them alike is not the
            # season's average.
            "parts": {
                "win_pct": (won, played),
                "adr": ((agg["dmg"], agg["n"]) if agg else (0, 0)),
                "traded_pct": ((agg["td"], agg["d"]) if agg else (0, 0)),
                "opening_pct": ((agg["ok"], agg["ok"] + agg["od"])
                                if agg else (0, 0)),
            },
            "us": us, "them": them,
            "result": None if us is None else ("W" if us > them else
                                               "L" if us < them else "T"),
            "adr": (agg["dmg"] / agg["n"]) if agg and agg["n"] else None,
            "traded_pct": (100.0 * agg["td"] / agg["d"])
                          if agg and agg["d"] else None,
            "opening_pct": (100.0 * agg["ok"] / (agg["ok"] + agg["od"]))
                           if agg and (agg["ok"] or agg["od"]) else None,
        })
    return out[-limit:] if limit else out


def maps_played(team_id: int) -> list[tuple[str, int]]:
    """Maps this team has matches on, most played first — for the map filter."""
    return [(r["map_name"], r["n"]) for r in db.query(
        """SELECT m.map_name, COUNT(*) n FROM matches m
             JOIN demos d ON d.id = m.demo_id
            WHERE d.team_id = ? GROUP BY m.map_name ORDER BY n DESC""", team_id)]
