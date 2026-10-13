# What is left

Kept here rather than in a chat window, because a reminder that only exists in
a conversation is not a reminder.

Ordered by what it costs you if it does not get done.

## Before emailing coaches

- [x] **A postal address for the outreach email footer.** Filled in; the
      first five emails went out with it on 2026-09-23 (`outreach/send.txt`).

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

- [ ] **More matches is NOT the lever. Retracted, 2026-09-24.**
      Three corpus sizes now, same eight seeds each time so the rows compare:

      | same 8 seeds | 42 maps | 88 maps | 138 maps |
      |---|---|---|---|
      | passing | 3 of 8 | 6 of 8 | 4 of 8 |
      | ratio median | 3.46 | 1.79 | 2.53 |
      | ECE median | 0.0293* | 0.0293 | 0.0310 |
      | floor median | 0.0164* | 0.0164 | 0.0126 |
      | AUC median | ~0.84 | ~0.844 | 0.8615 |

      88 to 138 maps changed the model's actual calibration error by nothing:
      0.0293 to 0.0310, against a per-seed spread of 0.012 to 0.041. The whole
      move in the ratio is the denominator. Test rows went 3,897 to 6,198,
      ratio 1.59, and the floor shrinks as 1/sqrt(n): sqrt(1.59) = 1.26,
      observed floor ratio 1.30. That accounts for all of it.

      What 50 more maps DID buy is discrimination: AUC median 0.844 to 0.8615,
      top end 0.8820. The booster is learning real signal. The calibration is
      standing still.

      **The 88-map entry said the data was the lever. That was drawn from one
      comparison where ECE and the floor happened to move together. They have
      now moved apart, which is the case that separates the explanations, and
      it went the other way.**

      Structural consequence: the gate is ECE / floor, the floor goes to zero
      as the test set grows, and real miscalibration does not. Any residual
      bias makes the ratio climb forever as matches are added. The comment on
      ECE_FLOOR_MULTIPLE claims 2.5x "separates them cleanly at any size";
      that claim is now falsified by our own runs. It fixed small corpora
      failing for being small and created the mirror problem.

      Downloads are close to exhausted anyway: 138 maps off roughly 159 links
      across rounds 1 to 3.

      \* 42-map ECE and floor were not recorded at the time. The 88-map
      figures are repeated in that column as a placeholder and must not be
      read as a measurement.

- [x] **The noise floor was wrong, and the gate was too LENIENT.** Fixed.
      null_calibration_floor drew its null from rng.uniform(0, 1, n), and the
      model's predictions are nothing like uniform: only 29% of them sit
      between .35 and .65, because a round win-probability model spends most
      of its time confident. Shape moves the floor, measured on 6,000 rows:
      bunched mid-range 1.23x, mild centre mass 1.15x, mass at the ends 0.91x.

      Measured over 20 seeds on 138 maps, the matched floor is 0.88x the
      uniform one. Honest result is **10 of 20 seeds, median 2.33**, not 13 of
      20 at 2.06. Every ratio recorded before 2026-09-24 is about 13% too low.

      It now bootstraps off the model's own predictions: p held fixed,
      y ~ Bernoulli(p), so shape, ties and row count are exactly what the
      model produced and only the miscalibration is removed. Passing a row
      count raises TypeError rather than silently doing the old thing.

      Ties were the other suspect and are NOT the problem: 72 to 108 distinct
      predictions, ten filled bins on nineteen of twenty seeds, and the floor
      moves 0.97x to 1.02x at 41, 21 and 11 distinct values.

- [x] **2.5 separates the arms. The negative control passed.**
      tools/calibcheck.py --raw takes the same fitted booster, drops the
      isotonic layer, and scores the raw probabilities against their own
      matched floor. On 5 seeds:

          uncalibrated   median 7.34   (6.10 to 10.30)   0 of 5 pass
          calibrated     median 2.92   (1.86 to  3.75)   1 of 5 pass

      Calibrating divides the ratio by 2.51 and the two arms do not overlap,
      so the threshold is measuring something real and is not the problem.
      The old anchor said uncalibrated lands 4-7x; under the corrected floor
      it lands 6-10x, shifted up as expected. Note those five seeds are the
      harsher half: the 20-seed calibrated median is 2.33, not 2.92.

