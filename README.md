# Counterplay v1: the decision engine

Scores CS2 rounds by win probability and returns the moments that cost the most.
Not a replay viewer: it does not show you the match, it tells you which seconds
of it were expensive.

```bash
pip install -r requirements.txt

python run.py --synth              # prove the pipeline works, no demos needed
python run.py --demos ./demos      # run it on your own .dem files
```

## Status

| Module | State |
|---|---|
| `schema.py` | Feature contract. Tested. |
| `state.py` | Event-driven round state reconstruction. Tested. |
| `synth.py` | Synthetic round generator for validation. Tested. |
| `model.py` | Win probability + calibration. Tested across 4 data sizes. |
| `rank.py` | Moment ranking + recurring patterns. Situation keying rebuilt, see below. |
| `parse.py` | Real demo parsing. **Validated against a Valve MM demo (de_dust2).** |
| `validate.py` | 13 sanity checks on parsed output. Tested against 4 injected bugs. |

Whole pipeline runs end to end on a real demo: 13/13 validation checks pass,
20 rounds parsed, score read correctly.

```bash
python run.py --demos ./demos --check-only      # validate parsing
python run.py --demos ./demos --train-on-synth  # score a few real matches
python run.py --demos ./demos                   # once you have hundreds
```

`--train-on-synth` exists because training and scoring are different jobs. One
match will never support training a model, but it is plenty to *score*. In
production you fit once on a large corpus and score every customer's matches
with it. Retrain on real matches once you have a few hundred.

## Tiers

Every round is labelled with the population it came from:

```
pro · collegiate · league · premier
```

These are not arbitrary skill buckets. They are the customer segments. The same
4v2 retake is a very different proposition in tier-1 CS than in solo-queue
Premier, and a model that averages them is wrong for everybody. Conditioning on
tier lets one model serve all four honestly.

Keep one tier per directory so the label is structural rather than something you
have to remember:

```
demos/pro/        python run.py --demos demos/pro --tier pro
demos/collegiate/ python run.py --demos demos/collegiate --tier collegiate
demos/league/     python run.py --demos demos/league --tier league
demos/premier/    python run.py --demos demos/premier --tier premier
```

Your own matchmaking games are `premier`. Mislabelling a pro match as premier
teaches the model that Premier players retake like professionals, and every
number it gives your customers inherits that.

## Three decisions worth understanding before you change anything

**1. State comes from events, not ticks.** A round becomes ~12 rows instead of
~7,000. Win probability only moves when someone dies or the bomb goes down, so
tick-level positional data buys the model nothing. Positions are needed later
for the 2D snapshot, and nowhere else. This is what makes the whole thing run on
a $6 VPS.

**2. Calibration is gated relative to a noise floor.** When the model says 30%,
that side must win about 30% of the time, because otherwise every number you show a
coach is a lie. Two traps here, both of which this code hit during development:

- *Max-error-across-bins is a noisy statistic.* A **perfectly** calibrated model
  measured on 7,700 rows scores ~0.034 on it from sampling noise alone. Gating
  at 0.05 means gating on your test-set size. The code reports it as a
  diagnostic only.
- *A fixed ECE threshold silently becomes stricter as data shrinks.* So the gate
  is a multiple of `null_calibration_floor()`, the ECE a perfect model would
  score on your row count. Uncalibrated lands 4–7x the floor, calibrated ~2x.

Raw LightGBM is reliably overconfident here, so the booster is wrapped in an
isotonic calibrator fitted on a **third, disjoint split**. All splits are by
match, never by row, because rows within a round are correlated and a random split
leaks.

**3. Moments rank by excess cost, not raw cost.** Rank on raw win-probability
delta and every top moment comes back a 1v1 post-plant duel. That is arithmetic,
not insight: with one player left, losing the duel loses the round, so the delta
is always maximal and there is nothing to coach. Excess cost compares each
moment against what that situation type normally costs, so 1v1s score ~0 and
drop out. What surfaces instead are 3v1 and 2v1 post-plant losses, rounds you
were winning comfortably and threw. Those are coachable.

Getting that comparison right took three goes, and the two failed ones are
worth knowing about because both produced a plausible-looking list:

- *The situation label was built from post-event counts.* Alive counts on a
  state row already have the dead player removed, so `alive_ct + 1` is only the
  right label when a CT died. A T death landing at 4v4 came from 4v5, not 5v4,
  and both were being filed under the same key, along with the plant, where
  nobody died at all. Each bucket ended up a mixture of losses and wins, and
  averaging them dragged the baseline toward zero. On a 120-match synthetic
  corpus the error reached 18 points of win probability, worst in exactly the
  man-advantage buckets this list is supposed to be about. The list looked
  right; it was right by accident.
- *Fixing that surfaced the 1v1 trap one level up.* When the last player on a
  side dies, win probability goes to zero, so the cost of that death IS whatever
  it was standing at, anywhere from 4% to 95%. Compared against one average
  over all of them, every 1v1 lost from a strong position scores an enormous
  excess, for a reason that is still pure arithmetic.

