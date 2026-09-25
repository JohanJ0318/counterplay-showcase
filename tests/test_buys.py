"""The buy check: money rules as the demos pay them, and the player notes.

The loss-bonus rule is here because it was measured, not remembered: "a win
resets the counter" is what most people would write, and it matched 83% of
real losses against 96.5% for the rule below.
"""
from __future__ import annotations

from counterplay import economy as E
from app import buys


def test_the_loss_counter_starts_at_one_and_a_win_takes_two_off():
    assert E.loss_counter([]) == 1
    assert E.loss_bonus(E.loss_counter([])) == 1900        # losing a pistol
    # W L L L W L, a sequence off a real demo: paid 1400, 1900, 2400, 1900
    seq, paid = [True, False, False, False, True, False], []
    for i, won in enumerate(seq):
        if not won:
            paid.append(E.loss_bonus(E.loss_counter(seq[:i])))
    assert paid == [1400, 1900, 2400, 1900]


def test_the_loss_bonus_stops_at_3400():
    assert E.loss_bonus(E.loss_counter([False] * 9)) == 3400


def test_more_equipment_wins_more():
    assert E.p_win(26000, 2500, "t") > 0.9
    assert E.p_win(2500, 26000, "ct") < 0.1
    assert E.p_win(15000, 15000, "t") > E.p_win(15000, 15000, "ct")


def test_nothing_carries_past_the_last_round_of_a_half():
    j = E.judge(money=12000, spent=11000, equip=12000, side="t", counter=2,
                their_equip=26000, their_money=9000, their_spent=4000,
                their_counter=0, rounds_left=1)
    assert j["p"] == j["v"]
    # with nothing to save for, buying beats saving
    assert j["best"] == "buy" and not j["flag"]


def test_a_save_that_matches_the_advice_is_never_flagged():
    j = E.judge(money=6000, spent=1500, equip=2500, side="ct", counter=1,
                their_equip=26000, their_money=20000, their_spent=16000,
                their_counter=0, rounds_left=6)
    assert j["made"] == "eco"
    assert not (j["flag"] and j["best"] == "save")


def _p(sid, money, spent, equip, loadout="Glock-18"):
    return {"steamid": sid, "name": sid, "money_start": money, "spent": spent,
            "equip_value": equip, "loadout": loadout}


def test_buying_into_a_save_is_noted():
    ps = [_p("a", 3000, 200, 1000), _p("b", 3000, 200, 1000),
          _p("c", 3000, 200, 1000), _p("d", 3000, 300, 1100),
          _p("e", 4000, 3700, 3900, "Glock-18, AK-47")]
    got = buys.player_notes(ps)
    assert [(n["steamid"], n["kind"]) for n in got] == [("e", "broke_save")]


def test_an_smg_on_rifle_money_and_a_lone_save_are_noted():
    ps = [_p("a", 5000, 4700, 4900, "Glock-18, AK-47"),
          _p("b", 5000, 4700, 4900, "Glock-18, AK-47"),
          _p("c", 5000, 4700, 4900, "Glock-18, AK-47"),
          _p("d", 6000, 1300, 1500, "Glock-18, MAC-10"),
          _p("e", 4200, 0, 200)]
    kinds = {(n["steamid"], n["kind"]) for n in buys.player_notes(ps)}
    assert ("d", "light_buy") in kinds
    assert ("e", "saved_alone") in kinds


def test_a_player_who_cannot_afford_anything_is_not_blamed():
    ps = [_p("a", 5000, 4700, 4900, "Glock-18, AK-47")] * 4 + \
         [_p("e", 1200, 0, 200)]
    assert not [n for n in buys.player_notes(ps) if n["steamid"] == "e"]