- [x] **Plant site added. It did not help.** 2026-09-24. Shipped because
      it is correct, not because it worked. 138 maps, 20 seeds, matched floor:

      | | before | with plant_site |
      |---|---|---|
      | passing | 10 of 20 | 11 of 20 |
      | ratio median | 2.33 | 2.39 |
      | ECE median | 0.0259 | 0.0264 |
      | AUC median | 0.8615 | 0.8599 |
      | ratio min / max | 1.05 / 4.03 | 1.40 / 3.48 |

      AUC is the clean read on whether a feature carries signal and it moved
      DOWN 0.0016. If plant site predicted round outcome the booster would
      have found it there first. Post-plant win probability is dominated by
      alive counts, time and equipment; which site is second-order next to
      those. Both tails pulled in, 1.05 to 1.40 and 4.03 to 3.48, which may be
      real and is one run.

      Kept, because it is right: the site IS part of the state and 2,956
      rounds now record it at 100% of planted rounds, split 1571 / 1385.
      tools/backfill.py fills it from round_positions with no re-parse.

- [x] **de_cache was training as de_mirage.** Found on the way. MAPS had no
      de_cache and MAP_IDS.get(name, 0) returns 0, which IS de_mirage, so 133
      collegiate rounds across 6 maps sat inside Mirage's 819: 14% of the
      largest map category was the wrong map. An unknown map now gets
      UNKNOWN_MAP_ID = len(MAPS) instead of defaulting to a real one, so the
      class of bug cannot recur silently. Append to MAPS, never insert.

- [x] **26 more maps did not move it either.** 2026-10-13: 164 maps (the
      138 plus NECC Fall 2026 division weeks 1-2), 20 seeds, matched floor:

      | | 138 maps | 164 maps |
      |---|---|---|
      | passing | 11 of 20 | 12 of 20 |
      | ratio median | 2.39 | 2.36 |
      | ratio min / max | 1.40 / 3.48 | 1.21 / 5.86 |
      | AUC median | 0.8599 | 0.8588 |

      One more seed passing is inside the noise, and the tail got WORSE:
      seed 53 at 5.86 (ECE 0.058) is the worst split recorded. This is the
      third time more matches has been tried as the lever (42, 88, 138,
      164) and the third time it was not one.

- [x] **The first real held-out test PASSED.** 2026-10-13, tools/holdout.py.
      Trained and calibrated on the 138 placement maps only, split 20 ways,
      every fit scored on the same 26 division maps (weeks 1-2, played after
      every training map, never used to choose anything). Rule written into
      the script BEFORE the run: 18 of 20 fits under 2.5x.

          passed 19 of 20; median ratio 1.79; min 0.89, max 2.54 (seed 67)
          AUC 0.862 to 0.885

      This is question 1 below, answered once, and it says yes. What it does
      not say: 26 maps is one sample of new games, and the one failure sits
      just over the line, so the next division weeks are the next test, read
      the same way with the same rule. And it is the calibration gate only:
      whatever the scorer prints to a coach still has to be checked for
      sense against real rounds before it ships.

- [x] **Why 19 of 20 held out but 12 of 20 in the sweep: the TEST SET.**
      tools/gapcheck.py changes one thing at a time from the held-out run:

      | arm | change | passed |
      |---|---|---|
      | A | same protocol, test on 26 random PLACEMENT maps | 12 of 20 |
      | B | division test, train on the sweep's share (123 maps) | 20 of 20 |
      | C | sweep on all 164, but a 26-map test set | 14 of 20 |

      Not training size (B passes with less), not test size (A fails at the
      same size). The 26 division maps are an easy test set, and a random
      26-map set passes about 60% of the time (A), so part of that pass may
      be the draw. A guess at "training size" written here earlier was wrong.
      Possible real reason, untested: divisions pair teams of similar level,
      so fewer lopsided games than placements. Weeks 3-4 decide it: if a
      second division set passes too, it is the games; if not, it was luck.

