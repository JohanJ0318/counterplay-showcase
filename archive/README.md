# archive

Things removed from the product but not from the project. Nothing in here is
served, mounted, or deployed.

## site-league

The generated NECC league site: 201 team pages, 777 match pages, an index and a
leaderboard. 980 files. It lived at `/league/` until it was taken off the site.

It was built from FACEIT match statistics, not from parsed demos, and it
covered the 2025-26 season through the Spring 2026 playoffs (the newest match
in the cache is 2026-05-11).

### What was removed with it

- The "League" link in `PRIMARY_NAV`, in the signed-out nav, and on the
  landing page
- The `leaderboards` entry in `FEATURE_LINKS`, which pointed at
  `/league/leaderboards.html`
- The league site's check in `app/smoke.py`

### What was deliberately left alone

- **`league/gen/`**, the generator and its 27MB cache. Never served, and the
  reason this is reversible.
- **`app.main.league_page`**, the route. It already returns 404 when the
  directory is missing, so it costs nothing to keep and it means restoring is
  a folder move rather than a code change.

### To put it back

```bash
mv archive/site-league site/league
```

Then restore the four links listed above, and deploy `site/league` to
`/srv/counterplay/site/league`.

### To rebuild it from scratch instead

```bash
cd league/gen
python fetch.py --org NECC          # needs FACEIT_API_KEY; skip to use the cache
python build.py --out ../../site/league
```

`fetch.py` only downloads what is missing, so re-running it during a season is
cheap. `build.py` regenerates all 980 pages from the cache in about a minute.

### Why it was removed

A product decision, not a technical one. It was a second product wearing the
same shell: a public directory of other people's seasons, sitting inside a
tool whose actual job is reading your own demos. Worth knowing before it goes
back up: it was the one thing on the site that could show a coach their own
data before they had done any work, which was the whole basis of the "open
with their own numbers" outreach plan.