So the baseline is keyed on (situation, phase, kind) and, within that, fitted
against the position it happened from rather than averaged over it. `kind`
separates losing a player from winning a duel from conceding a plant. Two fitted
parameters need far less data than bucketing the position would, which matters
on a ten-match corpus. Every moment reports how many comparable moments its
baseline came from, and says so when the situation was too thin and it fell back
to coarser company.

## Deliberately not here

- **Per-player blame.** Five players act at once and the attribution heuristics
  are fragile. A wrong name in a team tool is worse than no name. The coach
  already knows who was there; they lack the time to find the moment.
- **Counterfactuals** ("you should have held connector"). Genuinely hard
  research, and the most likely place for this project to stall out and die.
- **A 2D replay viewer.** That is the product you are competing against.

Both of the first two are v3, once someone is paying.

## Getting parse.py working: the actual procedure

`parse.py` is the translator. Everything else in this package speaks one
language (rounds and events) and this is the only module that knows how to
turn a `.dem` into it. It is also the only module that talks to the outside
world, which is why it is the one most likely to be wrong.

### Step 1: get demos

Easiest first source is your own matches, no API and no permissions needed:

- **CS2 client** → Watch → Your Matches → Download. Premier and competitive
  games, roughly 100–250 MB each.
- **FACEIT** → any match room → download demo.
- **HLTV** → pro matches, free, good for bulk training data later.

Five of your own matches is enough to get parsing right. You need a few hundred
before the model means anything.

### Step 2: see what your demos actually contain

```bash
python -m counterplay.parse --inspect yourdemo.dem
```

This prints the header, every event name the demo exposes, and the columns on
the four events we care about. **Compare that output against `parse.py` and fix
the field names.** They are reasonable guesses, not verified facts.

### Step 3: validate before you train

```bash
python run.py --demos ./demos --check-only
```

This runs 13 checks that must hold for any real Counter-Strike match, and stops
before training. Parsing fails silently far more often than it raises, and a model
trained on a bad parse is confidently wrong rather than obviously broken, which
is much worse.

### What the real demo taught us

Four assumptions in the first draft were wrong. Every one of them would have
failed silently, because the parser returns a dataframe either way and the model
trains happily on garbage. This is why `validate.py` exists.

| Assumption | Reality |
|---|---|
| There is a `round_end` event with a `winner` column | **There is no `round_end` event at all.** CS2 exposes `round_officially_ended`, `round_freeze_end`, `round_prestart`, `round_poststart`, and every one of them carries *only* a `tick` column. The winner lives in tick data as `round_win_status` (2 = T, 3 = CT), read a couple of ticks before the official end. |
| `total_rounds_played` identifies the round | It has already incremented by the time you read it near the round end, so every round lands one ahead of its own deaths. Read it at the **freeze-end** tick instead. |
| `round_start_equip_value` is the round's buy | Lagged by a full round. Use **`current_equip_value` at freeze-end**, what players are actually holding as the round goes live. |
| Events can be assigned to rounds by `total_rounds_played` | It lags across boundaries. Two bomb plants came back tagged to the same round. Map by **tick interval** instead. |

And one more, found only because a check failed: **rounds are closed intervals.**
A round runs freeze-end → official end, and the gap before the next freeze
belongs to neither. Players keep shooting after the round is decided, so
treating the round as open-ended puts six deaths on a five-player side.

Field names that *were* correct: `team_num` (2 = T, 3 = CT), `user_team_num` on
`player_death` when requested via `player=["team_num"]`, and a 64 tick rate.

### Step 4: then train

```bash
python run.py --demos ./demos
```

If the calibration gate fails, you need more matches, not different code. The
message tells you how far above the noise floor you are.

## The web app

    pip install -r requirements.txt
    python -m app                       # http://127.0.0.1:8000

FastAPI over SQLite, with the standard library doing the rest: `hashlib.scrypt`
for passwords, `secrets` for session tokens, `sqlite3` with no ORM. Same reason
as the engine: it has to run on a $6 VPS, and a season of a college league is
tens of thousands of rows, not millions.

| Route | What it does |
|---|---|
| `/` | the marketing page, served from `site/` |
| `/league/` | the generated league site |
| `/signup`, `/login`, `/logout` | real accounts |
| `/dashboard` | plan, demo counts, upload, and what each feature reaches |
| `/team/{slug}` | roster and demos, 403 to anyone not on the team |
| `/pricing` | generated from `app/plans.py`, not written by hand |
| `/api/lead` | the landing page's form, into the `leads` table |

**`app/plans.py` is the foundation.** Plans sit on one ladder and features
declare the rank at which each depth unlocks, so the pricing page and the gate
read from the same table and cannot disagree. Access is a level rather than a
boolean (`NONE`, `CORE`, `FULL`) because most of these features exist at two
depths and modelling that as on/off means either giving away the paid half or
hiding the thing that sells it.

    free  <  pro  <  team_t3  <  team_t2  <  team_t1