- [ ] **Stop chasing features on this evidence. The measurement is the limit.**
      ECE ranges 0.0156 to 0.0387 across 20 seeds on the SAME 138 maps, a 2.5x
      spread. Any feature worth less than that is invisible here, and plant
      site was.

      The seeds are not independent samples. They are 20 re-splits of one
      corpus, so the spread measures SPLIT SENSITIVITY and is a lower bound on
      the uncertainty about new data, not an estimate of it. Adding seeds
      narrows the median's standard error and tells you nothing more about
      whether the model is calibrated on a match it has never seen.

      So before any more feature work, decide which question is being asked:

      1. **Ship it or not.** Then hold out whole matches once, never touch
         them, and read the answer once. Everything else is re-splitting.
      2. **Is 0.026 ECE even bad?** Nobody has asked. rate() prints a
         percentage at MIN_CHANCES = 8, where the sampling error on the
         displayed number is about 17 points. The site already shows coaches
         numbers an order of magnitude noisier than this model's bias, and
         this gate is what is stopping it shipping. That is a product
         question and it has never been put.

      Candidates if feature work resumes anyway, cheapest first: defuse kits
      alive on CT, which decides a 5-second defuse against a 10-second one and
      so decides the retake; and round number, since a 5-round team and a
      20-round team play the same alive/equip state differently.

- [ ] **Do not quote a single-seed pass.** run.py defaults to seed 7, which
      was one of three lucky splits at 42 maps and passed at 2.25x while the
      median was 3.46x. At 138 maps seed 7 FAILS at 2.71 while the median is
      2.06 across twenty. The sweep exists because that number was reported
      once already. tools/seedsweep.py, 20 seeds.

      NOT TRUE ANYWHERE PUBLIC YET: the sample report still says in its own
      third line that its numbers are invented, and that stays until a sweep
      is clean against a floor we trust.

## Product gaps a coach will notice

- [ ] **Utility has no map or side split.** "67% of your flashes blind your own
      side" is a good line, and the next three questions are which map, which
      side, which player. None are answerable.
- [ ] **No opponent view.** Before playing a team again you want what happened
      last time. The data is keyed by match and there is no way in.
- [ ] **Nothing separates a scrim from an official match.** They average
      together, and they are different habits.
- [ ] **Denominators are hover-only, and a phone has no hover.** Since
      2026-09-24 every rate prints as a percentage with its rounds in the
      `title`. What the first real coach was sold was "every number has the
      rounds under it". See the `rate()` note in CLAUDE.md before changing it.
      The zone map's tap-to-open box (2026-09-26) is the pattern to copy.
- [ ] **Buy notes are per match only.** "saved alone in round 14" is a note;
      "saved alone six times this season" is coaching. A season roll-up on
      each player's page, and on Team stats.
- [x] **Zone map: kept as it is** (Johan, 2026-09-25): kills filed where the
      victim fell, open ground split in straight lines. Not up for redesign.
- [x] **Review the whole site with the `frontend-design` skill.** Done
      2026-09-25, audit then batches, on every page at both widths.

## Engineering

- [ ] **`main.py` is about 4,000 lines**, a quarter of it embedded HTML.
      Split it by page (auth, season, match, player, account, admin) into
      modules that register their routes, with no behaviour change. Between
      seasons, not during one: the page tests cover the shared pages and
      the outreach flow, not every signed-in page.
- [ ] **Thin tests for** `report.py` and `movement.py` (the coach filter,
      walked zones and the kill/death direction only), and none for either
      `utility.py` or `charts.py`. Page rendering is covered for the shared
      pages (`tests/test_pages.py`). 232 tests in all. A
      rendering test would have caught the "gap of 19 points across 745200
      rounds" bug before it shipped, and the "be"/"b4" arrows.
- [x] **The server is not a git checkout, and drift is now caught.** The
      `/deploy` skill refuses to overwrite any file on the box that matches
      no committed version, and a hook blocks `git pull` aimed at the box.
      See CLAUDE.md, Deploy.