def test_a_coach_in_the_server_does_not_stop_the_check(monkeypatch):
    """The first real team's demos had a FACEIT coach as a sixth player on
    one side, and every round was skipped for not having five."""
    def fake_query(sql, *args):
        if "FROM rounds" in sql:
            return [{"round_num": n, "ct_won": n % 2} for n in range(1, 7)]
        if "FROM events" in sql:
            return []
        out = []
        for n in range(1, 7):
            for i in range(5):
                for side in ("ct", "t"):
                    out.append({"round_num": n, "steamid": f"{side}{i}",
                                "name": f"{side}{i}", "side": side,
                                "money_start": 4000, "spent": 3000,
                                "equip_value": 3500, "loadout": "Glock-18",
                                "kills": 1, "deaths": 1, "damage": 80.0})
            out.append({"round_num": n, "steamid": "coach", "name": "coach",
                        "side": "ct", "money_start": 800, "spent": 0,
                        "equip_value": 200, "loadout": "USP-S",
                        "kills": 0, "deaths": 0, "damage": 0.0})
        return out
    monkeypatch.setattr(buys.db, "query", fake_query)
    calls = buys.match_calls("m")
    assert calls, "rounds with a coach in the server must still be judged"
    assert all(len(c["players"]) == 5 for c in calls)


def test_late_buys_do_not_invent_money():
    """`spent` includes buys made after freeze-end; freeze-end equipment does
    not. A team holding $14,500 and keeping $3,750 can reach $18,250, not a
    full buy, however the two readings disagree about what it carried in."""
    opts = E.options(money=19150, reach=14500 + 19150 - 15400, side="t")
    assert opts["buy"][0] == 18250
    assert E.kind(opts["buy"][0]) == "force"


def test_every_ct_is_paid_fifty_for_each_team_kill():
    """Found in what was left of 11,000 real CT losses after the loss bonus
    and each player's own kill money: $50 steps, one per team kill."""
    base = E.income("ct", False, 1, 0, 0, False)
    assert E.income("ct", False, 1, 0, 3, False) == base + 150
    assert E.income("t", False, 1, 0, 3, False) == E.loss_bonus(1)
    assert E.income("t", False, 1, 0, 0, True) == E.loss_bonus(1) + 600


def test_kill_rewards_by_weapon():
    assert E.kill_reward("awp") == 100
    assert E.kill_reward("mac10") == 600
    assert E.kill_reward("nova") == 900
    assert E.kill_reward("knife_karambit") == 1500
    assert E.kill_reward("ak47") == 300


def test_money_over_the_cap_and_an_awper_short_of_the_awp(monkeypatch):
    """Round 1: the CT AWPer spends $2,000 on a round the team saves, then
    cannot afford the AWP in round 2 when the team buys. The T side keeps
    $15,000 and wins, which pushes them over $16,000."""
    def pr(rn, sid, side, money, spent, equip, loadout):
        return {"round_num": rn, "steamid": sid, "name": sid, "side": side,
                "money_start": money, "spent": spent, "equip_value": equip,
                "loadout": loadout, "kills": 1, "deaths": 1, "damage": 50.0}

    def fake_query(sql, *args):
        if "FROM rounds" in sql:
            return [{"round_num": n, "ct_won": 0} for n in range(1, 8)]
        if "FROM events" in sql:
            return []
        rows = []
        for rn in range(1, 8):
            for i in range(5):
                if i == 0 and rn == 5:      # the round the AWPer spends
                    rows.append(pr(rn, "awper", "ct", 4000, 2000, 2200, "USP-S, MP9"))
                elif i == 0 and rn == 6:    # and the round after
                    rows.append(pr(rn, "awper", "ct", 4500, 3000, 3200, "USP-S, MP9"))
                elif i == 0:
                    rows.append(pr(rn, "awper", "ct", 6000, 5400, 5600, "USP-S, AWP"))
                else:
                    saving = rn == 5
                    rows.append(pr(rn, f"ct{i}", "ct", 4000, 300 if saving else 3500,
                                   500 if saving else 3700, "USP-S, M4A1-S"))
                rows.append(pr(rn, f"t{i}", "t", 16000, 1000, 5000,
                               "Glock-18, AK-47"))
        return rows

    monkeypatch.setattr(buys.db, "query", fake_query)
    kinds = {(c["round"], n["steamid"], n["kind"])
             for c in buys.match_calls("m") for n in c["notes"]}
    assert (6, "awper", "awp_money") in kinds
    assert any(k == "cap" and sid.startswith("t") for _, sid, k in kinds)
