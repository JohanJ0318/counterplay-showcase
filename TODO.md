# What is left

Kept here rather than in a chat window, because a reminder that only exists in
a conversation is not a reminder.

Ordered by what it costs you if it does not get done.

## Before emailing coaches

- [ ] **A postal address for the outreach email footer.** US law on commercial
      email requires a real mailing address inside the message, so a stranger
      can tell who actually sent it. Not required on the website, not required
      in a password reset, which is transactional and exempt. A home address
      is legal and publishes where you live to every coach on the list; a PO
      box or a virtual mailbox is the normal way round that. The template is
      ready apart from this one placeholder. See `deploy/outreach-email.md`.

      **This is the only thing standing between here and sending.**

- [ ] **Check the send list against the `unsubscribes` table.** Query is in the
      same file. The table is empty today, so there is nothing to strike off
      the first send.
- [ ] Optional: have somebody qualified read `/privacy` and `/terms`, then set
      `COUNTERPLAY_LEGAL_REVIEWED=1` to drop the draft banner.

## Now that CI runs

The first push turned it on and it went red immediately: fifteen failures,
every one of them from the same day's work, all fixed in the same sitting. Two
were worth the scare. `memo.version()` asked the demos table what version the
data was at and raised where there was no schema, which made a cache the
reason a call failed rather than an optimisation on top of one; it returns
None now and the caller computes uncached. And `test_advice.py` was asserting
that a place is judged against the season average, which had stopped being
true on purpose.

- [ ] **Keep it green.** The suite covers the parser, the advice engine, resets
      and imports. It does not cover `report.py`, `movement.py`, either
      `utility.py`, `charts.py` or page rendering, and a rendering test would
      have caught the "gap of 19 points across 745200 rounds" bug before it
      shipped.
- [ ] **Watch for `data/` drifting into the repo.** `.gitignore` keeps out the
      database, the demos, the backups, Valve's radar artwork and the 27MB
      FACEIT cache. The push was checked and carried none of them. It carries
      `site/media/loop.mp4` at 5.9MB, which is deliberate.

## Built, and deliberately not on a page

- [ ] **Smoke calls.** `app/smokes.py`, with tests, and nothing imports it.
      Finds the smokes a team throws at the same spot repeatedly and reports,
      per call: what it was for (execute, lurk, retake, map control, read off
      the thrower's distance to his own side and the plant), how far each throw
      lands from the team's own median for that call, and which spots the
      opposing sides in the same demos also use.

      Taken off the team stats page on 2026-09-11 because it was too much page
      for what it could honestly claim. `git show 96f1acd` is the rendering, and
      `git show cd4f733` the first version of it; both revert cleanly.

      Before it goes back, the thing it needs is not code. It is repetitions of
      the SAME call, so good executions can be compared against bad ones with
      the plan held constant. Eleven matches gives six calls worth printing and
      splits of 7 against 12. The `app/pull.py` cache cannot supply more: its
      1,681 FACEIT demo links have expired, six of six dead on 403 or DNS.

- [ ] **The smoke line under Utility.** One sentence, removed at the same time:
      how many smokes nobody was inside, how many an opponent walked into, and
      how long those held the space first. The numbers behind it are still
      computed in `utility.space()` and still correct; only the sentence is
      gone.

## Product gaps a coach will notice

- [ ] **The dashboard is a brochure.** Six feature cards, two of them "coming",
      are the first thing a returning coach sees. The Monday advice, the most
      useful thing in here, is two clicks away on Team stats. They should swap.
- [ ] **Utility has no map or side split.** "67% of your flashes blind your own
      side" is a good line, and the next three questions are which map, which
      side, which player. None are answerable.
- [ ] **No opponent view.** Before playing a team again you want what happened
      last time. The data is keyed by match and there is no way in.
- [ ] **Nothing separates a scrim from an official match.** They average
      together, and they are different habits.

## Engineering

- [ ] **`main.py` is 2,243 lines**, a quarter of it embedded HTML.
- [ ] **No tests for** `report.py`, `movement.py`, either `utility.py`,
      `charts.py`, or page rendering. 101 tests cover the parser, the advice
      engine, resets and imports. A rendering test would have caught the
      "gap of 19 points across 745200 rounds" bug before it shipped.
- [ ] **The server is not a git checkout.** Deploys are file copies and drift
      has already happened twice: a stale `build.py`, and the whole database
      still on the pre-collision-fix `match_key` scheme. Now that there is a
      remote, `git pull` on the box is a possible deploy instead.
- [ ] **The bundle on the server is a snapshot, not a mirror.**
      `/srv/counterplay/data/repo/counterplay-*.bundle` holds the whole history
      as of the day it was written and is not in `backup.sh`, which copies the
      database only. GitHub is the real backup; that file is a second copy that
      ages.
- [ ] **The server holds two demo files**, so no schema change can be replayed
      there. Every one needs hand-shipped SQL. That has happened three times.

## Interface

- [ ] **No favicon.** The tab is a blank page icon next to Leetify's logo.
- [ ] **Tables scroll sideways on mobile with no hint.** The charts say so; the
      tables, which are wider and matter more, say nothing.
- [ ] **No print stylesheet.** Coaches print things for team meetings.
- [ ] **The Team stats page is 5.9 MB**, because every zone map ships on every
      load.

## Done

Password reset and mail, zone naming locked to admins, privacy and terms,
unsubscribe, verified nightly backups, dark mode across all three surfaces,
utility measured by outcome, first deaths carrying whether they were traded,
and no em dashes anywhere a coach can see.

**Pushed to a private repo**, 2026-09-14: `JohanJ0318/counterplay`, 49 commits,
checked for a stray database or key and carrying none. CI ran for the first
time on that push.

**The smoke test run against production**, same day, with a real 106MB demo:
24 passed, 0 failed. The upload took 42 seconds through Caddy and the worker
parsed it in 10, while the live site kept answering in the same 0.43s it
answers in the rest of the time. That was the one path nothing had exercised
since every database query started reusing a connection. The two throwaway
accounts it leaves behind were deleted afterwards, rows only: the demo file it
uploaded is stored by hash and is byte for byte the corpus demo already on the
box, so deleting the file would have orphaned a demo that had nothing to do
with the test.

**A favicon**, drawn sharp at 16, 32, 48 and 64 rather than downsampled from
one big frame.