- [ ] **The bundle on the server is a snapshot, not a mirror.**
      `/srv/counterplay/data/repo/counterplay-*.bundle` holds the whole history
      as of the day it was written and is not in `backup.sh`, which copies the
      database only. GitHub is the real backup; that file is a second copy that
      ages.
- [ ] **Only three demo files are on the server**, UCF's two and one of
      team 3's, so the other old matches can never gain a new column (the
      buy check reaches none of them). Every upload IS kept from here on:
      `COUNTERPLAY_RETAIN` defaults to all and `tests/test_retention.py`
      holds it, and `tools/pull-backup.ps1` copies each file to Johan's PC.
- [x] **Stale claims on the homepage and the sample report.** Fixed
      2026-09-26 after a claim-checker sweep: counts are "carried" (hover),
      not "printed"; the buy call is the one modelled part and says so; the
      sample's second tile is opening duels won; no "IGL" role or "rounds
      with an AWP"; five places in the opening, as /stats shows. The hero's
      four figures are real (J-Crazy's season, checked on the box).
- [ ] **The sample report has no zone map.** "Where your rounds are decided"
      is the second section on /stats and what the first real coach asked
      for first; the sample skips it. Needs an invented but plausible
      reading drawn on a real map.
- [ ] **The sample's Players section is not a real /stats section.** The
      roster is /players (a table, with a Coach row). Either mirror that or
      cut the section.
- [ ] **The homepage feature cards do not mention the zone map or the buy
      calls**, the two things the first real coach asked for.
- [ ] **The walked-zone model is built from every position on a map at the
      first request after a restart**, about a second per map. Fine today;
      store it if maps or corpus grow a lot.

## Interface

- [x] **HEAD returns 405 everywhere.** Fixed 2026-09-26: `HeadAsGet` in
      `main.py` answers HEAD as the GET without the body
      (`tests/test_head.py`), so an uptime monitor can watch the site.
- [ ] **An uptime monitor.** Now possible. A free one (UptimeRobot or
      similar) pointed at https://counterplaycs.com/ every 5 minutes, alerting
      Johan's email. Needs an account, so it is Johan's to set up.

## Done

2026-09-26: **backups leave the box.** A Windows scheduled task on Johan's
PC ("Counterplay backup pull", daily 9am, catches up if the PC was off)
runs `tools/pull-backup.ps1`: every nightly database backup, checked on
arrival with SQLite's integrity_check and kept 30 days, and every demo
file, never deleted, into `C:\Users\Johan\counterplay-backups`. First run
pulled all 25 backups and 3 demos, all ok. Also: the outreach flow (a
team built for a coach from `/account`, and a handover link that carries
the coach through signup), the coach named on the roster, the junk
wvgnusrolu signup deleted, cvs renamed J-Crazy.

Password reset and mail, zone naming locked to admins, privacy and terms,
unsubscribe, verified nightly backups, dark mode across all three surfaces,
utility measured by outcome, first deaths carrying whether they were traded,
and no em dashes anywhere a coach can see.

2026-09-25: the share page down from 5.9 MB to about 230 KB; dropdown arrows
that printed "be" and "b4"; the patterns table behind "See the numbers" under
its chart; the coach off the roster; the zone map painting each place with
its own numbers, keyed by the counting, measured on foot so no zone crosses a
wall, with borders; Ancient's B site and Dust2's Top mid named correctly.

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
`tools/makeog.py` in the dark palette and carrying one real reading with its
denominator. Deliberately not the video poster frame: that is gameplay footage
with ten strangers' Steam avatars along the top, which is somebody else's data
on our card.

The same tags are in the page shell, and **suppressed on `noindex` pages**. A
share link unfurling a team name into a Discord channel is the exact leak the
noindex is there to stop.

Set in Segoe UI and Consolas, because Space Grotesk and JetBrains Mono are not
installed on this machine. Drop either `.ttf` into `design/fonts/` and re-run
`tools/makeog.py` and it picks them up.

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
