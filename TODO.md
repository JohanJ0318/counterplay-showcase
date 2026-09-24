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
- [ ] Optional: have somebody qualified read `/privacy` and `/terms`. The
      pages no longer announce that nobody has; that was a fact about how they
      were written rather than about what they say, and it was the first line
      anybody forwarding the link read. What they claim is still checkable
      against the code, which is the part that matters if the deletion or
      sharing behaviour ever changes.

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
      1,681 FACEIT demo links could not be fetched: six of six returned 403
      or failed DNS. NOTE 2026-09-23: the 403s are almost certainly NOT
      expiry. demos-us-central1.faceit-cdn.net sits behind Cloudflare bot
      protection, which answers curl and urllib with 403 Cf-Mitigated:
      challenge and a real browser with an interstitial. faceit.head() uses
      urllib, so that test measured the bot block, not the file. Whether
      those demos still exist is UNKNOWN. Do not repeat "the spring is
      gone" as fact anywhere public.

- [ ] **The smoke line under Utility.** One sentence, removed at the same time:
      how many smokes nobody was inside, how many an opponent walked into, and
      how long those held the space first. The numbers behind it are still
      computed in `utility.space()` and still correct; only the sentence is
      gone.

## The decision engine

- [ ] **42 collegiate matches is not enough, and one seed said otherwise.**
      2026-09-24. tier=league cleared the calibration gate at 2.25x against
      a gate of 2.5x, on run.py default seed of 7. Refitting on eight seeds
      with tools/seedsweep.py: passed 3 of 8, ratio min 1.65, median 3.46,
      max 5.74. It fails. Seed 7 is one of the lucky three.

      README is right that the answer is matches and not code. 823 rounds
      and 7,202 state rows off 42 matches; run.py own summary says aim for
      a few hundred matches before trusting a retrain. 121 of the fall
      round robin are still undownloaded, in outreach/fall-2026-matches.csv.

      Do not quote a single-seed pass again. The margin at this corpus size
      is smaller than the spread between splits, which is what the seed
      sweep exists to show.

## Product gaps a coach will notice

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

- [ ] **The Team stats page is 5.9 MB**, because every zone map ships on every
      load.
- [ ] **HEAD returns 405 everywhere.** FastAPI's `APIRoute` does not add HEAD
      to a GET route the way plain Starlette does. Link unfurlers use GET so
      nothing on the outreach path is affected; uptime monitors and link
      checkers use HEAD, so a monitor pointed at the site would read it as
      down.

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

**A link preview**, 2026-09-21. The site had no `og:` tags at all, so the URL
about to be posted in the NECC Discord and mailed to thirteen coaches unfurled
as a line of grey text. There is a card now, `site/media/og.png`, drawn by
`makeog.py` in the dark palette and carrying one real reading with its
denominator. Deliberately not the video poster frame: that is gameplay footage
with ten strangers' Steam avatars along the top, which is somebody else's data
on our card.

The same tags are in the page shell, and **suppressed on `noindex` pages**. A
share link unfurling a team name into a Discord channel is the exact leak the
noindex is there to stop.

Set in Segoe UI and Consolas, because Space Grotesk and JetBrains Mono are not
installed on this machine. Drop either `.ttf` into `design/fonts/` and re-run
`makeog.py` and it picks them up.

**`/robots.txt` and `/sitemap.xml`**, same day. Both 404'd. Six pages are
public; the other thirty routes want a session or a token, and `/zones.html`
is 6.4MB of zone-naming tool nobody outside the box has a use for.

**The print stylesheet**, same day. What came out of a printer used to be the
screen: a black page if the reader had picked dark, the sticky contents bar
stamped on top, an upload button nobody can press on paper, and every table
wider than the sheet cut off at the margin. It forces the light palette,
naming `[data-theme="dark"]` explicitly because that selector is one point
more specific than `:root` and would otherwise win. Tables print at .72rem
with 8px gutters, which takes the roster from 925 pixels to 644 and fits it on
a sheet: letting a scroll container overflow is not the same as making it fit,
and on paper the columns past the edge are not scrolled away, they are gone.

**The table scroll hint**, same day. The charts said "scroll sideways" and the
tables, which are wider and matter more, said nothing. The class is set by
script from the element's real overflow rather than from a breakpoint, for the
same reason `rate()` will not print a percentage off four rounds: on the live
sample report at 375px that is eight of ten tables, and a hint under the two
that fit is a hint a reader learns to ignore. It clears at the right edge and
comes back on the way left.

**The Monday advice on the dashboard**, same day. It was two clicks away on
Team stats while the first screen opened with six feature cards, two of them
"coming". The top three findings are on the dashboard now, under "read this
one first", with a link through to the full plan grouped by map. `advice_card`
was lifted out of the Team stats closure so both pages draw the same card; two
renderings of one recommendation is two things to keep in step, and the one on
the smaller page is the one that would have drifted.

The cost moved rather than grew: the dashboard is 0.9s cold and 5ms warm,
because `monday`'s expensive parts are already `@memo.by_team` and the
dashboard now warms the cache that Team stats reads. Do NOT put `@memo.by_team`
on `monday` itself. It was tried and it turned 14 tests in `test_advice.py`
red: those tests never write to the demos table, so `memo.version()` returns
the same stamp for every one of them and the cache hands back the first test's
answer.
