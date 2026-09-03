#!/usr/bin/env python3
"""Counterplay v1 — end to end.

    python run.py --synth              # prove the pipeline on synthetic rounds
    python run.py --demos ./demos      # run it on real .dem files

Stop and read the output before you write any web app. If this list isn't
good, no frontend saves it.
"""
from __future__ import annotations

import argparse
import sys

from counterplay.model import train
from counterplay.rank import (add_excess_cost, recurring_patterns,
                              score_moments, top_moments)
from counterplay.state import build_states
from counterplay.validate import report as validate_report

SIDE = "ct"


def banner(t):
    print(f"\n{'=' * 66}\n{t}\n{'=' * 66}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--synth", action="store_true", help="use synthetic rounds")
    ap.add_argument("--demos", type=str, help="directory of .dem files")
    ap.add_argument("--db", action="store_true",
                    help="train on the corpus already parsed into the database "
                         "by the ingest worker")
    ap.add_argument("--tier", type=str, default="premier",
                    choices=["pro", "collegiate", "league", "premier"],
                    help="which population these demos came from")
    ap.add_argument("--matches", type=int, default=120)
    ap.add_argument("--check-only", action="store_true",
                    help="validate parsing and stop, without training")
    ap.add_argument("--train-on-synth", action="store_true",
                    help="train on the synthetic corpus, score your real demos. "
                         "Use this until you have a few hundred real matches — "
                         "one match is nowhere near enough to train on, but it "
                         "is plenty to score.")
    args = ap.parse_args()

    if args.synth:
        from counterplay.synth import generate
        rounds, events = generate(n_matches=args.matches, tier=args.tier)
        print(f"synthetic: {len(rounds)} rounds, {len(events)} events")
    elif args.db:
        from app import corpus, db as appdb
        appdb.init()
        corpus.print_summary()
        rounds, events = corpus.load_frames(tier=None)
        if rounds.empty:
            ap.error("nothing parsed yet — run: python -m app.worker --once")
        print(f"\nloaded: {len(rounds)} rounds, {len(events)} events")
    elif args.demos:
        from counterplay.parse import parse_directory
        rounds, events, _players = parse_directory(args.demos, tier=args.tier)
        print(f"parsed: {len(rounds)} rounds, {len(events)} events")
    else:
        ap.error("pass --synth, --demos or --db")

    # Always validate real demos before trusting them. Parsing fails silently
    # far more often than it raises, and a model trained on a bad parse is
    # confidently wrong rather than obviously broken.
    if args.demos or args.db or args.check_only:
        banner("PARSE VALIDATION")
        if not validate_report(rounds, events):
            sys.exit(1)
    if args.check_only:
        return

    states = build_states(rounds, events)
    print(f"states:  {len(states)} rows")

    # Training and scoring are separate jobs. In production you fit the model
    # once on a large corpus and then score each customer's matches with it —
    # you never retrain per user, and a single match could never support it.
    banner("WIN PROBABILITY MODEL")
    synthetic_gate = args.train_on_synth
    if args.train_on_synth:
        from counterplay.synth import generate
        cr, ce = generate(n_matches=200, tier=args.tier)
        model, report, _ = train(build_states(cr, ce))
        print("  trained on synthetic corpus, scoring your demos")
        print("  (probabilities are structurally right but not yet true to real "
              "CS — retrain on real matches when you have them)\n")
    else:
        model, report, _ = train(states)
    print(report)
    if synthetic_gate:
        # The gate above was measured on a held-out split of the SYNTHETIC
        # corpus, because that is what the model was fitted on. It says the
        # model is calibrated to the simulator. It says nothing about whether
        # it is calibrated to your demos, and it cannot: the data being scored
        # has no labels to check against. Do not read a PASS here as evidence
        # about real matches.
        print("\n  NOTE: this gate was measured on synthetic data, which is what "
              "the\n  model was trained on. It says the model is calibrated to the "
              "simulator\n  — not to your matches. Nothing here has been checked "
              "against a real\n  round. Retrain on real demos before quoting any of "
              "these percentages.")
    if not report.passes:
        print("\n  Calibration failed. The numbers below would be dishonest.")
        print("  If you are training on a handful of matches, this is expected:")
        print("  you need more data, not different code. Try --train-on-synth.")
        sys.exit(1)

    scored = add_excess_cost(score_moments(model, states, side=SIDE), side=SIDE)

    banner(f"FIVE MOST EXPENSIVE MOMENTS ({SIDE.upper()} side)")
    for i, m in enumerate(top_moments(scored, 5, side=SIDE).itertuples(index=False), 1):
        print(f"\n  {i}. {m.match_id} · round {m.round_num} · {m.seconds:.0f}s")
        print(f"     {m.situation}")
        print(f"     {m.cost_pct:+.1f}% win probability (from {m.wp_before * 100:.0f}%)")
        thin = "  [thin baseline]" if m.baseline_thin else ""
        print(f"     {m.excess_pct:+.1f}% vs typical for this situation "
              f"({m.typical_pct:+.1f}% over {int(m.baseline_n)} comparable "
              f"moments){thin}")

    banner(f"RECURRING PATTERNS ({SIDE.upper()} side)")
    pats = recurring_patterns(scored, side=SIDE).head(6)
    print(f"\n  {'situation':<26} {'occ':>5} {'total':>9} {'avg':>8} {'share':>7}")
    print(f"  {'-' * 26} {'-' * 5} {'-' * 9} {'-' * 8} {'-' * 7}")
    for p in pats.itertuples(index=False):
        sit = f"{p.man_state} {p.phase} {p.round_type}"
        print(f"  {sit:<26} {p.occurrences:>5} {p.total_cost_pct:>8.0f}% "
              f"{p.avg_cost_pct:>7.1f}% {p.share_of_losses:>6.1f}%")
    print()


if __name__ == "__main__":
    main()