Tier 1 is the top, following how tiers are numbered in Counter-Strike rather
than in software. Only Team Tier 3 has a price (€29.95/mo); the rest render as
"price not set" rather than as free, so nobody signs up for a tier at €0 by
accident. Set `price_eur_month` in `app/plans.py` before the page goes public.

Security decisions worth not undoing: session cookies are stored as their
SHA-256 so a database backup is not a set of live logins; the login path hashes
a dummy password when the account does not exist so timing cannot enumerate
accounts; CSRF failures are rejected rather than ignored; and `Secure` is on the
session cookie unless `COUNTERPLAY_INSECURE_COOKIES=1` says this is a local run.

**Not done yet:** email verification generates a token but sends nothing, so there
is no SMTP configured. Uploaded demos land in `data/demos/` with status
`pending`; nothing parses them yet, which is the obvious next piece of wiring
between the app and `counterplay/parse.py`.

## Ingestion

    python -m app.pull --cache <fetch.py cache> --check     # are the links live?
    python -m app.pull --cache <fetch.py cache>             # queue them
    python -m app.worker --once                             # parse the queue
    python -m app.corpus                                    # what you have
    python run.py --db                                      # train on it

Demo → rows, in one path:

    download → decompress (.dem.zst) → parse.py → validate.py → tables → delete

**Demos are kept, compressed.** The whole NECC corpus is roughly 100-140GB as
`.dem.zst`, a few euro a month, and there are three reasons not to save it:

  * FACEIT deletes match demos after a few weeks. One dropped here is gone.
  * `schema.py` has ten features. Adding an eleventh means re-parsing everything
      `python -c "from app import ingest; ingest.reparse_all()"` replays the
    corpus through new code. Without the files, every future feature is limited
    to matches played after you thought of it.
  * A 2D replayer needs positional data this pipeline does not extract yet.

What is *not* kept is the decompressed `.dem`, which is 3-4x larger and needed only while
the parser reads it. Uploaded raw demos are compressed after a successful parse.
`COUNTERPLAY_RETAIN` takes `all` (default), `owned`, or `none`, and
`ingest.forget_team()` deletes a team's files and rows outright, which is the
landing page's "ask us to delete your data" promise.

A demo that fails to parse is **also kept**, because that is exactly the file you need
when you fix `parse.py`.

**A demo that fails validation is not stored.** `validate.py` runs before the
insert and a failure marks the demo `failed` with the reason. A bad parse in the
corpus is worse than a missing one: the model trains on it happily and comes out
confidently wrong instead of obviously broken.

`demoparser2` is a Rust extension, and a malformed demo makes it *panic* rather
than raise. pyo3 surfaces that as `PanicException`, which inherits from
`BaseException`, so `except Exception` does not catch it and one truncated file
kills the worker mid-corpus. `parse_to_frames` catches `BaseException` for that
reason; it is not defensive padding.

Parsing runs in `app/worker.py`, a separate process, one demo at a time. The
constraint is RAM, not CPU: a 250MB demo is gigabytes to parse, and two at once
on a 4GB box meets the OOM killer. Uploads land as `pending` and the worker
picks them up; nothing parses inside a web request.

### Where demos come from

`api.faceit.com/match/v2/match/{id}` returns `demoURLs` with **no API key and no
login**. The authenticated Data API works too: it returned 200, with `demo_url`,
for a match we did not organise. An earlier note here said it 403s in that case.
It does not. That 403 was Cloudflare, and **where you call from decides
everything**. See "FACEIT is behind Cloudflare" in CLAUDE.md. `league/gen/fetch.py` also already cached
`demo_url` for every match it saw (1,681 links across 780 NECC matches) which
`build.py` never used.

### The rule about whose data this is

League-pulled demos are inserted with `team_id = NULL` and `source = 'league'`.
They build **aggregate baselines**: situation rates by map, side and tier. A
team that never signed up never gets a profile, a page or a report built from
them. `corpus.load_frames(team_id=...)` is the only way to scope to one team's
matches, and it can only return matches attributed to a team that has an
account. `db.claim_demo()` is the only sanctioned way a demo gains a team.

Not built yet: matching a signed-up team to its FACEIT team id so its own league
matches are attributed automatically. That is what lets a coach get a full season
report without uploading anything, and it needs the team ids off the match detail,
which are fetched but not stored.

## Next

1. Get parsing clean, all 13 checks passing.
2. Retrain on real rounds and confirm the calibration gate still passes.
3. **Read the top-five output and decide honestly whether it makes you say
   "that's right."** You have the game knowledge to judge this, which is the
   whole reason you are the one building it.
4. Only then write the web app.

If the list is not good, no frontend saves it, and you will have found out at
40 hours instead of 100.
