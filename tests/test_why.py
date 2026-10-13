"""The opening-duel chain (app/why.py): what it counts and what it may claim."""
from app import league, why


def _d(sec, side, victim, attacker):
    return {"seconds": sec, "victim_side": side, "victim_steamid": victim,
            "attacker_steamid": attacker}


def test_a_trade_is_the_opening_killer_dying_within_five_seconds():
    first = _d(10.0, "t", "a", "K")
    assert why.opening_events([first, _d(13.0, "ct", "K", "b")]) == ("t", True)
    # Too late, or somebody else dying, is not a trade.
    assert why.opening_events([first, _d(16.0, "ct", "K", "b")]) == ("t", False)
    assert why.opening_events([first, _d(11.0, "ct", "x", "b")]) == ("t", False)
    assert why.opening_events([]) is None


def test_the_split_adds_up_to_the_whole_gap():
    mine, ref = (0.38, 0.27, 0.17), (0.25, 0.43, 0.26)
    shares = why._shapley(mine, ref)
    whole = why._expected(*mine) - why._expected(*ref)
    assert abs(sum(shares) - whole) < 1e-12


def _team(n, traded, traded_won, open_won, role="lost"):
    c = why.empty()
    c[role] = {"n": n, "traded": traded, "traded_won": traded_won,
               "open_won": open_won}
    return {"t": c, "ct": why.empty()}


def _ref(monkeypatch):
    chain = {s: {"lost": {"n": 1000, "traded": 250, "traded_won": 107,
                          "open_won": 195},
                 "took": {"n": 1000, "traded": 250, "traded_won": 143,
                          "open_won": 555}} for s in ("ct", "t")}
    monkeypatch.setattr(league, "_REF", {"opening_chain": chain})


def test_names_the_step_that_costs_the_rounds_not_the_trade(monkeypatch):
    # NC State Red's shape: trades MORE than college teams, loses after.
    _ref(monkeypatch)
    e = why.explain(_team(29, 11, 3, 3), {}, "lost")
    assert e["total"] <= -1
    assert e["culprits"] and 0 not in e["culprits"]
    assert e["links"][0]["rounds"] > 0          # the trade earns rounds


def test_claims_nothing_when_the_team_is_not_behind(monkeypatch):
    _ref(monkeypatch)
    e = why.explain(_team(40, 10, 5, 9), {}, "lost")   # about college rate
    assert e["culprits"] == [] and e["confidence"] is None


def test_their_trade_back_counts_against_you(monkeypatch):
    # Winning the opening duel and having it traded straight back, far more
    # than college teams: that link must read as bad for you.
    _ref(monkeypatch)
    e = why.explain(_team(40, 30, 10, 5, role="took"), {}, "took")
    assert e["links"][0]["verdict"] < 0
    assert e["links"][0]["rounds"] < 0
