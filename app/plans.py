"""Plans, features, and who gets what.

This is the single place the product's shape is written down. Routes, templates
and the pricing page all read from here — nothing else hard-codes a plan name,
so changing what a tier includes is a one-line edit rather than a search.

Two ideas carry the whole thing:

**Access is a level, not a boolean.** Most features exist at two depths. A free
account sees its own player stats; a paid one sees the weapon and economy
breakdown behind them. Free accounts watch a round back in the 2D replayer; the
top tier scrubs it frame by frame. Modelling that as on/off would mean either
giving away the paid half or hiding the thing that makes people want it, so
`Level` has three values and features declare where each one starts.

**Plans are ranked, and access is monotone.** Every plan is a point on one
ladder, and a feature unlocks at a rank. Nothing needs a per-plan-per-feature
grid, and no plan can accidentally be missing something a cheaper plan has —
the ordering makes that unrepresentable.

The ladder runs individual → team, because team plans include everything an
individual plan does plus the team-level work:

    free  <  pro  <  team_t3  <  team_t2  <  team_t1

Tier 1 is the top, following the way tiers are numbered in Counter-Strike
rather than the way they are numbered in software.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Level(IntEnum):
    """How much of a feature an account can reach."""

    NONE = 0
    CORE = 1
    FULL = 2

    @property
    def label(self) -> str:
        return {Level.NONE: "—", Level.CORE: "Core", Level.FULL: "Full"}[self]


@dataclass(frozen=True)
class Plan:
    key: str
    name: str
    rank: int
    kind: str                       # "individual" or "team"
    blurb: str
    # Monthly price in euro. None means NOT DECIDED YET — it renders as "price
    # not set" rather than as free, because quietly showing €0 for a tier that
    # is meant to cost money is the kind of thing that gets discovered by a
    # customer. Set these before the pricing page goes public.
    price_eur_month: float | None = None

    @property
    def is_team(self) -> bool:
        return self.kind == "team"

    @property
    def price_label(self) -> str:
        if self.price_eur_month is None:
            return "price not set"
        if self.price_eur_month == 0:
            return "Free"
        return f"€{self.price_eur_month:.2f}/mo"


PLANS: dict[str, Plan] = {
    p.key: p
    for p in [
        Plan("free", "Free", 0, "individual", price_eur_month=0.0,
             blurb="Your own stats, the leaderboards, and a summary of any "
                   "public match."),
        Plan("pro", "Pro", 10, "individual", price_eur_month=None,
             blurb="Everything in Free, plus the weapon and economy detail "
                   "behind your numbers."),
        Plan("team_t3", "Team · Tier 3", 20, "team", price_eur_month=29.95,
             blurb="Team-level tracking and Pattern Finder for a full roster. "
                   "The entry point for a league team."),
        Plan("team_t2", "Team · Tier 2", 30, "team", price_eur_month=None,
             blurb="For programs running more than one roster."),
        Plan("team_t1", "Team · Tier 1", 40, "team", price_eur_month=None,
             blurb="Everything at full depth, including frame-by-frame replay "
                   "and the full Pattern Finder."),
    ]
}

DEFAULT_USER_PLAN = "free"
DEFAULT_TEAM_PLAN = "team_t3"


@dataclass(frozen=True)
class Feature:
    """One thing the product does, and the rank at which each depth unlocks.

    `core_from` and `full_from` are plan keys. None means that depth is never
    reached on any current plan — used for depths that are not built yet, so
    the pricing page can list them honestly instead of implying they ship.
    """

    key: str
    name: str
    blurb: str
    core_from: str | None
    full_from: str | None
    # What the paid depth actually adds, in one line. Shown on the pricing
    # page and in the upgrade prompt, so it has to be concrete.
    full_adds: str = ""
    # Features still being calibrated carry the label everywhere they appear,
    # rather than only on the marketing page.
    beta: bool = False

    def level_for(self, plan_key: str) -> Level:
        rank = PLANS[plan_key].rank
        if self.full_from is not None and rank >= PLANS[self.full_from].rank:
            return Level.FULL
        if self.core_from is not None and rank >= PLANS[self.core_from].rank:
            return Level.CORE
        return Level.NONE


FEATURES: dict[str, Feature] = {
    f.key: f
    for f in [
        Feature(
            "player_stats", "Player stats",
            "Per-player performance, with role, weapon and economy read off "
            "what the player actually did rather than off a label they picked.",
            core_from="free", full_from="pro",
            full_adds="Weapon-by-weapon breakdown, economy behavior, and role "
                      "detection with the numbers that produced it.",
        ),
        Feature(
            "team_stats", "Team stats",
            "Team-level performance over a season: map pool with round records, "
            "side splits, and how often you convert the situations you get into.",
            core_from="team_t3", full_from="team_t1",
            full_adds="Opponent-adjusted splits and per-half economy detail.",
        ),
        Feature(
            "leaderboards", "Leaderboards",
            "Where you stand against everyone else on the platform, in your own "
            "tier rather than against professionals.",
            core_from="free", full_from="free",
        ),
        Feature(
            "match_reports", "Match reports",
            "One page per match: how the rounds went, where the score moved, "
            "and the handful of moments worth pulling up at practice.",
            core_from="free", full_from="team_t1",
            full_adds="Every round scored, full moment list rather than the top "
                      "five, and export.",
        ),
        Feature(
            "replay_2d", "2D replayer",
            "Top-down playback of the rounds a report flags — ten seconds either "
            "side, so you watch the thing that mattered.",
            core_from="free", full_from="team_t1",
            full_adds="Frame-by-frame scrubbing, utility trajectories, and any "
                      "round rather than only the flagged ones.",
        ),
        Feature(
            "pattern_finder", "Pattern Finder",
            "The things your team does over and over without deciding to, "
            "counted across every match rather than eyeballed from one.",
            core_from="team_t3", full_from="team_t1",
            full_adds="Cross-season patterns, opponent-specific tendencies, and "
                      "the rounds behind every line.",
        ),
        Feature(
            "decision_scoring", "Decision scoring",
            "Which decisions cost you rounds you were winning. The part nobody "
            "else does, and the part still being calibrated.",
            core_from="team_t3", full_from="team_t1",
            full_adds="Scored against the full league pool rather than your own "
                      "matches alone.",
            beta=True,
        ),
    ]
}

# Order features appear on the pricing page and in the dashboard.
FEATURE_ORDER = ["player_stats", "team_stats", "leaderboards", "match_reports",
                 "replay_2d", "pattern_finder", "decision_scoring"]

PLAN_ORDER = ["free", "pro", "team_t3", "team_t2", "team_t1"]


def effective_plan(user_plan: str, team_plan: str | None = None) -> Plan:
    """The plan that actually applies to someone acting inside a team.

    A coach on a Free account looking at a team page gets the team's plan,
    because the team is what was paid for. Someone on Pro whose team has not
    subscribed keeps Pro. Whichever ranks higher wins — which is only
    well-defined because plans sit on one ladder.
    """
    best = PLANS[user_plan]
    if team_plan and PLANS[team_plan].rank > best.rank:
        best = PLANS[team_plan]
    return best


def access(feature_key: str, user_plan: str, team_plan: str | None = None) -> Level:
    """How much of `feature_key` this account can reach. The only gate."""
    return FEATURES[feature_key].level_for(effective_plan(user_plan, team_plan).key)


def upgrade_target(feature_key: str, want: Level, user_plan: str,
                   team_plan: str | None = None) -> Plan | None:
    """The cheapest plan that reaches `want` for this feature, or None.

    Returns None when the account already has that depth, and also when no plan
    provides it — a depth that is not built yet has no upgrade to sell, and the
    prompt should say so rather than pointing at a tier that would not deliver.
    """
    if access(feature_key, user_plan, team_plan) >= want:
        return None
    feature = FEATURES[feature_key]
    needed = feature.full_from if want == Level.FULL else feature.core_from
    return PLANS[needed] if needed else None


def matrix() -> list[tuple[Feature, dict[str, Level]]]:
    """The whole feature grid, for the pricing page."""
    return [(FEATURES[f], {p: FEATURES[f].level_for(p) for p in PLAN_ORDER})
            for f in FEATURE_ORDER]
