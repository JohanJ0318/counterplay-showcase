"""Buy calls, per round and per player, for one match.

Two kinds of reading, and they are kept apart because they rest on different
things:

  * THE TEAM'S CALL is judged. counterplay.economy compares what the team
    did (save, force, full buy) with the other call over this round and the
    next, using the one learned curve and the money rules measured off the
    demos. It says something only when the other call is ahead by
    economy.MARGIN of a round or more.

  * EACH PLAYER'S BUY is checked against the team's own call, with no model
    at all: bought into a save, saved while the rest bought, held an SMG on
    rifle money, sat on money while a teammate had only a pistol. Each is a
    fact read off the demo, so each can be checked in the demo.

Silent on the round after a pistol round. It is judged but never flagged:
the model says force there every time, on both sides, and the corpus does
not back that on CT. Of teams that lost the pistol, T sides that forced won
0.81 of the next two rounds against 0.55 for those that saved, but CT sides
that forced won 0.48 against 0.63, on 21 forces each. A check this sure of
itself on the most argued-over buy in the game, with the data split, says
nothing rather than guess.

Regulation only. Overtime resets everyone's money every three rounds and
pays its own way, which is a different game; it is left out rather than
judged by the wrong rules. Pistol rounds are left out too: nobody chooses
what to buy with $800.
"""
from __future__ import annotations

from collections import defaultdict

from counterplay import economy as E

from . import db, report

# A player's buy, read against the team's. Team call is read off the MIDDLE
# player's equipment, so one player's rifle cannot turn a save into a buy.
TEAM_SAVED_BELOW = 1500       # median player equipment: pistols and little else
TEAM_BOUGHT_FROM = 3500       # median player equipment: a rifle or close to it
BROKE_SAVE_SPEND = 2000       # spent this much while the team saved
COULD_BUY_FROM = 3000         # had this much and held under TEAM_SAVED_BELOW
RIFLE_MONEY = 4500            # could have bought a rifle and armour outright
COULD_DROP_LEFT = 3000        # left after buying, with a teammate on a pistol
CAP_LOSS_FROM = 500           # dollars over the cap before it is worth a line
AWP_KIT = 4750 + 650          # an AWP and armour, the least an AWPer buys
AWPER_ROUNDS = 5              # held an AWP this many rounds: the team's AWPer,
                              # not someone who picked one up
AWP_MONEY_SPENT = 1500        # spent this much the round before


def _load(match_key: str):
    rounds = {r["round_num"]: r for r in db.query(
        "SELECT round_num, ct_won FROM rounds WHERE match_key = ? "
        "ORDER BY round_num", match_key)}
    rows = db.query(
        """SELECT round_num, steamid, name, side, money_start, spent,
                  equip_value, loadout, kills, deaths, damage
             FROM player_rounds WHERE match_key = ?""", match_key)
    # A FACEIT coach sits in a sixth slot on one side, alive and holding a
    # pistol all match. Counted as a player, every team total is off by one
    # person and no round has five a side, so nothing got judged at all on
    # the first real team's matches. report.is_coach() is the one definition,
    # judged over every round of the match.
    totals = defaultdict(lambda: {"kills": 0, "deaths": 0, "damage": 0.0})
    for r in rows:
        t = totals[r["steamid"]]
        t["kills"] += r["kills"] or 0
        t["deaths"] += r["deaths"] or 0
        t["damage"] += r["damage"] or 0
    coaches = {sid for sid, t in totals.items() if report.is_coach(t)}
    players = defaultdict(list)
    for r in rows:
        if r["steamid"] not in coaches:
            players[r["round_num"]].append(r)
    return rounds, players


def _halves(rounds: dict, players: dict) -> dict[int, int]:
    """round_num -> which half it is in (0, 1, then overtime), read off the
    side swap rather than assumed, so MR15 demos and short matches work."""
    half, out, prev = 0, {}, None
    for rn in sorted(rounds):
        ct = {p["steamid"] for p in players.get(rn, []) if p["side"] == "ct"}
        if prev is not None and ct and len(ct & prev) < len(ct) / 2:
            half += 1
        out[rn] = half
        if ct:
            prev = ct
    return out


