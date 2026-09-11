# What is left

Kept here rather than in a chat window, because a reminder that only exists in
a conversation is not a reminder.

Ordered by what it costs you if it does not get done.

## Do this next

- [ ] **Push to a private GitHub repo.** Eighteen commits exist on one laptop
      and nowhere else. A dead disk is the whole product. It also switches on
      the CI in `.github/workflows/tests.yml`, which has never run because
      there is no remote to run it on. About twenty minutes.

      ```
      gh repo create counterplay --private --source=. --remote=origin --push
      ```

## Before emailing coaches

- [ ] **A postal address for the outreach email footer.** Required by CAN-SPAM
      in commercial email. Not required on the website, not required in a
      password reset. A PO box or virtual mailbox is the normal answer. See
      `deploy/outreach-email.md`.
- [ ] **Check the send list against the `unsubscribes` table.** Query is in the
      same file.
- [ ] Optional: have somebody qualified read `/privacy` and `/terms`, then set
      `COUNTERPLAY_LEGAL_REVIEWED=1` to drop the draft banner.

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
      still on the pre-collision-fix `match_key` scheme.
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
