<p align="center"><img src="site/media/og.png" width="720" alt="Counterplay: your matches, actually read"></p>

# Counterplay

**Match analysis for collegiate Counter-Strike 2 teams. Live at [counterplaycs.com](https://counterplaycs.com).**

A coach uploads their team's match demos and gets back player and team statistics, a
report for every match, and the patterns the team repeats without deciding to. It is not
a replay viewer. It reads the match and says which seconds of it were expensive, and every
number on the page carries the rounds it came from, so a coach can open the demo and check.

Built and run solo by Johan Johnson, September 2026 onward: data pipeline, models, web app,
deployment and the first conversations with coaches.

> This repository is a portfolio snapshot of the product's source and its full commit
> history. Deployment configuration, operating notes and customer contact material are not
> included. All rights reserved; see [LICENSE](LICENSE).

---

## What it does

- **Parses raw demo files** as they arrive from FACEIT or Valve matchmaking (zstd, gzip
  and bzip2 packing detected by magic number, never by file extension).
- **Reconstructs each round from events**, not ticks: about 12 rows per round instead of
  about 7,000. Win probability only moves when someone dies or the bomb goes down, which is
  why the whole thing runs on a single small server.
- **Checks every parse** with 13 automated validations before anything reaches a page.
- **Reads the season**: per-player and per-team rates, opening duels, trades, utility,
  buys, and a zone map of where a team's rounds are decided.
- **Judges a team against collegiate teams in the same spot**, with an exact binomial test,
  so it flags only differences the data can support.
- **Shares and hands over**: read-only share links, and a one-time link that transfers a
  team built from a coach's public demos to that coach's own account.

## How it fits together

```mermaid
flowchart LR
    U[Coach uploads demo] --> W[FastAPI app]
    W --> Q[(SQLite)]
    Q --> K[Background worker]
    K --> P[Parser: demoparser2<br/>events to round state<br/>13 validation checks]
    P --> Q
    Q --> R[report.py: every reading<br/>rates with denominators]
    R --> W
    subgraph Offline, on the collegiate corpus
        C[(138 collegiate matches)] --> M[LightGBM win probability<br/>+ isotonic calibration]
        C --> B[Collegiate benchmarks<br/>league_rates.json, benchmark.json]
        C --> E[Economy curve<br/>with team-strength control]
    end
    M --> R
    B --> R
    E --> R
```

## The machine learning, and the decisions behind it

The model work is deliberately boring in architecture and careful in evaluation. The
longer write-up is in [docs/decision-engine.md](docs/decision-engine.md); the short version:

- **Gradient-boosted trees on tabular features, not a sequence model.** What matters is not
  accuracy but **calibration**: when the model says 30%, that side must win about 30% of the
  time, or every number shown to a coach is wrong. Raw LightGBM is overconfident at the
  extremes here, so it is wrapped in an isotonic calibrator fitted on a third, disjoint split.
- **Every split is by match, never by row.** Rows within a round are highly correlated, and
  a random split leaks and flatters every metric.
- **Calibration is gated against a measured noise floor**, not a fixed threshold. A
  perfectly calibrated model still scores about 0.034 on max-bin error from sampling noise
  alone on 7,700 rows, so a fixed gate mostly measures test-set size. Expected calibration
  error is compared to the error a perfect model would show at the same row count.
- **Measured honestly across 20 seeds.** On 138 maps the model clears its gate on 10 of 20
  seeds (median 2.33x the floor). More data did not close the gap, which says the remaining
  miscalibration is real, and [TODO.md](TODO.md) records the investigation rather than a
  single lucky seed.
- **Moments are ranked by excess cost, not raw cost.** Ranked on raw win-probability change,
  every top moment is a lost 1v1, which is arithmetic, not insight. Comparing each moment
  with what that situation normally costs surfaces the coachable ones instead: 3v1 and 2v1
  post-plant rounds a team was winning and threw. Getting that baseline right took three
  attempts; both failures are written up.
- **The economy model is one learned curve plus measured rules.** P(win) from the two sides'
  equipment ratio, fitted with a team-strength control (89% of the slope survives it,
  because a better team is also a richer one). Money rules were measured off demos rather
  than remembered, and each buy call is simulated over the rest of the half.
- **Missing data is unknown, not a miss.** Some demos carry no blind events; treating every
  flash in them as blinding nobody produced false advice, so those matches are excluded from
  flash figures and from the reference they are judged against.

## The engineering

- **FastAPI and SQLite on one Linux server**, HTTPS through Caddy. Password hashing, session
  tokens and the database come from the standard library on purpose.
- **Numbered schema migrations** run on startup (schema version 25).
- **A background worker** parses uploads, polls in a loop and requeues anything abandoned
  mid-parse.
- **Pages are server-rendered** with inline CSS and no build step; the homepage is about
  30KB. Charts never scroll sideways on a phone.
- **264 automated tests** (pytest) run in GitHub Actions on every push. Many of them exist
  because a specific bug shipped once: an undefined CSS token, a duplicate-demo guard that
  skipped across teams, a coach counted as a player.
- **About 165 commits** in this history, each describing what changed and why.

## Repository map

```
app/            Web app: routes and pages (main.py), every reading (report.py),
                positional analysis (movement.py), migrations, worker, auth, mail
counterplay/    Parser and models: parse.py, model.py (win probability), rank.py,
                economy.py, zones and the walked zone model
league/gen/     Generator for the league statistics site (FACEIT data)
tools/          Measurement scripts: calibration checks, seed sweeps, benchmarks
tests/          264 tests
docs/           The decision engine write-up
```

## Running it locally

```bash
pip install -r requirements.txt
python run.py --synth          # the full pipeline on synthetic rounds, no demos needed
python -m pytest -q            # the test suite
```

The match corpus and the production database are not part of this repository.

## License

Copyright (c) 2026 Johan Johnson. All rights reserved. The source is published for viewing
as part of a portfolio; no permission is granted to copy, modify, or use it. See
[LICENSE](LICENSE).