def match_calls(match_key: str) -> list[dict]:
    """Every regulation round we can judge, both sides, in round order.

    Each is {round, side, won, money, spent, equip, made, best, gain, flag,
    options, players, notes}. A round is left out when either side lacks
    money data for all five players (a demo parsed before migration 23)."""
    rounds, players = _load(match_key)
    if not rounds:
        return []
    half = _halves(rounds, players)
    starts = {}
    for rn in sorted(rounds):
        starts.setdefault(half[rn], rn)
    half_len = (starts[1] - starts[0]) if 1 in starts else 12

    def team(rn, side):
        ps = [p for p in players.get(rn, []) if p["side"] == side]
        if len(ps) != 5 or any(p["money_start"] is None or p["spent"] is None
                               or p["equip_value"] is None for p in ps):
            return None
        return {"money": sum(p["money_start"] for p in ps),
                "spent": sum(p["spent"] for p in ps),
                "equip": sum(p["equip_value"] for p in ps), "players": ps}

    out = []
    for rn in sorted(rounds):
        h = half[rn]
        if h >= 2 or rn == starts[h]:
            continue                                   # overtime, pistol round
        results = [bool(rounds[k]["ct_won"]) for k in range(starts[h], rn)
                   if k in rounds]
        # Rounds left in this half, this one included. The half's length is
        # read off the swap (12, or 15 on an MR15 demo), never off how the
        # match went on to end, which would hand the judge the future.
        rounds_left = half_len - (rn - starts[h])
        teams = {s: team(rn, s) for s in ("ct", "t")}
        if not all(teams.values()):
            continue
        for side in ("ct", "t"):
            other = "t" if side == "ct" else "ct"
            us, them = teams[side], teams[other]
            mine = [r if side == "ct" else not r for r in results]
            j = E.judge(money=us["money"], spent=us["spent"], equip=us["equip"],
                        side=side, counter=E.loss_counter(mine),
                        their_equip=them["equip"], their_money=them["money"],
                        their_spent=them["spent"],
                        their_counter=E.loss_counter([not w for w in mine]),
                        rounds_left=rounds_left,
                        seed=rn * 2 + (side == "ct"))
            if rn == starts[h] + 1:
                j["flag"] = False            # after the pistol: see above
            out.append(dict(j, round=rn, side=side,
                            won=bool(rounds[rn]["ct_won"]) == (side == "ct"),
                            money=us["money"], spent=us["spent"],
                            players=us["players"],
                            notes=player_notes(us["players"])))
    extra = match_notes(match_key, rounds, players, half, starts)
    for c in out:
        c["notes"] += extra.get((c["round"], c["side"]), [])
    return out


