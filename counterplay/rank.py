"""Rank the moments that cost the most win probability.

This is the product. Everything upstream exists to make this list good.

v1 deliberately names no player. It reports the situation — side, man count,
timing, round type — and lets the coach assign responsibility. They already
know who was there; what they lack is the time to find the moment. Attribution
is v3, and getting it wrong is worse than not doing it.

One thing to hold on to while reading this module: the alive counts on a state
row are POST-event. The row for a death already has the dead player removed.
Every situation label below therefore has to add that player back, and it must
add them back to the side that actually lost them — which is why `state.py`
carries `victim_side` rather than leaving it to be inferred here.

NOT WIRED UP, AND THAT IS DELIBERATE.

Nothing in the product imports this module. It is the decision-scoring
engine — the win-probability model with isotonic calibration and an ECE gate —
and it is switched off because the thing it needs does not exist yet: a corpus
of collegiate rounds to train on. Pro and matchmaking rounds are the wrong
population, and a model trained on them would produce confident numbers about
a league it has never seen.

Two ways this could go wrong later, which is why the note is here:

  * A future reader finds an unimported module and deletes it as dead code.
    It is not dead. It is waiting.
  * A future reader wires it up because it looks finished. Before doing that,
    check the ECE gate still refuses to publish when the model cannot beat its
    own noise floor. That gate is the only thing standing between this product
    and a plausible fabricated number, which is the one mistake it has never
    made.

The dashboard and the match report both say decision scoring is not available.
Keep that true until the corpus says otherwise.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .schema import ROUND_TYPES

# A baseline computed from three examples is not a baseline. When a situation
# group is thinner than this, fall back to a coarser key rather than comparing
# a moment against itself — which produces an excess cost of exactly zero and
# silently drops a genuine moment off the list.
MIN_BASELINE_N = 12


def score_moments(model, states: pd.DataFrame, side: str = "ct") -> pd.DataFrame:
    """Attach a win-probability delta to every event in every round.

    delta is signed from `side`'s perspective: negative means the event cost
    them win probability.
    """
    st = states.sort_values(["match_id", "round_num", "event_idx"]).copy()
    wp_ct = model.predict(st)
    st["wp"] = wp_ct if side == "ct" else 1.0 - wp_ct

    st["wp_delta"] = st.groupby(["match_id", "round_num"])["wp"].diff()
    st["wp_before"] = st.groupby(["match_id", "round_num"])["wp"].shift()
    return st[st["wp_delta"].notna()].copy()


def _victim(df: pd.DataFrame) -> pd.Series:
    if "victim_side" in df.columns:
        return df["victim_side"]
    return pd.Series(None, index=df.index, dtype=object)


def pre_state(df: pd.DataFrame, side: str = "ct") -> pd.Series:
    """The man count going INTO each event, written from `side`'s point of view.

    Counts on a state row are post-event, so the player who just died is added
    back — to whichever side actually lost them. Rows where nobody died (the
    plant) leave both counts alone: the count going in is the count coming out.
    """
    victim = _victim(df)
    ct = df["alive_ct"] + (victim == "ct").astype(int)
    t = df["alive_t"] + (victim == "t").astype(int)
    us, them = (ct, t) if side == "ct" else (t, ct)
    return us.astype(int).astype(str) + "v" + them.astype(int).astype(str)


def describe(row, side: str = "ct") -> str:
    """One human-readable line for a moment."""
    if side == "ct":
        us, them = int(row.alive_ct), int(row.alive_t)
    else:
        us, them = int(row.alive_t), int(row.alive_ct)

    victim = getattr(row, "victim_side", None)
    if row.event_type == "death":
        # reconstruct the situation going in by putting the dead player back
        pre_us, pre_them = us, them
        if victim == side:
            pre_us += 1
            what = "duel lost"
        else:
            pre_them += 1
            what = "duel won"
        state = f"{pre_us}v{pre_them}"
    elif row.event_type == "plant":
        state = f"{us}v{them}"
        what = "bomb planted" if side == "t" else "bomb planted against you"
    else:
        state = f"{us}v{them}"
        what = row.event_type

    phase = "post-plant" if row.bomb_planted else "pre-plant"
    return f"{state} {phase} — {what}"


def _kind(df: pd.DataFrame, side: str) -> pd.Series:
    """What sort of moment this is, from `side`'s point of view.

    Losing a player, winning a duel and conceding a plant are three different
    things that cost three different amounts. Pooling them into one baseline
    is what made the old version wrong, so they are kept apart here.
    """
    victim = _victim(df)
    kind = pd.Series("other", index=df.index, dtype=object)
    kind[df["event_type"] == "plant"] = "plant"
    deaths = df["event_type"] == "death"
    kind[deaths & (victim == side)] = "loss"
    kind[deaths & victim.notna() & (victim != side)] = "trade"
    return kind


def add_excess_cost(scored: pd.DataFrame, side: str = "ct") -> pd.DataFrame:
    """Cost of a moment relative to what that situation normally costs.

    Ranking on raw wp_delta is a trap, and you will see it immediately in the
    output: every top moment comes back as a 1v1 post-plant duel. That is not
    insight, it is arithmetic — when one player remains, losing the duel loses
    the round, so the delta is always maximal and there is nothing to coach.

    Excess cost fixes it. For each situation type we compute what a moment of
    that kind typically costs, then rank by how much worse this instance was
    than that baseline. A 1v1 loss is exactly as bad as every other 1v1 loss,
    so it scores ~0 excess and drops out. What surfaces instead are the moments
    that were unusually expensive for the situation they happened in.

    The baseline key is (situation, phase, kind, position). All four matter:

      * SITUATION is the man count going IN, not the one left over. Because
        alive counts are post-event, a CT death landing at 4v4 came from 5v4
        while a T death landing at 4v4 came from 4v5. Keying on the leftover
        counts merges those two into one bucket.
      * KIND separates losing a player from winning a duel from conceding a
        plant. Merged, the wins cancel the losses and the baseline drifts
        toward zero — which makes every real loss look more excessive than it
        was, worst of all in exactly the man-advantage situations this list is
        supposed to be about. Measured on a 120-match synthetic corpus that
        error reached 18 points of win probability in the 5v3 bucket.
      * POSITION is where win probability stood going in. Without it the 1v1
        trap comes straight back one level up. When the last player on a side
        dies the round is over, so win probability goes to zero and the cost of
        that death IS whatever it was standing at — anywhere from 4% to 95%.
        Averaged into a single number, every 1v1 lost from a strong position
        scores an enormous excess for a reason that is pure arithmetic. So the
        baseline is a fit against position within the situation, not a mean
        over it, and a 1v1 lost at 93% is compared against what 1v1s lost at
        93% cost — which is 93%, so it scores ~0 and drops out.

    Situations thinner than MIN_BASELINE_N fall back to coarser company and
    finally to the kind's overall mean, so a small corpus still gets a real
    comparison instead of a moment measured against itself.
    """
    df = scored.copy()
    df["man_state"] = pre_state(df, side)
    df["kind"] = _kind(df, side)
    df["phase"] = df["bomb_planted"].map({0: "pre-plant", 1: "post-plant"})

    key = ["man_state", "phase", "kind"]
    n = df.groupby(key)["wp_delta"].transform("size")
    group_mean = df.groupby(key)["wp_delta"].transform("mean")

    # Within a situation, fit the cost against the position it happened from
    # rather than bucketing the position. Two parameters need far less data
    # than ten buckets do, which matters on a corpus of ten matches — and the
    # relationship really is close to linear, because the round ending caps
    # how far win probability can fall from where it stood.
    baseline = group_mean.copy()
    fitted = pd.Series(False, index=df.index)
    for _, idx in df.groupby(key).groups.items():
        g = df.loc[idx]
        if len(g) < MIN_BASELINE_N or g["wp_before"].std() < 1e-6:
            continue
        slope, intercept = np.polyfit(g["wp_before"], g["wp_delta"], 1)
        pred = intercept + slope * g["wp_before"]
        # never extrapolate past what this situation was actually observed to
        # cost — a fit is a summary of the group, not a licence to invent
        baseline.loc[idx] = pred.clip(g["wp_delta"].min(), g["wp_delta"].max())
        fitted.loc[idx] = True

    # Situations too thin to summarise fall back to coarser company, so a
    # moment is never compared against itself — which yields an excess of
    # exactly zero and silently drops a genuine moment off the list.
    coarse = ["man_state", "kind"]
    n_coarse = df.groupby(coarse)["wp_delta"].transform("size")
    thin = n < MIN_BASELINE_N
    baseline = baseline.where(~thin, df.groupby(coarse)["wp_delta"].transform("mean"))
    baseline = baseline.where(~(thin & (n_coarse < MIN_BASELINE_N)),
                              df.groupby("kind")["wp_delta"].transform("mean"))

    # How the comparison was made, so a report can say so rather than implying
    # more precision than the corpus supports.
    df["baseline_n"] = n.where(~thin, n_coarse).astype(int)
    df["baseline_thin"] = thin
    df["baseline_fitted"] = fitted

    df["expected_delta"] = baseline
    df["excess_cost"] = df["wp_delta"] - baseline
    return df


def top_moments(scored: pd.DataFrame, n: int = 5, side: str = "ct") -> pd.DataFrame:
    """The n moments that cost most, relative to their situation's baseline.

    Restricted to moments that actually went against this side: a player lost,
    or a bomb conceded. A duel you WON that still cost win probability is a
    model artifact — real, occasionally, but not something a coach can act on
    at practice, and it reads as nonsense on a report.
    """
    if "excess_cost" not in scored.columns:
        scored = add_excess_cost(scored, side=side)
    costly = scored[(scored["wp_delta"] < 0) & scored["kind"].isin(["loss", "plant"])]
    worst = costly.nsmallest(n, "excess_cost").copy()
    worst["situation"] = [describe(r, side) for r in worst.itertuples(index=False)]
    worst["cost_pct"] = (worst["wp_delta"] * 100).round(1)
    worst["excess_pct"] = (worst["excess_cost"] * 100).round(1)
    worst["typical_pct"] = (worst["expected_delta"] * 100).round(1)
    return worst[["match_id", "round_num", "seconds", "situation", "cost_pct",
                  "excess_pct", "typical_pct", "wp_before", "round_type_id",
                  "kind", "baseline_n", "baseline_thin"]]


def recurring_patterns(scored: pd.DataFrame, side: str = "ct",
                       min_count: int = 8) -> pd.DataFrame:
    """Total win probability lost, grouped by situation type across all matches.

    This is the feature a 2D replay viewer structurally cannot have: it opens
    one demo at a time, so a pattern spread across eleven matches is invisible
    to it. min_count guards against calling six rounds a trend.

    Only moments where this side lost a player are counted. A conceded plant
    costs win probability too, but it is a different kind of event, and filing
    it under a man-count label reads as a duel that never happened.
    """
    df = scored
    if "kind" not in df.columns:
        df = add_excess_cost(df, side=side)
    losses = df[(df["kind"] == "loss") & (df["wp_delta"] < 0)].copy()
    losses["round_type"] = losses["round_type_id"].map(dict(enumerate(ROUND_TYPES)))

    total = losses["wp_delta"].sum()
    g = (losses.groupby(["man_state", "phase", "round_type"])
                .agg(total_cost=("wp_delta", "sum"),
                     occurrences=("wp_delta", "size"),
                     avg_cost=("wp_delta", "mean"))
                .reset_index())
    g = g[g["occurrences"] >= min_count]
    g["total_cost_pct"] = (g["total_cost"] * 100).round(1)
    g["avg_cost_pct"] = (g["avg_cost"] * 100).round(2)
    g["share_of_losses"] = (g["total_cost"] / total * 100).round(1) if total else 0.0
    return g.sort_values("total_cost").drop(columns=["total_cost", "avg_cost"])
