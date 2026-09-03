"""Sanity checks for parsed output.

parse.py is the one module that talks to real demo files, so it is the one most
likely to be silently wrong. Wrong in ways that do not raise: sides swapped,
warmup rounds included, ticks misread as seconds. The model will happily train
on all of it and hand you confident nonsense.

Run this after every parsing change. It checks facts about Counter-Strike that
must be true regardless of what the parser did.
"""
from __future__ import annotations

import pandas as pd

# Below this many matches, the distributional checks are switched off: they
# describe a population, and one match is not one. See validate() for why.
MIN_MATCHES_FOR_DISTRIBUTION = 10


class Check:
    def __init__(self, name, ok, detail=""):
        self.name, self.ok, self.detail = name, ok, detail

    def __str__(self):
        mark = "PASS" if self.ok else "FAIL"
        line = f"  [{mark}] {self.name}"
        return line if self.ok else f"{line}\n         {self.detail}"


def validate(rounds: pd.DataFrame, events: pd.DataFrame) -> list[Check]:
    checks = []

    def add(name, ok, detail=""):
        checks.append(Check(name, ok, detail))

    # Some checks below are DISTRIBUTIONAL: they ask whether the mix of
    # outcomes looks like Counter-Strike. Those are only meaningful across many
    # matches. A real FACEIT demo used to develop this was a 12-0 CT blowout
    # with no bomb ever planted — every one of those checks failed, and the
    # parse was perfectly correct. Applied to one match they punish a lopsided
    # game; applied to a corpus they catch swapped sides. So they only run when
    # there is a corpus to run them on.
    n_matches = rounds["match_id"].nunique() if len(rounds) else 0
    corpus = n_matches >= MIN_MATCHES_FOR_DISTRIBUTION

    def add_dist(name, ok, detail=""):
        if not corpus:
            return
        checks.append(Check(name, ok, detail))

    # --- rounds -----------------------------------------------------------
    per_match = rounds.groupby("match_id")["round_num"].agg(["count", "min", "max"])
    # The floor is 5, not 13. A completed MR12 match is at least 13 rounds, but
    # matches get abandoned and forfeited all the time — the real demo this was
    # developed against ended 12-0 when a side left. Those rounds are genuine
    # and perfectly usable; only a count too low to be a match at all is
    # evidence of a broken parse. The ceiling still catches warmup rounds and
    # misdetected boundaries, which is what this check is really for.
    # The ceiling is 60, not 40. A professional match that goes to several
    # overtimes really does play 46 rounds — one in this corpus does — and 40
    # failed it as though the parse were broken. 60 still catches the failure
    # this check is for: warmup rounds kept, or round boundaries merged, which
    # produce counts far beyond any real match.
    bad = per_match[(per_match["count"] < 5) | (per_match["count"] > 60)]
    add("round count per match is 5-60",
        bad.empty,
        f"{len(bad)} match(es) outside range — warmup rounds included, or "
        f"round boundaries misdetected:\n         {bad.head().to_dict('index')}")

    long_ = per_match[per_match["count"] > 30]
    if len(long_):
        checks.append(Check(
            f"note: {len(long_)} match(es) over 30 rounds — overtime, not a "
            f"parse error", True))

    short = per_match[per_match["count"] < 13]
    if len(short):
        # Not a failure, but worth saying out loud: a corpus that is mostly
        # abandoned matches is a corpus of unrepresentative rounds.
        checks.append(Check(
            f"note: {len(short)} match(es) under 13 rounds — abandoned or "
            f"forfeited, not a parse error", True))

    # count == max only proves contiguity if the numbers are also distinct.
    # A duplicated round 7 plus a missing round 12 satisfies both endpoints and
    # every count, and merges two rounds' deaths onto one five-player side.
    dupes = rounds.duplicated(subset=["match_id", "round_num"]).sum()
    add("round numbers are unique within a match", dupes == 0,
        f"{dupes} duplicate (match, round) pair(s) — the same round is being "
        f"emitted twice, usually a freeze-end tick matched to two boundaries")

    add("round numbers start at 1 and are contiguous",
        (per_match["min"] == 1).all() and (per_match["max"] == per_match["count"]).all()
        and dupes == 0,
        "gaps or off-by-one in round numbering")

    wr = rounds["ct_won"].mean()
    add_dist("CT win rate is 30-70%", 0.30 <= wr <= 0.70,
        f"got {wr:.1%} — sides are probably swapped, or the winner column "
        f"is being read wrong (CS2 uses team_num 2=T, 3=CT)")

    eq = rounds[["equip_ct", "equip_t"]]
    # A fully kitted professional side — five players with rifle or AWP, armour,
    # kit and a full nade set — comes to roughly 38,000. The old 35,000 ceiling
    # was tuned on matchmaking demos and failed real pro buys. 50,000 still
    # catches the failure this check exists for: summing across all rounds
    # rather than per round, which lands in the hundreds of thousands.
    add("equipment values are 0-50000",
        bool(((eq >= 0) & (eq <= 50000)).all().all()),
        f"range seen: {eq.min().min():.0f} to {eq.max().max():.0f} — if this is "
        f"huge you may be summing across all rounds, not per round")

    add("equipment is non-zero in most rounds",
        (rounds["equip_ct"] > 0).mean() > 0.9,
        "equipment mostly zero — the freeze-end tick lookup is likely failing")

    # --- events -----------------------------------------------------------
    if events.empty:
        add("events exist", False, "no events parsed at all")
        return checks

    deaths = events[events["type"] == "death"]
    add("deaths per round never exceed 10",
        deaths.groupby(["match_id", "round_num"]).size().max() <= 10,
        "more than 10 deaths in a round — rounds are being merged together")

    for side in ("ct", "t"):
        m = deaths[deaths["victim_side"] == side]
        worst = m.groupby(["match_id", "round_num"]).size().max() if len(m) else 0
        add(f"{side.upper()} deaths per round never exceed 5", worst <= 5,
            f"saw {worst} — victim side is being misread")

    share = (deaths["victim_side"] == "ct").mean()
    add_dist("death split between sides is 35-65%", 0.35 <= share <= 0.65,
        f"CT deaths are {share:.1%} of all deaths — victim_side mapping is likely wrong")

    add("event times are 0-200 seconds",
        bool(events["seconds"].between(0, 200).all()),
        f"range: {events['seconds'].min():.1f} to {events['seconds'].max():.1f} — "
        f"if these are in the thousands you are reporting ticks, not seconds "
        f"(divide by the tick rate, usually 64)")

    plants = events[events["type"] == "plant"]
    if len(plants):
        pr = plants.groupby(["match_id", "round_num"]).size().max()
        add("at most one plant per round", pr <= 1,
            f"saw {pr} plants in one round")
        rate = len(plants) / len(rounds)
        add_dist("plant rate is 10-70% of rounds", 0.10 <= rate <= 0.70,
                 f"got {rate:.1%}")

    orphans = set(zip(events.match_id, events.round_num)) - set(zip(rounds.match_id, rounds.round_num))
    add("every event belongs to a known round", not orphans,
        f"{len(orphans)} event group(s) reference rounds that do not exist")

    return checks


def report(rounds, events) -> bool:
    checks = validate(rounds, events)
    print(f"\n  Validating {len(rounds)} rounds, {len(events)} events\n")
    for c in checks:
        print(c)
    failed = [c for c in checks if not c.ok]
    print(f"\n  {len(checks) - len(failed)}/{len(checks)} passed")
    if failed:
        print("  Fix parsing before training. A model trained on this will be confidently wrong.\n")
    else:
        print("  Parsing looks sane. Safe to train.\n")
    return not failed