def match_notes(match_key, rounds, players, half, starts) -> dict:
    """Notes that need two rounds to see: money lost to the cap, and an AWPer
    who spent the AWP money the round before. {(round, side): [note]}."""
    kills = defaultdict(int)          # (round, steamid) -> kill money
    team_kills = defaultdict(int)     # (round, side) -> kills that side made
    planted = set()
    for e in db.query("SELECT round_num, type, attacker_steamid, victim_side, "
                      "weapon FROM events WHERE match_key = ?", match_key):
        if e["type"] == "plant":
            planted.add(e["round_num"])
            continue
        if e["type"] != "death" or not e["victim_side"]:
            continue
        killer_side = "t" if e["victim_side"] == "ct" else "ct"
        team_kills[(e["round_num"], killer_side)] += 1
        if e["attacker_steamid"]:
            kills[(e["round_num"], e["attacker_steamid"])] += E.kill_reward(e["weapon"])

    by = {(rn, p["steamid"]): p for rn, ps in players.items() for p in ps}
    awp_rounds = defaultdict(int)
    for (rn, sid), p in by.items():
        if p["loadout"] and "AWP" in p["loadout"].split(", "):
            awp_rounds[sid] += 1
    out = defaultdict(list)

    def add(rn, p, kind, text):
        out[(rn, p["side"])].append({"steamid": p["steamid"], "name": p["name"],
                                     "kind": kind, "text": text})

    for (rn, sid), p in by.items():
        nxt = by.get((rn + 1, sid))
        h = half.get(rn)
        if (nxt is None or h is None or h >= 2 or half.get(rn + 1) != h or
                nxt["side"] != p["side"] or p["money_start"] is None or
                p["spent"] is None or nxt["money_start"] is None):
            continue
        side = p["side"]
        results = [bool(rounds[k]["ct_won"]) == (side == "ct")
                   for k in range(starts[h], rn) if k in rounds]
        won = bool(rounds[rn]["ct_won"]) == (side == "ct")
        left = p["money_start"] - p["spent"]
        uncapped = left + E.income(side, won, E.loss_counter(results),
                                   kills[(rn, sid)], team_kills[(rn, side)],
                                   rn in planted)
        lost = uncapped - E.MONEY_CAP
        if lost >= CAP_LOSS_FROM and nxt["money_start"] >= E.MONEY_CAP - 50:
            add(rn, p, "cap",
                f"kept ${left:,} unspent, so about ${lost // 50 * 50:,} went "
                f"over the $16,000 cap")

        # The AWPer, the round after spending: the team bought, they could
        # not afford the AWP, and would have without last round's spend.
        if awp_rounds[sid] < AWPER_ROUNDS or nxt["spent"] is None:
            continue
        team_next = sorted(q["equip_value"] or 0 for q in players.get(rn + 1, [])
                           if q["side"] == side)
        team_now = sorted(q["equip_value"] or 0 for q in players.get(rn, [])
                          if q["side"] == side)
        if not team_next or not team_now:
            continue
        bought_next = team_next[len(team_next) // 2] >= TEAM_BOUGHT_FROM
        bought_now = team_now[len(team_now) // 2] >= TEAM_BOUGHT_FROM
        has_awp = nxt["loadout"] and "AWP" in nxt["loadout"].split(", ")
        if (bought_next and not bought_now and not has_awp and
                p["spent"] >= AWP_MONEY_SPENT and
                nxt["money_start"] < AWP_KIT <= nxt["money_start"] + p["spent"]):
            add(rn + 1, nxt, "awp_money",
                f"no AWP with ${nxt['money_start']:,} to spend, after "
                f"spending ${p['spent']:,} in round {rn} while the team "
                f"did not buy")
    return out


def player_notes(ps: list) -> list[dict]:
    """Where a player's buy went against the team's own call this round.

    Returns [{steamid, name, kind, text}]. No model: each line is money and
    equipment straight off the demo."""
    eq = sorted(p["equip_value"] for p in ps)
    median = eq[len(eq) // 2]
    notes = []

    def note(p, kind, text):
        notes.append({"steamid": p["steamid"], "name": p["name"],
                      "kind": kind, "text": text})

    if median < TEAM_SAVED_BELOW:
        for p in ps:
            if p["spent"] >= BROKE_SAVE_SPEND:
                note(p, "broke_save",
                     f"spent ${p['spent']:,} while the team saved")
        return notes
    if median < TEAM_BOUGHT_FROM:
        return notes                     # a mixed round: no call to hold anyone to

    pistol_only = [p for p in ps if p["equip_value"] < TEAM_SAVED_BELOW]
    for p in ps:
        gun = E.main_weapon(p["loadout"])
        if (p["equip_value"] < TEAM_SAVED_BELOW and
                p["money_start"] >= COULD_BUY_FROM):
            note(p, "saved_alone",
                 f"held ${p['equip_value']:,} with ${p['money_start']:,} "
                 f"to spend while the team bought")
        elif (gun in (E.SMG, E.PISTOL) and p["money_start"] >= RIFLE_MONEY and
              p["equip_value"] < p["money_start"]):
            note(p, "light_buy",
                 f"{'an SMG' if gun == E.SMG else 'a pistol'} with "
                 f"${p['money_start']:,} to spend")
        left = p["money_start"] - p["spent"]
        if (left >= COULD_DROP_LEFT and
                any(q is not p and q["money_start"] < COULD_BUY_FROM
                    for q in pistol_only)):
            note(p, "no_drop",
                 f"kept ${left:,} while a teammate had only a pistol")
    return notes
