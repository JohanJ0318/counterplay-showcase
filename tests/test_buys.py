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
                their_counter=0, last_of_half=True)
    assert j["p"] == j["v"]
    # with nothing to save for, buying beats saving
    assert j["best"] == "buy" and not j["flag"]


def test_a_save_that_matches_the_advice_is_never_flagged():
    j = E.judge(money=6000, spent=1500, equip=2500, side="ct", counter=1,
                their_equip=26000, their_money=20000, their_spent=16000,
                their_counter=0, last_of_half=False)
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
