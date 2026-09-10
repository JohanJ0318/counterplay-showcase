"""Counterplay web app.

    pip install -r requirements.txt
    python -m app            # http://127.0.0.1:8000

Serves three things from one process:

  * the marketing page and the generated league site, as static files
  * real accounts — signup, login, teams, demo uploads — against SQLite
  * a feature list on the dashboard, read from `plans.py` rather than written
    by hand, so it cannot promise something the product does not do

Nothing here shows a price or a tier. It is free this season, and a coach
evaluating it should not have to think about what it will cost later.
`plans.py` still holds the plan ladder for when that changes.
"""
from __future__ import annotations

import hashlib
import os
import secrets
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import (advice, auth, charts, db, legal, mail, movement,
               report as report_mod, resets, sample as sample_page,
               utility)
from .plans import (DEFAULT_TEAM_PLAN, DEFAULT_USER_PLAN, FEATURE_ORDER,
                    FEATURES, Level, access)
from .theme import banner, esc, map_chip, page

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"

# Cookies are marked Secure unless this is explicitly a local run. Getting this
# backwards in production means session cookies travel in clear text, so the
# default is the safe one and development has to opt out.
INSECURE_COOKIES = os.environ.get("COUNTERPLAY_INSECURE_COOKIES") == "1"

MAX_DEMO_BYTES = 400 * 1024 * 1024      # a CS2 demo is 100-250MB
ZSTD_MAGIC = bytes([0x28, 0xB5, 0x2F, 0xFD])   # FACEIT serves .dem.zst
LEAGUES = ["NECC", "NACE Starleague", "ECAC", "Playfly", "ESEA",
           "FACEIT League", "Other"]
ROLES = [("coach", "Coach"), ("igl", "In-game leader"), ("player", "Player"),
         ("director", "Program director"), ("other", "Other")]

# Features that actually work today. Everything else in plans.py renders as
# "Coming" rather than being quietly listed as though it ships.
BUILT_FEATURES = {"match_reports", "player_stats", "team_stats",
                  "pattern_finder", "leaderboards"}

# Where a working feature actually lives, so "Available" is clickable rather
# than a claim a coach has to go hunting to verify.
FEATURE_LINKS = {"match_reports": "/matches", "player_stats": "/players",
                 "team_stats": "/stats", "pattern_finder": "/stats",
                 "leaderboards": "/league/leaderboards.html"}

app = FastAPI(title="Counterplay", docs_url=None, redoc_url=None)


@app.on_event("startup")
def _startup() -> None:
    db.init()


# ---------------------------------------------------------------- helpers

def current(request: Request):
    return auth.session_user(request.cookies.get(auth.SESSION_COOKIE))


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        auth.SESSION_COOKIE, token,
        max_age=auth.SESSION_DAYS * 86400,
        httponly=True,                 # JavaScript must never see this
        samesite="lax",                # blocks the cross-site POST case
        secure=not INSECURE_COOKIES,
        path="/",
    )


def see_other(url: str) -> RedirectResponse:
    """303 so the browser turns a POST into a GET and a refresh cannot resubmit."""
    return RedirectResponse(url, status_code=303)


def html_page(*args, **kwargs) -> HTMLResponse:
    return HTMLResponse(page(*args, **kwargs))


def require_user(request: Request):
    user = current(request)
    if user is None:
        return None, see_other("/login")
    return user, None


def form_field(name: str, label: str, kind: str = "text", value: str = "",
               required: bool = True, **attrs) -> str:
    extra = "".join(f' {k.replace("_", "-")}="{esc(v)}"' for k, v in attrs.items())
    req = " required" if required else ""
    opt = "" if required else ' <span class="den">optional</span>'
    return (f'<label>{esc(label)}{opt}<input type="{kind}" name="{esc(name)}" '
            f'value="{esc(value)}"{req}{extra}></label>')


def select_field(name: str, label: str, options, value: str = "") -> str:
    opts = "".join(
        f'<option value="{esc(v)}"{" selected" if v == value else ""}>{esc(t)}</option>'
        for v, t in options)
    return (f'<label>{esc(label)}<select name="{esc(name)}">{opts}</select></label>')


def csrf_input(user) -> str:
    return f'<input type="hidden" name="csrf" value="{esc(user["csrf"])}">'


# ---------------------------------------------------------------- signup

SIGNUP_INTRO = (
    "Free for the season. You get a link before your next match, and one person "
    "reads every one of these, so you will get a reply from a human.")


def signup_form(values: dict | None = None, error: str = "") -> str:
    v = values or {}
    warn = f'<p class="warn">{esc(error)}</p>' if error else ""
    return f"""
  <section>
    <div class="card">
      {warn}
      <form class="stack" method="post" action="/signup">
        {form_field("team", "Team or program", value=v.get("team", ""))}
        {select_field("league", "League", [(x, x) for x in LEAGUES], v.get("league", "NECC"))}
        {select_field("role", "Your role", ROLES, v.get("role", "coach"))}
        {form_field("name", "Your name", value=v.get("name", ""))}
        {form_field("email", "Email", "email", v.get("email", ""), autocomplete="email")}
        {form_field("password", "Password", "password", required=True,
                    autocomplete="new-password", minlength="10")}
        {form_field("faceit_url", "FACEIT team page", value=v.get("faceit_url", ""),
                    required=False)}
        <button type="submit">Create the account</button>
        <p class="den">Ten characters minimum. Already have one?
          <a href="/login">Log in</a>.</p>
      </form>
    </div>
  </section>"""


@app.get("/signup", response_class=HTMLResponse)
def signup_get(request: Request):
    if current(request):
        return see_other("/dashboard")
    return html_page("Add your team | Counterplay",
                     banner("Add your team", label="Free this season"),
                     f'<section><p class="lede">{SIGNUP_INTRO}</p></section>'
                     + signup_form())


@app.post("/signup")
def signup_post(request: Request, team: str = Form(""), league: str = Form(""),
                role: str = Form("other"), name: str = Form(""),
                email: str = Form(""), password: str = Form(""),
                faceit_url: str = Form("")):
    values = {"team": team, "league": league, "role": role, "name": name,
              "email": email, "faceit_url": faceit_url}

    def fail(msg):
        return HTMLResponse(page("Add your team | Counterplay",
                                 banner("Add your team", label="Free this season"),
                                 signup_form(values, msg)), status_code=400)

    problem = auth.email_problem(email) or auth.password_problem(password)
    if problem:
        return fail(problem)
    if not team.strip():
        return fail("A team or program name is needed.")
    if not name.strip():
        return fail("Your name is needed.")
    if role not in dict(ROLES):
        role = "other"

    key = auth.email_key(email)
    if db.one("SELECT id FROM users WHERE email_key = ?", key):
        # Deliberately explicit rather than vague. Signup already leaks account
        # existence through any honest error message, and being coy here just
        # strands a returning coach on a form that will not accept them.
        return fail("There is already an account for that email. "
                    "Log in instead, or use a different address.")

    user_id = db.execute(
        """INSERT INTO users (email, email_key, password_hash, name, role, plan,
                              verify_token, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        email.strip(), key, auth.hash_password(password), name.strip(), role,
        DEFAULT_USER_PLAN, secrets.token_urlsafe(24), db.utcnow())

    slug = db.slugify(team)
    team_id = db.execute(
        """INSERT INTO teams (name, slug, league, faceit_url, plan, created_at,
                              created_by)
           VALUES (?,?,?,?,?,?,?)""",
        team.strip(), slug, league, faceit_url.strip(), DEFAULT_TEAM_PLAN,
        db.utcnow(), user_id)
    db.execute("""INSERT INTO team_members (team_id, user_id, member_role, created_at)
                  VALUES (?,?,?,?)""", team_id, user_id, "owner", db.utcnow())
    db.audit(user_id, "signup", f"team={slug} league={league}")

    token, _ = auth.start_session(user_id, request.headers.get("user-agent", ""))
    response = see_other("/dashboard")
    set_session_cookie(response, token)
    return response


# ---------------------------------------------------------------- login

def login_form(email: str = "", error: str = "") -> str:
    warn = f'<p class="warn">{esc(error)}</p>' if error else ""
    return f"""
  <section>
    <div class="card">
      {warn}
      <form class="stack" method="post" action="/login">
        {form_field("email", "Email", "email", email, autocomplete="email")}
        {form_field("password", "Password", "password", autocomplete="current-password")}
        <button type="submit">Log in</button>
        <p class="den">No account? <a href="/signup">Add your team</a>.
          Forgotten it? <a href="/forgot">Reset your password</a>.</p>
      </form>
    </div>
  </section>"""


@app.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    if current(request):
        return see_other("/dashboard")
    return html_page("Log in | Counterplay", banner("Log in"), login_form())


@app.post("/login")
def login_post(request: Request, email: str = Form(""), password: str = Form("")):
    def fail(msg, code=400):
        return HTMLResponse(page("Log in | Counterplay", banner("Log in"),
                                 login_form(email, msg)), status_code=code)

    if auth.too_many_attempts(email):
        return fail("Too many attempts for that address. Wait a few minutes.", 429)

    row = db.one("SELECT * FROM users WHERE email_key = ?", auth.email_key(email))
    # Verify against a dummy hash when the account does not exist, so a missing
    # account and a wrong password take the same time. Skipping this turns the
    # login form into an account enumerator with a stopwatch.
    stored = row["password_hash"] if row else auth.hash_password("not-a-real-password")
    if not auth.verify_password(password, stored) or row is None:
        auth.record_failure(email)
        return fail("That email and password do not match.", 401)

    auth.clear_attempts(email)
    token, _ = auth.start_session(row["id"], request.headers.get("user-agent", ""))
    db.audit(row["id"], "login")
    response = see_other("/dashboard")
    set_session_cookie(response, token)
    return response


# ---------------------------------------------------------------- password reset
#
# The rules live in `resets.py`; what is here is the four screens and the one
# thing the screens must never do, which is say whether an address has an
# account. Every path through /forgot ends on the same page with the same
# words, so the form cannot be used to find out who has signed up.

def _forgot_form(email: str = "", error: str = "") -> str:
    warn = f'<p class="warn">{esc(error)}</p>' if error else ""
    return f"""
  <section>
    <div class="card">
      {warn}
      <p class="lede">Give us the address on the account and we will send a
        link that lets you set a new password. The link works once and lasts
        {resets.TOKEN_HOURS} hour.</p>
      <form class="stack" method="post" action="/forgot">
        {form_field("email", "Email", "email", email, autocomplete="email")}
        <button type="submit">Send the link</button>
        <p class="den"><a href="/login">Back to signing in</a></p>
      </form>
    </div>
  </section>"""


def _sent_page() -> str:
    return """
  <section>
    <div class="card">
      <p class="lede">If that address has an account, a reset link is on its
        way. It works once and lasts an hour.</p>
      <p class="den">Nothing arrived? Check the spam folder, then try again in
        a few minutes. We do not say whether an address has an account here,
        which is deliberate: otherwise this form is a way to find out who has
        signed up.</p>
      <p class="den"><a href="/login">Back to signing in</a></p>
    </div>
  </section>"""


@app.get("/forgot", response_class=HTMLResponse)
def forgot_get(request: Request):
    if current(request):
        return see_other("/account")
    return html_page("Reset your password | Counterplay",
                     banner("Reset your password"), _forgot_form())


@app.post("/forgot", response_class=HTMLResponse)
def forgot_post(request: Request, email: str = Form("")):
    sent = html_page("Check your email | Counterplay",
                     banner("Check your email"), _sent_page())
    if not mail.configured():
        # Better to say so than to show "check your email" forever. This is
        # the state of a box that has not been given SMTP settings, and the
        # only person who can hit it before launch is us.
        return HTMLResponse(
            page("Reset your password | Counterplay",
                 banner("Reset your password"),
                 _forgot_form(email, "Password reset is not switched on for "
                                     "this server yet. Get in touch and we "
                                     "will sort it out by hand.")),
            status_code=503)

    # Rate limited per account, and silently: a caller must not be able to tell
    # "too many requests" from "no such account" either.
    if resets.too_many(email):
        return sent
    got = resets.issue(email, request.client.host if request.client else "")
    if got is None:
        return sent
    token, user = got
    subject, body = mail.reset_email(
        user.get("name") or "", mail.site_url(f"/reset/{token}"),
        resets.TOKEN_HOURS)
    try:
        mail.send(user["email"], subject, body)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        # The token is already issued and the mail did not go. Say so rather
        # than showing "check your email" to somebody who will never get one.
        db.audit(user["id"], "reset_mail_failed", f"{type(exc).__name__}")
        return HTMLResponse(
            page("Reset your password | Counterplay",
                 banner("Reset your password"),
                 _forgot_form(email, "We could not send the email just now. "
                                     "Try again in a minute.")),
            status_code=502)
    db.audit(user["id"], "reset_requested")
    return sent


def _reset_form(token: str, error: str = "") -> str:
    warn = f'<p class="warn">{esc(error)}</p>' if error else ""
    return f"""
  <section>
    <div class="card">
      {warn}
      <form class="stack" method="post" action="/reset/{esc(token)}">
        {form_field("password", "New password", "password",
                    autocomplete="new-password")}
        {form_field("confirm", "New password again", "password",
                    autocomplete="new-password")}
        <button type="submit">Set the password</button>
        <p class="den">Setting it signs this account out everywhere else.</p>
      </form>
    </div>
  </section>"""


def _dead_link() -> str:
    return """
  <section>
    <div class="card">
      <p class="warn">That link is not usable. It has either expired, been
        used already, or was never one of ours.</p>
      <p class="den">A link lasts an hour and works once.
        <a href="/forgot">Ask for a new one</a>.</p>
    </div>
  </section>"""


@app.get("/reset/{token}", response_class=HTMLResponse)
def reset_get(token: str):
    if resets.holder(token) is None:
        return HTMLResponse(page("Link expired | Counterplay",
                                 banner("Link expired"), _dead_link()),
                            status_code=410)
    return html_page("Set a new password | Counterplay",
                     banner("Set a new password"), _reset_form(token))


@app.post("/reset/{token}", response_class=HTMLResponse)
def reset_post(request: Request, token: str, password: str = Form(""),
               confirm: str = Form("")):
    if resets.holder(token) is None:
        return HTMLResponse(page("Link expired | Counterplay",
                                 banner("Link expired"), _dead_link()),
                            status_code=410)
    if password != confirm:
        return HTMLResponse(
            page("Set a new password | Counterplay", banner("Set a new password"),
                 _reset_form(token, "Those two do not match.")), status_code=400)
    problem = auth.password_problem(password)
    if problem:
        return HTMLResponse(
            page("Set a new password | Counterplay", banner("Set a new password"),
                 _reset_form(token, problem)), status_code=400)
    if not resets.spend(token, password):
        return HTMLResponse(page("Link expired | Counterplay",
                                 banner("Link expired"), _dead_link()),
                            status_code=410)
    return html_page(
        "Password changed | Counterplay", banner("Password changed"),
        """
  <section>
    <div class="card">
      <p class="lede">Done. Every session on this account was signed out,
        including any that were not yours.</p>
      <p><a class="btn" href="/login">Sign in</a></p>
    </div>
  </section>""")


# ------------------------------------------------------------------- legal
#
# Two pages and an opt-out. None of it is interesting and all of it has to
# exist before somebody who did not build this has an account, or before a
# cold email goes to a coach.

@app.get("/privacy", response_class=HTMLResponse)
def privacy_page(request: Request):
    return html_page("Privacy | Counterplay",
                     banner("Privacy", label="What we hold, and how to get rid of it"),
                     legal.privacy_body(), current(request))


@app.get("/terms", response_class=HTMLResponse)
def terms_page(request: Request):
    return html_page("Terms | Counterplay",
                     banner("Terms", label="The deal, in plain English"),
                     legal.terms_body(), current(request))


@app.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe_get(request: Request, e: str = ""):
    """The link in an outreach email.

    A GET must not change anything, so this confirms rather than acting: mail
    clients and link scanners fetch every URL in a message, and an unsubscribe
    that fired on GET would opt people out because their virus scanner was
    thorough. The address is prefilled and one button away.
    """
    return html_page("Unsubscribe | Counterplay", banner("Unsubscribe"),
                     legal.unsubscribe_form(e), current(request))


@app.post("/unsubscribe", response_class=HTMLResponse)
def unsubscribe_post(email: str = Form("")):
    key = auth.email_key(email)
    if auth.email_problem(email):
        return HTMLResponse(
            page("Unsubscribe | Counterplay", banner("Unsubscribe"),
                 legal.unsubscribe_form(email, "That does not look like an "
                                               "email address.")),
            status_code=400)
    already = db.one("SELECT id FROM unsubscribes WHERE email_key = ?", key)
    if already is None:
        db.execute("""INSERT INTO unsubscribes (email_key, source, created_at)
                      VALUES (?,?,?)""", key, "web", db.utcnow())
        db.audit(None, "unsubscribe", key)
    return html_page("Unsubscribed | Counterplay", banner("Unsubscribed"),
                     legal.unsubscribed_body(email, already is not None))


@app.post("/logout")
def logout(request: Request, csrf: str = Form("")):
    user = current(request)
    if user is None:
        return see_other("/")
    # Reject loudly rather than dropping the cookie anyway. Clearing it on a
    # failed check leaves the server session alive while the browser forgets
    # the only handle on it — logged out to the user, still valid to anyone
    # holding the token.
    if not auth.check_csrf(user, csrf):
        return HTMLResponse("Bad CSRF token.", status_code=403)
    auth.end_session(request.cookies.get(auth.SESSION_COOKIE))
    db.audit(user["id"], "logout")
    response = see_other("/")
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return response


# ---------------------------------------------------------------- dashboard

def feature_card(key: str, level: Level, team_slug: str | None) -> str:
    """One feature, marked by whether it works yet.

    Deliberately not a tier badge. While the season is free the only question a
    coach has is whether a thing exists, so that is the only thing shown; the
    plan a feature will eventually sit behind is in `plans.py` and stays there
    until there is something to charge for.
    """
    f = FEATURES[key]
    built = key in BUILT_FEATURES
    pill = ('<span class="pill on">Available</span>' if built
            else '<span class="pill">Coming</span>')
    beta = ' <span class="pill beta">Beta</span>' if f.beta else ""
    href = FEATURE_LINKS.get(key) if built else None
    go = (f'<p style="margin-top:10px"><a href="{href}">Open {esc(f.name.lower())}'
          f' &rarr;</a></p>' if href else "")
    return (f'<div class="card"><div style="display:flex;gap:8px;align-items:center;'
            f'flex-wrap:wrap"><h3>{esc(f.name)}</h3>{pill}{beta}</div>'
            f'<p class="lede">{esc(f.blurb)}</p>{go}</div>')


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user, redirect = require_user(request)
    if redirect:
        return redirect

    team = db.team_for_user(user["id"])
    team_plan = team["plan"] if team else None
    counts = db.demo_counts(team["id"]) if team else {"total": 0, "parsed": 0,
                                                      "pending": 0, "failed": 0,
                                                      "rounds": 0}

    cards = "".join(feature_card(k, access(k, user["plan"], team_plan),
                                 team["slug"] if team else None)
                    for k in FEATURE_ORDER)

    team_line = (f'<a href="/team/{esc(team["slug"])}">{esc(team["name"])}</a> · '
                 f'{esc(team["league"] or "no league set")}' if team
                 else "No team yet")

    # The honest state of the product, on the page people actually look at
    # rather than only in the marketing copy. A dashboard that shows an empty
    # report and no explanation reads as broken software.
    status = ""
    if counts["parsed"] == 0:
        status = ('<p class="note">Nothing parsed yet. Upload demos below and the '
                  'reports fill in. Grab them while they are fresh, because platforms '
                  'delete match demos after a few weeks.</p>')

    # Record and recent form, so the first screen after logging in is about the
    # team rather than about the plan. Two cards used to read the same number
    # (uploaded, parsed) and the season went unmentioned.
    all_matches = report_mod.team_matches(team["id"]) if team else []
    done = [q for q in all_matches if q["result"]]
    wins = sum(1 for q in done if q["result"] == "W")
    record = f"{wins}&ndash;{len(done) - wins}" if done else "&ndash;"
    pending = sum(1 for q in all_matches if q["status"] != "parsed")
    pending_note = (f'<span class="den" style="font-size:.5em"> +{pending}</span>'
                    if pending else "")

    played = [f for f in (report_mod.recent_form(team["id"]) if team else [])
              if f["result"]]
    if played:
        _cards = "".join(
            f'<a class="formcard" href="/match/{esc(f["match_key"])}">'
            f'<span class="res {"win" if f["result"] == "W" else "loss"}">'
            f'{esc(f["result"])}</span>'
            f'<span class="mono">{f["us"]}&ndash;{f["them"]}</span>'
            f'<span class="den">{esc(f["map"])}</span></a>' for f in played)
        form_block = (
            f'<section><div class="sec-head"><span class="label">'
            f'Newest first</span><h2>Recent form</h2></div>'
            f'<div class="formrow">{_cards}</div>'
            f'<p class="note" style="margin-top:12px">'
            f'<a href="/matches">All {len(done)} matches &rarr;</a> &middot; '
            f'<a href="/stats">What repeats across them &rarr;</a></p></section>')
    else:
        form_block = ""

    body = f"""
  <section>
    <div class="stat-row">
      <div class="stat"><span class="stat-n">{record}</span>
        <span class="label">record</span></div>
      <div class="stat"><span class="stat-n">{counts["parsed"]}{pending_note}</span>
        <span class="label">matches analyzed</span></div>
      <div class="stat"><span class="stat-n">{counts["rounds"]}</span>
        <span class="label">rounds</span></div>
      <div class="stat"><span class="stat-n">Free</span>
        <span class="label">this season</span></div>
    </div>
    {status}
  </section>
  {form_block}

  <section>
    <div class="sec-head"><span class="label">What your plan reaches</span>
      <h2>Features</h2></div>
    <p class="lede">What the product does today, and what is still being built.
      Everything is free this season.</p>
    <div class="grid2">{cards}</div>
  </section>
  <section>
    <div class="sec-head"><span class="label">Demos</span><h2>Upload</h2></div>
    <div class="card">
      <form class="stack" method="post" action="/upload"
            enctype="multipart/form-data">
        {csrf_input(user)}
        <label>Match demos
          <input type="file" name="demo" accept=".dem,.zst" multiple required></label>
        <button type="submit">Upload</button>
        <p class="den">Select as many as you like; a whole season at once is
          fine. <strong>.dem</strong> or <strong>.dem.zst</strong> (what FACEIT's
          download button gives you), up to 400&nbsp;MB each. The same match
          uploaded twice is stored once.</p>
        <p class="den">Grab them while they are fresh: FACEIT and Valve delete
          match demos after a few weeks, so the ones worth keeping are the ones
          you save now.</p>
      </form>
    </div>
  </section>"""

    return html_page("Dashboard | Counterplay",
                     banner("Dashboard", crumb=team_line), body, user)


# ---------------------------------------------------------------- upload

async def _save_one(demo: UploadFile, team, user) -> tuple[str, str]:
    """Store one uploaded demo. Returns (outcome, detail) for the summary."""
    name = demo.filename or "unnamed"
    low = name.lower()
    if not (low.endswith(".dem") or low.endswith(".dem.zst")):
        return "skipped", f"{name}: not a .dem or .dem.zst"

    # Hash and write in one pass, capped. Reading a 400MB upload into memory to
    # hash it would take the process down under any real load.
    digest = hashlib.sha256()
    size = 0
    tmp = db.DEMO_DIR / f".incoming-{secrets.token_hex(8)}"
    try:
        with tmp.open("wb") as out:
            while chunk := await demo.read(1 << 20):
                size += len(chunk)
                if size > MAX_DEMO_BYTES:
                    return "skipped", f"{name}: over 400MB"
                digest.update(chunk)
                out.write(chunk)
        if size == 0:
            return "skipped", f"{name}: empty"
        sha = digest.hexdigest()
        # Keep the extension honest: a coach downloading from FACEIT gets a
        # .zst, and ingest decides what to do by reading the magic number, not
        # the name, but the stored name should still say what the bytes are.
        with tmp.open("rb") as probe:
            suffix = ".dem.zst" if probe.read(4) == ZSTD_MAGIC else ".dem"
        final = db.DEMO_DIR / f"{sha}{suffix}"
        if final.exists():
            tmp.unlink(missing_ok=True)     # same bytes already on disk
        else:
            tmp.replace(final)
    finally:
        tmp.unlink(missing_ok=True)

    if db.one("SELECT id FROM demos WHERE team_id = ? AND sha256 = ?",
              team["id"], sha):
        return "duplicate", f"{name}: already uploaded"

    db.execute(
        """INSERT INTO demos (team_id, uploaded_by, filename, size_bytes,
                              sha256, tier, status, created_at, source)
           VALUES (?,?,?,?,?,?,?,?,'upload')""",
        team["id"], user["id"], name[:200], size, sha, "league",
        "pending", db.utcnow())
    db.audit(user["id"], "upload", f"{name} {size}B")
    return "queued", f"{name}: {size/1e6:.0f} MB"


@app.post("/upload")
async def upload(request: Request, csrf: str = Form(""),
                 demo: list[UploadFile] = File(default=[])):
    """Take a whole folder of demos at once.

    A coach has a season, not a file. Uploading twenty matches one at a time
    through a form is the kind of friction that ends a pilot before it starts.
    """
    user, redirect = require_user(request)
    if redirect:
        return redirect
    if not auth.check_csrf(user, csrf):
        return HTMLResponse("Bad CSRF token.", status_code=403)

    team = db.team_for_user(user["id"])
    if team is None:
        return see_other("/dashboard")

    counts = {"queued": 0, "duplicate": 0, "skipped": 0}
    details = []
    for f in demo:
        if f is None or not f.filename:
            continue
        outcome, detail = await _save_one(f, team, user)
        counts[outcome] += 1
        if outcome != "queued":
            details.append(detail)

    if counts["queued"] == 0 and counts["duplicate"] == 0 and details:
        return HTMLResponse(page(
            "Upload | Counterplay", banner("Nothing was accepted"),
            '<section><p class="warn">' +
            "<br>".join(esc(d) for d in details[:20]) +
            '</p><p><a class="btn" href="/dashboard">Back</a></p></section>',
            user), status_code=400)
    return see_other(f"/team/{team['slug']}?queued={counts['queued']}"
                     f"&dupe={counts['duplicate']}&skip={counts['skipped']}")


# ---------------------------------------------------------------- team

@app.get("/team/{slug}", response_class=HTMLResponse)
def team_page(request: Request, slug: str):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    team = db.team_by_slug(slug)
    if team is None:
        return HTMLResponse(page("Not found | Counterplay", banner("Not found"),
                                 '<section><p class="lede">No team by that '
                                 'name.</p></section>', user), status_code=404)

    membership = db.one("""SELECT member_role FROM team_members
                            WHERE team_id = ? AND user_id = ?""",
                        team["id"], user["id"])
    if membership is None:
        # One team's report is never shown to another team. That promise is on
        # the marketing page, so it is enforced here rather than assumed.
        return HTMLResponse(page("Not yours | Counterplay", banner("Not yours"),
                                 '<section><p class="lede">You are not on this '
                                 'team.</p></section>', user), status_code=403)

    roster = db.team_roster(team["id"])
    rows = "".join(
        f'<tr><td class="name">{esc(m["name"] or m["email"])}</td>'
        f'<td><span class="pill">{esc(m["member_role"])}</span></td>'
        f'<td class="den">{esc(m["role"])}</td></tr>' for m in roster)

    demos = db.team_demos(team["id"])

    # "PENDING" with no explanation reads as broken software. Say what the
    # status means and what happens next, in the place someone is looking when
    # they wonder.
    counts = db.demo_counts(team["id"])
    waiting = counts["pending"]
    if waiting:
        explain = (f'<p class="note"><strong>{waiting} demo(s) waiting to be '
                   f'parsed.</strong> Uploading and parsing are separate steps: '
                   f'a match takes a few seconds to a few minutes to read, so it '
                   f'happens in the background rather than making you wait on '
                   f'the upload. This page updates when it is done, so '
                   f'reload in a minute.</p>')
    elif counts["failed"] and not counts["parsed"]:
        explain = ('<p class="warn">Nothing parsed successfully yet. The status '
                   'note on each row says what went wrong.</p>')
    else:
        explain = ""

    if demos:
        # Named by map and score, not by the string Valve happened to call the
        # file. Eleven rows of "003838914553828081689_1191066329.dem" is eleven
        # rows a coach cannot tell apart, and every part of a usable name was
        # already in the database.
        items = report_mod.team_matches(team["id"])
        drows = []
        for m in items:
            if m["match_key"] and m["result"]:
                cls = "win" if m["result"] == "W" else "loss"
                score = (f'<span class="res {cls}">{m["result"]}</span>'
                         f'<span class="mono">{m["us"]}&ndash;{m["them"]}</span>')
            elif m["match_key"] and m["us"] is not None:
                score = f'<span class="mono">{m["us"]}&ndash;{m["them"]}</span>'
            else:
                score = '<span class="den">&ndash;</span>'
            name = (f'<a href="/match/{esc(m["match_key"])}">'
                    f'{esc(m["map"] or "match")}</a>' if m["match_key"]
                    else esc(m["map"] or m["filename"]))
            note = (f'<div class="den">{esc((m["note"] or "")[:120])}</div>'
                    if m["note"] and m["status"] != "parsed" else "")
            # size_bytes is 0 when the copy was not retained, which is a
            # retention decision and not a zero-byte file.
            size = (f'{m["size_mb"]:.0f} MB' if m["size_mb"] >= 1
                    else '<span class="den">not kept</span>')
            drows.append(
                f'<tr><td class="name">{name}'
                f'<div class="den" style="font-weight:400" '
                f'title="{esc(m["filename"])}">{esc(m["filename"][:28])}&hellip;'
                f'</div></td>'
                f'<td class="num">{score}</td>'
                f'<td><span class="pill">{esc(m["status"])}</span></td>'
                f'<td class="num mono">{m["rounds"] if m["rounds"] is not None else "&ndash;"}</td>'
                f'<td class="num mono">{size}</td>'
                f'<td class="den">{esc(m["uploaded"])}{note}</td></tr>')
        demo_block = (explain +
                      f'<div class="tbl-wrap"><table><thead><tr><th>Match</th>'
                      f'<th class="num">Score</th><th>Status</th>'
                      f'<th class="num">Rounds</th><th class="num">Size</th>'
                      f'<th>Uploaded</th></tr></thead>'
                      f'<tbody>{"".join(drows)}</tbody></table></div>')
    else:
        demo_block = ('<p class="note">No demos yet. Upload from the '
                      '<a href="/dashboard">dashboard</a>.</p>')

    body = f"""
  <section>
    <div class="stat-row">
      <div class="stat"><span class="stat-n">{len(roster)}</span>
        <span class="label">on the roster</span></div>
      <div class="stat"><span class="stat-n">{len(demos)}</span>
        <span class="label">demos</span></div>
      <div class="stat"><span class="stat-n">Free</span>
        <span class="label">this season</span></div>
    </div>
  </section>
  <section>
    <div class="sec-head"><span class="label">Who is on it</span><h2>Roster</h2></div>
    <div class="tbl-wrap"><table><thead><tr><th>Name</th><th>On this team</th>
      <th>Role</th></tr></thead><tbody>{rows}</tbody></table></div>
  </section>
  <section>
    <div class="sec-head"><span class="label">What has been sent in</span>
      <h2>Demos</h2></div>
    {demo_block}
  </section>"""
    return html_page(f"{team['name']} | Counterplay",
                     banner(team["name"], crumb=esc(team["league"])), body, user)




def _demo_link(d) -> str:
    """A parsed demo links to its report; anything else is just a filename."""
    name = esc(d["filename"])
    if d["status"] != "parsed":
        return name
    m = db.one("SELECT match_key FROM matches WHERE demo_id = ?", d["id"])
    if m is None:
        return name
    return f'<a href="/match/{esc(m["match_key"])}">{name}</a>'


@app.get("/match/{match_key}", response_class=HTMLResponse)
def match_report(request: Request, match_key: str):
    user, redirect = require_user(request)
    if redirect:
        return redirect

    # A report belongs to whoever owns the demo behind it. One team's match is
    # never shown to another team - the same rule as /team, enforced the same way.
    owner = db.one("""SELECT d.team_id FROM matches m JOIN demos d ON d.id = m.demo_id
                       WHERE m.match_key = ?""", match_key)
    if owner is None:
        return HTMLResponse(page("Not found", banner("Not found"),
                                 '<section><p class="lede">No such match.</p></section>',
                                 user), status_code=404)
    if owner["team_id"] is not None:
        member = db.one("SELECT 1 FROM team_members WHERE team_id = ? AND user_id = ?",
                        owner["team_id"], user["id"])
        if member is None:
            return HTMLResponse(page("Not yours", banner("Not yours"),
                                     '<section><p class="lede">That match belongs to '
                                     'another team.</p></section>', user),
                                status_code=403)

    r = report_mod.build(match_key)
    if r is None:
        return HTMLResponse(page("Not found", banner("Not found"),
                                 '<section><p class="lede">Nothing parsed for that '
                                 'match.</p></section>', user), status_code=404)

    m, rows = r["match"], r["rows"]
    rate = report_mod.rate
    DASH = "&ndash;"

    trs = []
    for x in rows:
        won = "CT" if x["ct_won"] else "T"
        # The one place a second hue is used: a report is unreadable if you
        # cannot tell the sides apart at a glance.
        cls = "pill ct" if x["ct_won"] else "pill t"
        if x["opening_loser"]:
            opening = (f'{x["opening_loser"].upper()} lost it '
                       f'<span class="den">{x["opening_at"]:.0f}s</span>')
        else:
            opening = "&ndash;"
        trs.append(
            f'<tr><td class="num mono">{x["round_num"]}</td>'
            f'<td><span class="{cls}">{won}</span></td>'
            f'<td class="den">{esc(x["buy_ct"])} v {esc(x["buy_t"])}</td>'
            f'<td class="num mono">{x["equip_ct"]:,.0f}</td>'
            f'<td class="num mono">{x["equip_t"]:,.0f}</td>'
            f'<td class="num mono">{x["deaths_ct"]}{DASH}{x["deaths_t"]}</td>'
            f'<td>{opening}</td>'
            f'<td class="den">{"yes" if x["planted"] else "&ndash;"}</td></tr>')

    od = []
    for side in ("ct", "t"):
        o = r["opening"][side]
        rounds_lost = ", ".join(str(n) for n in o["lost_rounds"]) or "-"
        od.append(
            f'<tr><td class="name">{side.upper()}</td>'
            f'<td class="num">{rate(o["saved"], o["lost"])}</td>'
            f'<td class="num">{rate(o["converted"], o["taken"])}</td>'
            f'<td class="den">{esc(rounds_lost)}</td></tr>')

    br = []
    for side in ("ct", "t"):
        for kind, v in sorted(r["buys"][side].items()):
            which = ", ".join(str(n) for n in v["rounds"])
            br.append(f'<tr><td class="name">{side.upper()} {esc(kind)}</td>'
                      f'<td class="num">{rate(v["won"], v["n"])}</td>'
                      f'<td class="den">{esc(which)}</td></tr>')

    # ---- scoreboard
    ROLE_CLASS = {"AWP": "role awp", "Entry": "role entry"}
    sb_blocks = []
    for team in r["scoreboard"]:
        prows = []
        for a in team["players"]:
            cls = ROLE_CLASS.get(a["role"], "role")
            util = a.get("util_damage", 0) or 0
            tk = a.get("trade_kills", 0) or 0
            ct_t, ct_w = a.get("clutch_tried", 0) or 0, a.get("clutch_won", 0) or 0
            prows.append(
                f'<tr><td class="name">'
                f'<a href="/player/{esc(a["steamid"])}">{esc(a["name"])}</a></td>'
                f'<td><span class="{cls}" title="{esc(a["role_why"])}">'
                f'{esc(a["role"])}</span></td>'
                f'<td class="num mono">{a["kills"]}{DASH}{a["deaths"]}{DASH}{a["assists"]}</td>'
                f'<td class="num mono">{a["adr"]:.0f}</td>'
                f'<td class="num mono">{a["kd"]:.2f}</td>'
                f'<td class="num mono">{a["hs_pct"]:.0f}%</td>'
                f'<td class="num mono">{a["opening_kills"]}/{a["opens"]}</td>'
                f'<td class="num mono">{tk or "&ndash;"}</td>'
                f'<td class="num mono">{f"{ct_w}/{ct_t}" if ct_t else "&ndash;"}</td>'
                f'<td class="num mono">{util:.0f}</td>'
                f'<td class="num mono">{a["awp_kills"] or "&ndash;"}</td>'
                f'<td class="num mono">{a["rounds"]}</td></tr>')
        pill = "pill ct" if team["side"] == "ct" else (
            "pill t" if team["side"] == "t" else "pill")
        sb_blocks.append(
            f'<div style="display:flex;align-items:center;gap:10px;margin-top:6px">'
            f'<span class="{pill}">{esc(team["label"])}</span>'
            f'<span class="den">{len(team["players"])} players</span></div>'
            f'<div class="tbl-wrap"><table><thead><tr><th>Player</th><th>Role</th>'
            f'<th class="num">K{DASH}D{DASH}A</th><th class="num">ADR</th>'
            f'<th class="num">K/D</th><th class="num">HS</th>'
            f'<th class="num" title="Opening duels won, of those taken">Opening</th>'
            f'<th class="num" title="Kills that traded a teammate who had just died">'
            f'Trades</th>'
            f'<th class="num" title="Clutches won of clutches entered">Clutch</th>'
            f'<th class="num" title="Damage dealt with grenades and molotovs. '
            f'Flashes and smokes do none, so 0 is not an idle player">Nade dmg</th>'
            f'<th class="num">AWP</th>'
            f'<th class="num">Rounds</th></tr></thead>'
            f'<tbody>{"".join(prows)}</tbody></table></div>')

    scoreboard_section = (f"""
  <section>
    <div class="sec-head"><span class="label">Both rosters, counted from the demo</span>
      <h2>Scoreboard</h2></div>
    <p class="lede">Teams are the side each player started on. A demo carries no
      team names, but players do not swap teams while sides swap every half. Roles come
      from what a player actually did; hover one to see the number behind it.</p>
    {"".join(sb_blocks)}
  </section>""" if sb_blocks else "")

    # How early the first duel lands, which is the number the timeline column
    # beside it is full of and nobody wants to average by eye.
    _fb = sorted(q["opening_at"] for q in r["rows"] if q.get("opening_at"))
    first_blood_at = f"{_fb[len(_fb) // 2]:.0f}s" if _fb else "&ndash;"

    # ---- the match as a picture, not as twenty-nine rows
    #
    # A round timeline is a time series and it was a table. Bars are rounds —
    # up for won, height for what was brought — and the line is the running
    # score difference, so a comeback looks like one.
    team = db.team_for_user(user["id"]) if user else None
    _sides = (report_mod._side_by_round(
        team["id"], report_mod.team_anchors(team["id"]).get("anchors", {}))
        if team else {})
    _us_ct = (lambda rn: _sides.get((match_key, rn)) == "ct") if _sides else None
    timeline_chart = charts.round_timeline(r["rows"], _us_ct)

    # ---- where you went tonight
    #
    # Everything positional was season-level, so a coach opening one match —
    # because something went wrong in THAT match — got a scoreboard and no
    # answer to the only question this product is unusually good at.
    where = movement.match_positions(match_key, team["id"]) if team else {}
    where_block = ""
    if where.get("commit") or where.get("death"):
        def zone_table(items, label, heading, trades=False):
            rows_ = "".join(
                f'<tr><td class="name">{esc(z["zone"])}</td>'
                f'<td class="num">{z["n"]}</td>'
                + (f'<td class="num">{rate(z["traded"] or 0, z["n"])}</td>'
                   if trades else "")
                + f'<td class="num">{rate(z["won"], z["n"])}</td></tr>'
                for z in items)
            head = (f'<th class="num" title="First deaths here that a teammate '
                    f'traded back">Traded</th>' if trades else "")
            return (f'<div><div class="sec-head"><span class="label">{label}</span>'
                    f'<h3>{heading}</h3></div>'
                    f'<div class="tbl-wrap"><table><thead><tr><th>Place</th>'
                    f'<th class="num">Rounds</th>{head}'
                    f'<th class="num">Won</th></tr>'
                    f'</thead><tbody>{rows_}</tbody></table></div></div>')

        blocks = []
        if where["commit"]:
            blocks.append(zone_table(where["commit"],
                                     "Furthest the group got, and held",
                                     "Where you went"))
        if where["death"]:
            blocks.append(zone_table(where["death"], "The first of you to fall",
                                     "Where it went wrong", trades=True))

        named = {z["zone"] for z in where["commit"] + where["death"]}
        figs = "".join(
            f'<figure class="zonefig">{q["svg"]}<figcaption class="den">'
            f'{esc((where["map"] or "").replace("de_", ""))}'
            + (f' &middot; {esc(q["level"])} floor' if q["level"] else "")
            + '</figcaption></figure>'
            for q in zone_pictures(where["map"], show=named))

        rr = []
        for x in where["rounds"]:
            res = "win" if x["won"] else "loss"
            went = esc(x["went"]) if x["went"] else "&ndash;"
            at = f'{x["at"]:.0f}s' if x["at"] else "&ndash;"
            died = esc(x["died_in"]) if x["died_in"] else "&ndash;"
            if x["died_in"] and x.get("traded") is not None:
                died += ('' if x["traded"] else
                         ' <span class="den">not traded</span>')
            rr.append(
                f'<tr><td class="num mono">{x["round_num"]}</td>'
                f'<td><span class="pill {x["side"]}">{x["side"].upper()}</span></td>'
                f'<td><span class="res {res}">{"W" if x["won"] else "L"}</span></td>'
                f'<td>{went}</td><td class="num den">{at}</td>'
                f'<td>{died}</td></tr>')

        where_block = f"""
  <section>
    <div class="sec-head"><span class="label">From position data, this match</span>
      <h2>Where you went tonight</h2></div>
    <p class="lede">The reading the season page does, asked of this match alone.
      Where three of you got to together and held, where the first of you died,
      and whether a teammate got him back. Counted only in rounds where your
      side is known.</p>
    <div class="grid2">{"".join(blocks)}</div>
    <div class="zonerow">{figs}</div>
    <details><summary>Round by round</summary>
      <div class="tbl-wrap"><table><thead><tr><th class="num">#</th><th>Side</th>
        <th>Result</th><th>Group reached</th><th class="num">At</th>
        <th>First death</th></tr></thead><tbody>{"".join(rr)}</tbody></table></div>
    </details>
  </section>"""

    # ---- what this one match says, kept deliberately thin
    match_notes = advice.for_match(match_key, team["id"]) if team else []
    notes_block = ""
    if match_notes:
        notes_block = (
            '<section><div class="sec-head"><span class="label">'
            'Worth pulling up at practice</span><h2>From this match</h2></div>'
            + "".join(
                f'<div class="card"><h3>{esc(n["do"])}</h3>'
                f'<p class="lede">{esc(n["because"])}</p>'
                f'<p class="den">{esc(n["evidence"])}</p></div>'
                for n in match_notes) + '</section>')

    # THE SCORE.
    #
    # This used to read score_ct-score_t, which is rounds won by SIDE summed
    # over the whole match. Sides swap at the half, so neither number belongs
    # to a team: one 28-round Inferno showed "16-12" for a match actually won
    # 16-13, and a Mirage showed "22-6" for a 16-13. It is the first number a
    # coach reads and it was not the score.
    sc = report_mod.match_score(match_key, team["id"] if team else None)
    played = (m["played_at"] or "")[:10]
    if sc.get("us") is not None:
        title = f'{sc["map"]} {sc["us"]}–{sc["them"]}'
        crumb_res = {"W": "you won", "L": "you lost"}.get(sc["result"], "drawn")
    elif sc.get("a") is not None:
        title = f'{sc["map"]} {sc["a"]}–{sc["b"]}'
        crumb_res = None
    else:
        title = f'{m["map_name"].replace("de_", "")} {r["score_ct"]}-{r["score_t"]}'
        crumb_res = None
    bits = [esc(m["competition"] or m["tier"])]
    if crumb_res:
        bits.append(crumb_res)
    if sc.get("end_reason") == "surrender":
        bits.append("won by surrender" if sc.get("result") == "W"
                    else "surrendered")
    elif sc.get("end_reason") == "cut":
        bits.append("recording cut short")
    bits.append(f"uploaded {esc(played)}")
    head = banner(title, crumb=" &middot; ".join(bits), label="Match report")

    # Every report was a dead end: no way to the next match, no way back to the
    # list. A coach reviewing a season walks it in order.
    nav_prev = nav_next = ""
    if team is not None:
        seq = [q for q in report_mod.team_matches(team["id"]) if q["match_key"]]
        keys = [q["match_key"] for q in seq]
        if match_key in keys:
            i = keys.index(match_key)
            if i + 1 < len(seq):                     # older
                o = seq[i + 1]
                nav_prev = (f'<a href="/match/{esc(o["match_key"])}">'
                            f'&larr; {esc(o["map"])} '
                            f'{o["us"]}{DASH}{o["them"]}</a>')
            if i > 0:                                # newer
                o = seq[i - 1]
                nav_next = (f'<a href="/match/{esc(o["match_key"])}">'
                            f'{esc(o["map"])} {o["us"]}{DASH}{o["them"]} &rarr;</a>')
    match_nav = (f'<nav class="pager"><span>{nav_prev}</span>'
                 f'<a class="den" href="/matches">All matches</a>'
                 f'<span>{nav_next}</span></nav>')

    body = f"""
  {match_nav}

  {notes_block}

  <section>
    <div class="stat-row">
      <div class="stat"><span class="stat-n">{r["n_rounds"]}</span>
        <span class="label">rounds</span></div>
      <div class="stat"><span class="stat-n">{first_blood_at}</span>
        <span class="label">median first blood</span></div>
      <div class="stat"><span class="stat-n">{r["deaths"]}</span>
        <span class="label">deaths</span></div>
      <div class="stat"><span class="stat-n">{r["plants"]}</span>
        <span class="label">bombs planted</span></div>
    </div>
  </section>

  {scoreboard_section}

  <section>
    <div class="sec-head"><span class="label">The first duel of the round</span>
      <h2>Opening duels</h2></div>
    <p class="lede">Who lost the first player, and what happened next. Counted from
      the demo, not estimated. The round numbers are listed so you can open
      the match and watch them.</p>
    <div class="tbl-wrap"><table>
      <thead><tr><th>Side</th><th class="num">Won after losing it</th>
        <th class="num">Won after winning it</th><th>Rounds they lost it</th></tr></thead>
      <tbody>{"".join(od)}</tbody></table></div>
  </section>

  <section>
    <div class="sec-head"><span class="label">By what they could afford</span>
      <h2>Buys</h2></div>
    <div class="tbl-wrap"><table>
      <thead><tr><th>Side and buy</th><th class="num">Rounds won</th>
        <th>Which rounds</th></tr></thead>
      <tbody>{"".join(br)}</tbody></table></div>
  </section>

  <section>
    <div class="sec-head"><span class="label">Every round</span><h2>Timeline</h2></div>
    <p class="lede">Each bar is a round: above the line if you won it, as tall
      as the equipment you brought to it. A tall bar pointing down is a full buy you
      lost; a stub pointing up is a round won on nothing. The grey line is the score
      difference as it moved.</p>
    <div class="chart">{timeline_chart}</div>
    <details><summary>Every round as a table</summary>
      <div class="tbl-wrap"><table>
        <thead><tr><th class="num">#</th><th>Won</th><th>Buy</th>
          <th class="num">CT $</th><th class="num">T $</th>
          <th class="num">Deaths</th><th>Opening duel</th><th>Plant</th></tr></thead>
        <tbody>{"".join(trs)}</tbody></table></div>
    </details>
  </section>

  {where_block}

  <section>
    <p class="note"><strong>Everything above is counted.</strong> Nothing on this
      page is modeled, estimated or predicted. It is arithmetic over the
      rounds in this demo, with the denominator beside every rate. Anything under
      {report_mod.MIN_CHANCES} chances shows raw counts and a
      <span class="pill beta">thin</span> label instead of a percentage.</p>
    <p class="warn"><strong>Not here yet: decision scoring.</strong> Which decision
      cost you a round you were winning is the one thing on a Counterplay report
      that needs a trained model, and the league corpus does not exist yet. It
      stays off rather than showing a number that came out of a simulator.</p>
  </section>"""
    return html_page("Match report", head, body, user)



@app.get("/players", response_class=HTMLResponse)
def players_page(request: Request):
    """Season player stats for the signed-in coach's own team."""
    user, redirect = require_user(request)
    if redirect:
        return redirect
    team = db.team_for_user(user["id"])
    if team is None:
        return see_other("/dashboard")

    squad = report_mod.squad(team["id"])
    DASH = "&ndash;"

    if not (squad["yours"] or squad["others"]):
        return html_page("Players", banner("Players", crumb=esc(team["name"])),
                         empty_state("players", team["name"]), user)

    ROLE_CLASS = {"AWP": "role awp", "Entry": "role entry"}

    def player_rows(people):
        out = []
        for a in people:
            cls = ROLE_CLASS.get(a["role"], "role")
            thin = ' <span class="thin">thin</span>' if a["thin"] else ""
            # A side never played shows a dash, not a zero: "0" reads as
            # "terrible on T" when it means "never played T".
            ct_adr = f'{a["ct_adr"]:.0f}' if a["ct_rounds"] else "&ndash;"
            t_adr = f'{a["t_adr"]:.0f}' if a["t_rounds"] else "&ndash;"
            # "105/97" read as a broken fraction. One flashbang can blind
            # three people, so this is a rate per flash, not a share of them.
            flash = (f'{a["blind_per_flash"]:.2f}'
                     if a["flashes_thrown"] else "&ndash;")
            clutch = (f'{a["clutch_won"]}/{a["clutch_tried"]}'
                      if a["clutch_tried"] else "&ndash;")
            traded = (f'{a["traded_pct"]:.0f}%' if a["deaths"] else "&ndash;")
            out.append(
                f'<tr><td class="name">'
                f'<a href="/player/{esc(a["steamid"])}">{esc(a["name"])}</a>{thin}</td>'
                f'<td><span class="{cls}" title="{esc(a["role_why"])}">'
                f'{esc(a["role"])}</span></td>'
                f'<td class="num mono">{a["matches"]}</td>'
                f'<td class="num mono">{a["rounds"]}</td>'
                f'<td class="num mono">{a["adr"]:.0f}</td>'
                f'<td class="num mono">{ct_adr} / {t_adr}</td>'
                f'<td class="num mono">{a["kd"]:.2f}</td>'
                f'<td class="num mono">{a["hs_pct"]:.0f}%</td>'
                f'<td class="num mono">{a["opening_kills"]}/{a["opens"]}</td>'
                f'<td class="num mono">{traded}</td>'
                f'<td class="num mono">{a["util_adr"]:.1f}</td>'
                f'<td class="num mono">{a["awp_kills"] or "&ndash;"}</td></tr>')
        return "".join(out)

    # Nine columns, not sixteen.
    #
    # Trades, clutches, multi-kills and flashes were added to the roster table
    # without anything being taken away, and it grew to 1,285px — wider than a
    # 1,280px desktop screen, so it scrolled sideways on a full monitor. They
    # are per-player detail and they belong on the player's own page, which is
    # where a coach is when they care about them.
    HEAD = (f'<thead><tr><th>Player</th><th>Role</th><th class="num">Matches</th>'
            f'<th class="num">Rounds</th><th class="num">ADR</th>'
            f'<th class="num">ADR CT / T</th><th class="num">K/D</th>'
            f'<th class="num">HS</th>'
            f'<th class="num" title="Opening duels won, of those taken">Opening</th>'
            f'<th class="num" title="Share of this player&rsquo;s deaths that a '
            f'teammate traded back">Traded</th>'
            f'<th class="num" title="Grenade and molotov damage per round">'
            f'Nade dmg</th>'
            f'<th class="num">AWP</th></tr></thead>')

    yours, others = squad["yours"], squad["others"]
    blocks = []
    if yours:
        blocks.append(
            f'<section><div class="sec-head"><span class="label">'
            f'Who keeps turning up</span><h2>Your players</h2></div>'
            f'<p class="lede">A demo carries no roster, so these are the players who '
            f'appear in more than one of your matches. Your opponents each play you '
            f'once; your own team plays all of them, which is enough to tell the two '
            f'apart without anyone typing in a Steam ID.</p>'
            f'<div class="tbl-wrap"><table>{HEAD}'
            f'<tbody>{player_rows(yours)}</tbody></table></div></section>')
    if others:
        note = ('' if yours else
                '<p class="note">Only one match so far, so everyone appears in all of '
                'it and there is no way yet to tell your players from theirs. Upload a '
                'second match and this splits itself.</p>')
        blocks.append(
            f'<section><div class="sec-head"><span class="label">'
            f'Seen once, in one of your matches</span>'
            f'<h2>Everyone else in your demos</h2></div>{note}'
            f'<p class="lede">Opponents, kept because their numbers are the context '
            f'yours sit in, but they are not your team and they do not belong in '
            f'the same table.</p>'
            f'<details><summary>Show {len(others)} other players</summary>'
            f'<div class="tbl-wrap"><table>{HEAD}'
            f'<tbody>{player_rows(others)}</tbody></table></div></details></section>')

    total_rounds = sum(a["rounds"] for a in yours) or sum(a["rounds"] for a in others)
    matches = max((a["matches"] for a in (yours or others)), default=0)
    body = f"""
  <section>
    <div class="stat-row">
      <div class="stat"><span class="stat-n">{len(yours) or len(others)}</span>
        <span class="label">{"your players" if yours else "players"}</span></div>
      <div class="stat"><span class="stat-n">{matches}</span>
        <span class="label">matches</span></div>
      <div class="stat"><span class="stat-n">{total_rounds}</span>
        <span class="label">player-rounds</span></div>
    </div>
  </section>
  {"".join(blocks)}
  <section>
    <p class="note"><strong>Counted, not modeled.</strong> Every figure here is
      arithmetic over parsed rounds. CT and T damage are kept apart on purpose: a
      player at 90 ADR as CT and 60 as T has a specific problem, and one averaged
      number hides it. Anyone under {report_mod.MIN_ROUNDS_FOR_ROLE} rounds is marked
      thin and gets no role. Trades, clutches, multi-kill rounds and flash
      figures are on each player&rsquo;s own page; click a name.</p>
  </section>"""
    return html_page("Players", banner("Players", crumb=esc(team["name"]),
                                       label="Season player stats"), body, user)



END_LABEL = {"surrender": "surrendered", "cut": "recording cut short"}


# Zone pictures, drawn once and reused.
#
# A pattern that says "top mid" is unreadable to anyone who did not name the
# zones themselves, and every one of these names was typed by one person
# looking at one picture. The picture belongs next to the table.
#
# Rendering costs a clustering pass over a map's samples, so it is cached: the
# stored zone model only changes when someone deliberately rebuilds it.
_ZONE_PIC: dict[tuple, str] = {}


def zone_pictures(map_name: str, show=None, width: int = 420) -> list[dict]:
    """One drawing per floor: [{"level": str|None, "svg": str}, ...].

    A split map gets BOTH floors, not the busier one. Nuke's whole difficulty
    is that its two bombsites sit 369 units above each other — drawing only the
    floor with more traffic hides the site the tables are talking about, which
    on Nuke is exactly the thing a coach came to see.

    `show` is the set of place names the page's tables refer to. Only those get
    a label; everything else is a faint dot.
    """
    key = (map_name, tuple(sorted(show)) if show else None, width)
    if key in _ZONE_PIC:
        return _ZONE_PIC[key]

    out: list[dict] = []
    try:
        import numpy as np

        from counterplay import (mapwalk as MW, radar as RD,
                                  zonemodel as ZM, zones as Z)

        zs = ZM.load(map_name)
        names = ZM.names(map_name)
        if zs and names:
            rows = db.query("""SELECT rp.data FROM round_positions rp
                                 JOIN matches m ON m.match_key = rp.match_key
                                WHERE m.map_name = ?""", map_name)
            x, y, z = Z.collect([r["data"] for r in rows], thin=2, alive_only=False)
            if len(x):
                geom_all = MW.load(map_name)
                split = ZM.SPLIT_LEVELS.get(map_name)
                if split is None:
                    floors = [(None, list(range(len(zs))),
                               np.ones(len(x), dtype=bool), geom_all)]
                else:
                    floors = []
                    for level, above in (("upper", True), ("lower", False)):
                        idx = [i for i, q in enumerate(zs) if q["level"] == level]
                        if not idx:
                            continue
                        sel = (z >= split) if above else (z < split)
                        g = None
                        if geom_all is not None:
                            gs = (geom_all[2] >= split) if above else (geom_all[2] < split)
                            g = (geom_all[0][gs], geom_all[1][gs], geom_all[2][gs])
                        floors.append((level, idx, sel, g))

                for level, idx, sel, geom in floors:
                    if not idx or not sel.any():
                        continue
                    centres = np.array([[zs[i]["cx"], zs[i]["cy"], zs[i]["cz"]]
                                        for i in idx])
                    anchors = np.array([ZM.label_pos(zs[i]) for i in idx])
                    counts = np.array([zs[i]["share"] for i in idx])
                    # One pill per NAME, not per cluster.
                    #
                    # Zones were named by hand, and a place a person thinks of
                    # as one place is often three clusters: Mirage came back
                    # with "A main" written across the middle of the picture
                    # three times, which reads as a drawing error rather than
                    # as one area covered by three shapes. The shapes still all
                    # draw, so the extent is unchanged; only the biggest one of
                    # each name carries the label.
                    biggest: dict[str, int] = {}
                    for i in idx:
                        nm = names.get(i + 1, "")
                        if not nm:
                            continue
                        if (nm not in biggest
                                or zs[i]["share"] > zs[biggest[nm]]["share"]):
                            biggest[nm] = i
                    labels = []
                    for i in idx:
                        nm = names.get(i + 1, "")
                        wanted = (show is None or nm in show) and biggest.get(nm) == i
                        labels.append(nm if wanted else "")
                    rad = RD.available(map_name, level)
                    # Valve's alpha channel says where the map is, which is
                    # the one thing position data cannot say about a corner
                    # nobody walks into.
                    msk = None
                    if rad is not None:
                        from counterplay import radarmask as RM
                        try:
                            msk = RM.sample(map_name, level, *Z.picture_extent(
                                x[sel], y[sel], rad), 150, rad)
                        except Exception:
                            msk = None
                    out.append({"level": level, "credit": rad and rad["credit"],
                                "svg": Z.svg(x[sel], y[sel], centres, counts,
                                             width=width,
                                             first_number=idx[0] + 1,
                                             labels=labels, geometry=geom,
                                             radar=rad, anchors=anchors,
                                             mask=msk)})
    except Exception:
        out = []            # a missing picture must never break the page
    _ZONE_PIC[key] = out
    return out


def empty_state(what: str, team_name: str = "") -> str:
    """The page a coach sees before they have uploaded anything.

    Not an apology and not an error. It says what this page will hold, what to
    do to fill it, and — because the thing coaches actually worry about is
    whether it is worth the effort — what they get back for one match.

    The same block on every page, with the page's own promise swapped in, so
    an empty product still reads as a product rather than as a broken one.
    """
    PROMISE = {
        "matches": ("One page per match", [
            "The real score, followed through the side swap",
            "A timeline you can read at a glance instead of a table",
            "Where your group went, and where the first of you died"]),
        "players": ("Your five, separated from your opponents", [
            "Roles read off what a player did, not off a label they picked",
            "CT and T damage kept apart, because they are different problems",
            "Match by match, so you can see a bad night against a bad level"]),
        "stats": ("What repeats across a season", [
            "The habits you have without deciding to",
            "Where on each map your rounds are actually being lost",
            "A short list of what to work on, with the counts behind it"]),
        "trends": ("Whether the thing you fixed is holding", [
            "Match by match, filtered to one map",
            "Your last three against everything before them"]),
    }
    title, bullets = PROMISE.get(what, PROMISE["stats"])
    items = "".join(f'<li>{b}</li>' for b in bullets)
    return f"""
  <section>
    <div class="card" style="gap:16px">
      <span class="label">Nothing here yet</span>
      <h2>{title}</h2>
      <p class="lede">This page fills in the moment your first demo finishes
        parsing, which takes under a minute. One match is enough to see a
        scoreboard and a timeline; three or four is enough for the patterns,
        because nothing here is reported until it has happened often enough to
        mean something.</p>
      <ul class="lede" style="margin:0;padding-left:20px">{items}</ul>
      <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:4px">
        <a class="btn" href="/dashboard">Upload a demo</a>
        <a class="btn ghost" href="/sample-report.html">See a filled-in example</a>
      </div>
    </div>
  </section>

  <section>
    <div class="sec-head"><span class="label">Where to find them</span>
      <h2>Getting your demos</h2></div>
    <div class="grid2">
      <div class="card"><h3>FACEIT</h3>
        <p class="lede">Open the match room and use the download button. You get a
          <code>.dem.zst</code> file, which is what this expects, so there is no need to
          unpack it.</p></div>
      <div class="card"><h3>Valve matchmaking</h3>
        <p class="lede">In CS2: <b>Watch &rarr; Your Matches</b>, then Download beside
          the match. Files land in your <code>csgo/replays</code> folder.</p></div>
    </div>
    <p class="note"><strong>Grab them while they are fresh.</strong> FACEIT and Valve
      both delete match demos after a few weeks. The ones worth keeping are the ones
      you save now. A season you cannot download is a season this cannot
      analyze.</p>
  </section>"""


@app.get("/trends", response_class=HTMLResponse)
def trends_page(request: Request, map: str = "", metric: str = "win_pct"):
    """Match by match, so a coach can ask whether something is holding.

    The gap this fills: a season total and a single match, with nothing in
    between. "Show me the last three Mirages" and "is the thing we fixed still
    fixed" are the two questions a coach actually asks between Tuesday and
    Saturday, and neither end of the product could answer either.

    Filtering by map is not a convenience. A team's Mirage and its Nuke are
    different teams, and an average across both hides one improving while the
    other rots.
    """
    user, redirect = require_user(request)
    if redirect:
        return redirect
    team = db.team_for_user(user["id"])
    if team is None:
        return see_other("/dashboard")

    METRICS = {
        "win_pct":     ("Rounds won", "%", "Share of rounds you took."),
        "adr":         ("Damage per round", "", "Your players only, not both sides."),
        "traded_pct":  ("Deaths traded", "%",
                        "When one of you dies, how often a teammate trades it back."),
        "opening_pct": ("Opening duels won", "%",
                        "Of the opening duels your players were in."),
    }
    if metric not in METRICS:
        metric = "win_pct"
    maps = report_mod.maps_played(team["id"])
    series = report_mod.match_series(team["id"], map or None)

    if len(series) < 2:
        if not report_mod.team_matches(team["id"]):
            return html_page("Trends", banner("Trends", crumb=esc(team["name"])),
                             empty_state("trends", team["name"]), user)
        body = ('<section><p class="note">Two matches are the minimum for a trend, '
                'and a trend on one map needs two on that map. Try '
                '<a href="/trends">all maps</a>, or upload another.</p></section>')
        return html_page("Trends", banner("Trends", crumb=esc(team["name"])),
                         body, user)

    label, unit, blurb = METRICS[metric]
    # A label that distinguishes three Mirages from each other: the map plus
    # where the match sits in the season. Truncating to three characters made
    # every Mirage read "mir".
    pts = [(f'{m["map"][:6]} {i + 1}', m[metric], m["result"] or "")
           for i, m in enumerate(series) if m.get(metric) is not None]
    vals = [v for _, v, _ in pts]
    avg = sum(vals) / len(vals) if vals else 0

    # Is it holding? Compare the most recent three against everything before
    # them. Stated as a difference with both counts, never as a trend line
    # fitted through eleven points.
    verdict = ""
    if len(vals) >= 5:
        recent, before = vals[-3:], vals[:-3]
        r_avg = sum(recent) / len(recent)
        b_avg = sum(before) / len(before)
        d = r_avg - b_avg
        word = ("better" if d > 3 else "worse" if d < -3 else "about the same")
        verdict = (
            f'<div class="note"><strong>Last three against everything before '
            f'them:</strong> {r_avg:.0f}{unit} versus {b_avg:.0f}{unit}, '
            f'which is {word}. Three matches is a small number and this is a '
            f'difference, not a trend; treat it as a question to check rather '
            f'than an answer.</div>')

    chart = charts.trend(pts, width=760, height=236, unit=unit,
                         is_pct=bool(unit))

    tabs = "".join(
        f'<a class="btn ghost{" on" if metric == k else ""}" '
        f'href="/trends?metric={k}{"&map=" + esc(map) if map else ""}">'
        f'{esc(v[0])}</a>' for k, v in METRICS.items())
    map_tabs = (f'<a class="btn ghost{" on" if not map else ""}" '
                f'href="/trends?metric={esc(metric)}">All maps</a>'
                + "".join(
                    f'<a class="btn ghost{" on" if map == mp else ""}" '
                    f'href="/trends?metric={esc(metric)}&map={esc(mp)}">'
                    f'{esc(mp.replace("de_", ""))} <span class="den">{n}</span></a>'
                    for mp, n in maps))

    rows = []
    for m in reversed(series):
        if None in (m["adr"], m["traded_pct"], m["opening_pct"]):
            continue
        res = "&ndash;"
        if m["result"]:
            cls = "win" if m["result"] == "W" else "loss"
            res = f'<span class="res {cls}">{m["result"]}</span>'
        rows.append(
            f'<tr><td class="name">'
            f'<a href="/match/{esc(m["match_key"])}">{esc(m["map"])}</a></td>'
            f'<td>{res}</td>'
            f'<td class="num mono">{m["us"]}&ndash;{m["them"]}</td>'
            f'<td class="num mono">{m["win_pct"]:.0f}%</td>'
            f'<td class="num mono">{m["adr"]:.0f}</td>'
            f'<td class="num mono">{m["traded_pct"]:.0f}%</td>'
            f'<td class="num mono">{m["opening_pct"]:.0f}%</td></tr>')
    rows = "".join(rows)

    body = f"""
  <section>
    <div class="sec-head"><span class="label">Match by match</span>
      <h2>{esc(label)}</h2></div>
    <p class="lede">{esc(blurb)} Oldest on the left. The shaded band is your own
      average across the matches shown, so a point above it is a match better than
      your normal and a point below is worse.</p>
    <div style="display:flex;gap:7px;flex-wrap:wrap">{tabs}</div>
    <div style="display:flex;gap:7px;flex-wrap:wrap">{map_tabs}</div>
    <div class="chart">{chart}</div>
    {verdict}
  </section>

  <section>
    <div class="sec-head"><span class="label">Newest first</span>
      <h2>Every match{" on " + esc(map.replace("de_", "")) if map else ""}</h2></div>
    <div class="tbl-wrap"><table>
      <thead><tr><th>Map</th><th>Result</th><th class="num">Score</th>
        <th class="num">Rounds won</th><th class="num">ADR</th>
        <th class="num">Traded</th><th class="num">Opening</th></tr></thead>
      <tbody>{rows}</tbody></table></div>
  </section>

  <section>
    <p class="note"><strong>Still counted, not modeled.</strong> Every point is one
      match's arithmetic. No line is fitted through them and no direction is
      predicted. A trend you can see is a trend; a trend that needs a
      regression to see is not one yet.</p>
  </section>"""
    return html_page("Trends", banner("Trends", crumb=esc(team["name"]),
                                      label="Is it holding?"), body, user)


@app.get("/matches", response_class=HTMLResponse)
def matches_page(request: Request):
    """Every match this team has sent in, named the way a coach names one."""
    user, redirect = require_user(request)
    if redirect:
        return redirect
    team = db.team_for_user(user["id"])
    if team is None:
        return see_other("/dashboard")

    items = report_mod.team_matches(team["id"])
    if not items:
        return html_page("Matches", banner("Matches", crumb=esc(team["name"])),
                         empty_state("matches", team["name"]), user)

    rows = []
    for m in items:
        if m["match_key"] and m["result"]:
            cls = "win" if m["result"] == "W" else "loss" if m["result"] == "L" else ""
            score = (f'<span class="res {cls}">{m["result"]}</span> '
                     f'<span class="mono">{m["us"]}&ndash;{m["them"]}</span>')
        elif m["match_key"]:
            score = f'<span class="mono">{m["us"]}&ndash;{m["them"]}</span>'
        else:
            score = '<span class="den">&ndash;</span>'

        chip = map_chip(f'de_{m["map"]}' if m["map"] and not
                        str(m["map"]).startswith("de_") else (m["map"] or ""),
                        label=m["map"] or "match")
        name = (f'<a href="/match/{esc(m["match_key"])}">{chip}</a>'
                if m["match_key"] else (chip if m["map"] else esc(m["filename"])))
        tag = END_LABEL.get(m.get("end_reason") or "")
        cut = f' <span class="pill">{tag}</span>' if tag else ""
        status = ('' if m["status"] == "parsed"
                  else f'<span class="pill">{esc(m["status"])}</span>')
        rows.append(
            f'<tr><td class="name">{name}{cut}'
            f'<div class="den" style="font-weight:400" title="{esc(m["filename"])}">'
            f'{esc(m["tier"] or "")} &middot; uploaded {esc(m["uploaded"])}</div></td>'
            f'<td class="num">{score}</td>'
            f'<td class="num mono">{m["rounds"] or "&ndash;"}</td>'
            f'<td class="num">{status}</td></tr>')

    played = [m for m in items if m["result"]]
    won = sum(1 for m in played if m["result"] == "W")
    body = f"""
  <section>
    <div class="stat-row">
      <div class="stat"><span class="stat-n">{len(items)}</span>
        <span class="label">matches</span></div>
      <div class="stat"><span class="stat-n">{won}&ndash;{len(played) - won}</span>
        <span class="label">record</span></div>
      <div class="stat"><span class="stat-n">{sum(m["rounds"] or 0 for m in items)}</span>
        <span class="label">rounds</span></div>
    </div>
  </section>
  <section>
    <div class="sec-head"><span class="label">Newest first</span>
      <h2>Every match you have sent in</h2></div>
    <p class="lede">Scores are the real result, followed through the side swap
      rather than summed by side. CT and T are not teams, and a match that
      ends 13&ndash;9 reads as 16&ndash;6 if you add up the sides instead.
      A CS2 demo carries no match date, so the date shown is when the file was
      uploaded; the order is the true one.</p>
    <div class="tbl-wrap"><table>
      <thead><tr><th>Match</th><th class="num">Score</th>
        <th class="num">Rounds</th><th class="num">Status</th></tr></thead>
      <tbody>{"".join(rows)}</tbody></table></div>
  </section>"""
    return html_page("Matches", banner("Matches", crumb=esc(team["name"]),
                                       label="Match reports"), body, user)


@app.get("/stats", response_class=HTMLResponse)
def stats_page(request: Request):
    """Team stats and recurring patterns, across every match the team sent in."""
    user, redirect = require_user(request)
    if redirect:
        return redirect
    team = db.team_for_user(user["id"])
    if team is None:
        return see_other("/dashboard")

    st = report_mod.team_stats(team["id"])
    if st is None:
        return html_page("Team stats",
                         banner("Team stats", crumb=esc(team["name"])),
                         empty_state("stats", team["name"]), user)

    DASH = "&ndash;"
    rate = report_mod.rate
    patterns = report_mod.recurring_patterns(team["id"])

    # ---- what to do on Monday
    #
    # The product was scrupulous about not over-claiming and never landed a
    # recommendation as a result: "first death in top mid 8 of 32, you win 1"
    # sat one sentence away from "stop taking that duel" and never took the
    # step. Every line here is a conclusion from a fact already proved, with
    # the fact printed underneath so a coach can argue with the reasoning
    # rather than having to trust it.
    plan = advice.monday(team["id"])
    if plan["items"]:
        def advice_card(it):
            tag = "keep doing this" if it["good"] else "worth changing"
            cls = "on" if it["good"] else "t"
            side = (it["side"] or "").upper()
            ev = "".join(f'<li>{esc(e)}</li>' for e in it["evidence"])
            # A finding counted in flashes or in dollars brings its own
            # closing line. The default one is a share of rounds against the
            # team's round win rate, which is only true of the rest.
            foot = it.get("foot") or (
                f'{it["rate"]:.0f}% against your {plan["baseline"]:.0f}% '
                f'overall, a gap of {abs(it["gap"]):.0f} points across '
                f'{it["of"]} rounds')
            return (
                f'<div class="card advice{" good" if it["good"] else ""}">'
                f'<div style="display:flex;gap:9px;align-items:center;'
                f'flex-wrap:wrap"><span class="pill {cls}">{tag}</span>'
                + (f'<span class="pill {it["side"]}">{side}</span>' if side else "")
                + f'</div><h3>{esc(it["do"])}</h3>'
                f'<p class="lede">{esc(it["because"])}</p>'
                f'<ul class="den" style="margin:0;padding-left:17px">{ev}</ul>'
                f'<p class="den">{esc(foot)}</p></div>')

        # Grouped by map, because practice is planned one map at a time. The
        # ranking still decides the order of the groups and of the cards inside
        # them, so what matters most is still read first.
        groups = []
        for mp, items in plan["by_map"]:
            head = (f'<div class="sec-head"><span class="label">'
                    f'{"On " + esc(mp) if mp else "Across every map"}</span>'
                    f'<h3>{len(items)} thing{"s" if len(items) != 1 else ""} '
                    f'to work on</h3></div>')
            groups.append(f'<div style="margin-bottom:22px">{head}'
                          f'<div class="grid2">'
                          f'{"".join(advice_card(i) for i in items)}</div></div>')
        monday_block = f"""
  <section class="lead">
    <div class="sec-head"><span class="label">Read this one first</span>
      <h2>What to work on</h2></div>
    <p class="lede">Every line below is a conclusion drawn from something counted
      further down this page, ranked by how many rounds it covers and how far it
      sits from your own average of {plan['baseline']:.0f}%. Nothing here is
      predicted. The evidence is printed under each one, so you can disagree
      with the reasoning rather than having to take it on trust.</p>
    {"".join(groups)}
  </section>"""
    else:
        monday_block = ""

    # ---- recent form
    #
    # A season total cannot show whether the thing you fixed in practice held.
    form = report_mod.recent_form(team["id"])
    if form and any(f["result"] for f in form):
        cards = []
        for f in form:
            cls = ("win" if f["result"] == "W" else
                   "loss" if f["result"] == "L" else "")
            score = (f'{f["us"]}{DASH}{f["them"]}' if f["us"] is not None
                     else "&ndash;")
            cards.append(
                f'<a class="formcard" href="/match/{esc(f["match_key"])}">'
                f'<span class="res {cls}">{esc(f["result"] or "?")}</span>'
                f'<span class="mono">{score}</span>'
                f'<span class="den">{esc(f["map"])}</span></a>')
        form_block = (
            f'<section><div class="sec-head"><span class="label">'
            f'Newest first</span><h2>Recent form</h2></div>'
            f'<p class="lede">Your last {len(form)} matches, with the real '
            f'result. Click one to open its report.</p>'
            f'<div class="formrow">{"".join(cards)}</div></section>')
    else:
        form_block = ""

    # ---- recurring patterns
    #
    # The bar length is the CHANCES and the fill is what came of them, so a
    # 5-of-6 and a 40-of-48 look like different weights of evidence even though
    # the percentages are close. That is the same point the printed denominator
    # makes, made visually.
    # Full names, not truncated. The label sits above its bar precisely so it
    # does not have to fit in a column.
    # Every pattern, not the first seven. The cut was arbitrary and it dropped
    # eco rounds off the bottom of the picture while leaving them in the table
    # beside it — two views of the same list that disagreed about its length.
    patterns_chart = charts.bars(
        [(p_["name"], p_["hit"], p_["of"]) for p_ in patterns],
        width=600) if patterns else ""
    if patterns:
        # The explanation of each pattern used to sit under it as a paragraph.
        # Nine patterns meant nine paragraphs, and the page was mostly prose
        # about numbers rather than the numbers. It now lives behind the "i",
        # which is readable on hover, on focus, and by a screen reader through
        # aria-describedby — nothing is hidden from anybody, it is just no
        # longer in the way of the column a coach is reading down.
        prows = []
        for i_, p_ in enumerate(patterns):
            side = (f'<span class="pill {p_["side"]}">{p_["side"].upper()}</span> '
                    if p_["side"] else "")
            tid_ = f"pt{i_}"
            info = (f'<span class="info" tabindex="0" role="button"'
                    f' aria-describedby="{tid_}" aria-label="What this means">i'
                    f'<span class="tip" role="tooltip" id="{tid_}">'
                    f'{esc(p_["detail"])}</span></span>')
            prows.append(
                f'<tr><td class="name">{side}{esc(p_["name"])}{info}</td>'
                f'<td class="num">{rate(p_["hit"], p_["of"])}</td></tr>')
        patterns_block = (
            f'<div class="tbl-plain"><table><thead><tr><th>Pattern</th>'
            f'<th class="num">Observed / chances</th></tr></thead>'
            f'<tbody>{"".join(prows)}</tbody></table></div>')
    else:
        patterns_block = (
            f'<p class="note">Nothing has happened often enough to call a pattern '
            f'yet. A line appears here once it has at least '
            f'{report_mod.MIN_PATTERN_CHANCES} chances behind it, usually two '
            f'or three matches.</p>')

    # ---- utility
    #
    # Outcome, not activity. The first version of this counted grenades thrown
    # and grenades that landed, and neither is a reason to change anything:
    # a coach cannot act on "you threw 374 flashes". What they can act on is
    # whether anybody dies behind the flash, what the unthrown grenades cost,
    # and how much ground the fire actually took away.
    #
    # Four cards and one line. A utility section big enough for its own page
    # would push everything below it off the screen, and the finer per-player
    # numbers already live on each player's page.
    util = utility.summary(team["id"])
    if util:
        uf, uu, us = util["flashes"], util["unused"], util["space"]
        cards = []

        def ucard(big, label, den, tip=""):
            info = ""
            if tip:
                tid = f"ut{len(cards)}"
                info = (f'<span class="info" tabindex="0" role="button"'
                        f' aria-describedby="{tid}" aria-label="What this means">i'
                        f'<span class="tip" role="tooltip" id="{tid}">{esc(tip)}'
                        f'</span></span>')
            cards.append(
                f'<div class="stat"><span class="stat-n">{big}</span>'
                f'<span class="label">{esc(label)}{info}</span>'
                f'<span class="den">{den}</span></div>')

        hit_pct = 100.0 * uf["hit_enemy"] / uf["thrown"] if uf["thrown"] else 0
        ucard(f"{hit_pct:.0f}%", "of your flashes blind an opponent",
              f'{uf["hit_enemy"]} of {uf["thrown"]} thrown',
              f'Counted per flash, not per player blinded: one flashbang '
              f'blinds everyone who can see it. Those {uf["hit_enemy"]} '
              f'flashes took {uf["enemy_secs"]:.0f} seconds of sight off the '
              f'opposition. {uf["hit_own"]} of your flashes also blinded your '
              f'own side, for {uf["own_secs"]:.0f} seconds.')
        kill_pct = 100.0 * uf["got_a_kill"] / uf["thrown"] if uf["thrown"] else 0
        ucard(f"{kill_pct:.0f}%", "of your flashes get somebody killed",
              f'{uf["got_a_kill"]} of {uf["thrown"]} thrown',
              f'An opponent this flash blinded, who then died before it wore '
              f'off. {uf["kills_from"]} opponents in all. This is the only '
              f'reason to throw one, and it is a long way below the share that '
              f'merely land.')
        if us and us["molotovs"]:
            deny_pct = 100.0 * us["denied"] / us["molotovs"]
            ucard(f"{deny_pct:.0f}%", "of your molotovs deny space",
                  f'{us["denied"]} of {us["molotovs"]} thrown',
                  f'A molotov an opponent had to stand in, walk out of, or go '
                  f'round, read from the position samples. Between them they '
                  f'took {us["denied_secs"]:.0f} seconds of ground away, and '
                  f'{us["moved"]} pushed somebody back out of it. The other '
                  f'{us["empty"]} burned with nobody near them at any point.')
        if uu and uu["spent"]:
            ucard(f'${uu["per_round"]:.0f}', "of utility wasted per round",
                  f'${uu["wasted"]:,} of ${uu["spent"]:,} bought',
                  f'Grenades still in a player\'s hand at the moment they '
                  f'died, priced at what they cost. Grenades a survivor kept '
                  f'are not counted: carrying a smoke into the next round is '
                  f'not waste. Across {uu["rounds"]} rounds that is '
                  f'{uu["unused"]} grenades that bought nothing.')

        smoke_line = ""
        if us and us["smokes"]:
            smoke_line = (
                f'<p class="den" style="margin-top:2px">An opponent walked '
                f'through {us["crossed"]} of your {us["smokes"]} smokes. '
                f'The other {us["uncrossed"]} nobody crossed while they were up '
                f'&ndash; which is not the same as nobody wanting to.</p>')
        utility_block = f"""
  <section>
    <div class="sec-head"><span class="label">What your grenades did</span>
      <h2>Utility</h2></div>
    <p class="lede">What the utility achieved, counted per grenade from the
      demo, not how much of it was thrown.</p>
    <div class="stat-row">{"".join(cards)}</div>
    {smoke_line}
  </section>"""
    else:
        utility_block = ""

    # ---- positional patterns: where they actually play
    #
    # Grouped by what the pattern is ABOUT rather than sorted into one list.
    # "Where your group ends up" and "where your first death happens" are
    # different questions and a coach reads them differently.
    pos = movement.positional_patterns(team["id"])
    POS_SECTIONS = (
        ("commit", "Where your group ends up",
         "The furthest three of you get together and hold, inside the first "
         f"{int(movement.COMMIT_TO)} seconds. Corridors everyone walks through "
         "are not destinations, so they only appear here when the group never "
         "got past them, which is itself worth seeing."),
        ("setup", "Your default setup",
         f"Where two or more of you are standing {int(movement.SETUP_AT)} seconds "
         "in: after the round has taken shape, before contact decides it."),
        ("death", "Where your first death happens",
         "The first of you to die, where, and whether anybody got him back. "
         "The same death traded leaves a 4v4 and untraded leaves a 4v5, which "
         "is the difference between a place you lose men and a place you lose "
         "rounds."),
    )
    # Five rows, not twenty.
    #
    # "Where your first death happens" ran to twenty rows with seventeen of
    # them marked thin, which buried the one line worth acting on — mirage T,
    # top mid, first death in 8 of 32 rounds and one round won from them — at
    # position three of twenty. A table nobody reads to the bottom of should
    # not have a bottom.
    POS_TOP_N = 5
    pos_blocks = []
    # Which places each map's tables actually mention, so the maps can be drawn
    # ONCE at the end with only those labeled. Drawing one per section put the
    # same Mirage picture on the page three times.
    shown_zones: dict[str, set] = {}
    for kind, title, lede in POS_SECTIONS:
        sel = [q for q in pos if q["kind"] == kind]
        if not sel:
            continue
        hidden = max(0, len(sel) - POS_TOP_N)
        sel = sel[:POS_TOP_N]
        # Only a first death can be traded, so the column exists in that one
        # section rather than sitting empty in the other two.
        trades = kind == "death"
        rws = []
        for q in sel:
            # The place is already named in the row, so repeating "traded 3 of
            # 10" in the sub-line would print the same denominator twice.
            extra = "" if trades else q["extra"]
            sub = f' &middot; {esc(extra)}' if extra else ""
            traded_cell = (f'<td class="num">{rate(q["traded"], q["hit"])}</td>'
                           if trades else "")
            rws.append(
                f'<tr><td class="name"><span class="pill {q["side"]}">'
                f'{q["side"].upper()}</span> {esc(q["zone"])}'
                f'<span class="den" style="font-weight:400;margin-left:7px">'
                f'{esc(q["map"].replace("de_", ""))}{sub}</span></td>'
                f'<td class="num">{rate(q["hit"], q["of"])}</td>'
                f'{traded_cell}'
                f'<td class="num">{rate(q["won"], q["hit"])}</td></tr>')
        more = (f'<p class="note">{hidden} more place'
                f'{"s" if hidden != 1 else ""} showed the same pattern less '
                f'often; the top {POS_TOP_N} are the ones worth practice time.</p>'
                if hidden else "")
        for q in sel:
            shown_zones.setdefault(q["map"], set()).add(q["zone"])

        # The map goes next to the table that names it — in EVERY section that
        # names it, not just the first.
        #
        # Drawing each map once and marking it "done" moved the problem rather
        # than solving it: all five figures piled into "Where your group ends
        # up" and the two sections below it, which talk about the same places,
        # got none. A reader at "Where your first death happens" needs the map
        # there, and a second small copy of Mirage costs less than scrolling
        # back for it.
        here = []
        for mp in dict.fromkeys(q["map"] for q in sel):
            for pic in zone_pictures(mp, show={q["zone"] for q in sel
                                               if q["map"] == mp}, width=300):
                floor = (f' <span class="pill">{esc(pic["level"])}</span>'
                         if pic["level"] else "")
                here.append(
                    f'<figure class="zonefig">{pic["svg"]}'
                    f'<figcaption class="den"><strong>'
                    f'{esc(mp.replace("de_", ""))}</strong>{floor}</figcaption>'
                    f'</figure>')
        maps_here = f'<div class="zonerow">{"".join(here)}</div>' if here else ""
        pos_blocks.append(
            f'<section><div class="sec-head"><span class="label">'
            f'From position data</span><h2>{title}</h2></div>'
            f'<p class="lede">{lede}</p>'
            f'<div class="tbl-wrap"><table><thead><tr><th>Place</th>'
            f'<th class="num">Rounds</th>'
            + (f'<th class="num" title="First deaths here that a teammate '
               f'traded back">Traded</th>' if trades else "")
            + f'<th class="num">Of those, won</th>'
            f'</tr></thead><tbody>{"".join(rws)}</tbody></table></div>'
            f'{more}{maps_here}</section>')

    if pos_blocks:
        positional_block = "".join(pos_blocks)
    elif db.one("SELECT COUNT(*) n FROM zone_names")["n"] == 0:
        positional_block = (
            '<section><div class="sec-head"><span class="label">From position '
            'data</span><h2>Where you play</h2></div><p class="note">Your demos '
            "carry every player&rsquo;s position eight times a second, but a zone "
            "has "
            'to be <a href="/zones.html">given a name</a> before it can appear in '
            'a pattern. Nobody can act on &ldquo;zone 8&rdquo;.</p></section>')
    else:
        positional_block = (
            '<section><div class="sec-head"><span class="label">From position '
            'data</span><h2>Where you play</h2></div><p class="note">Not enough '
            'rounds on any one map yet. These fill in at about two matches per '
            'map.</p></section>')

    # ---- map pool
    known = st["anchors"]["confident"]
    maprows = []
    for name, m in st["maps"].items():
        if known:
            maprows.append(
                f'<tr><td class="name">{map_chip(name)}</td>'
                f'<td class="num mono">{m["matches"]}</td>'
                f'<td class="num">{rate(m["you_won"], m["you_played"])}</td>'
                f'<td class="num">{rate(m["you_ct_won"], m["you_ct"])}</td>'
                f'<td class="num">{rate(m["you_t_won"], m["you_t"])}</td></tr>')
        else:
            maprows.append(
                f'<tr><td class="name">{map_chip(name)}</td>'
                f'<td class="num mono">{m["matches"]}</td>'
                f'<td class="num mono">{m["rounds"]}</td>'
                f'<td class="num">{rate(m["ct_won"], m["rounds"])}</td>'
                f'<td class="num">{rate(m["t_won"], m["rounds"])}</td></tr>')
    map_head = ('<th>Map</th><th class="num">Matches</th><th class="num">Rounds won</th>'
                '<th class="num">As CT</th><th class="num">As T</th>' if known else
                '<th>Map</th><th class="num">Matches</th><th class="num">Rounds</th>'
                '<th class="num">Won as CT</th><th class="num">Won as T</th>')

    # ---- sides
    y = st["you"]
    if known:
        siderows = "".join(
            f'<tr><td class="name"><span class="pill {sd}">{sd.upper()}</span></td>'
            f'<td class="num mono">{y[sd]["rounds"]}</td>'
            f'<td class="num">{rate(y[sd]["won"], y[sd]["rounds"])}</td></tr>'
            for sd in ("ct", "t"))
        side_head = ('<th>Your side</th><th class="num">Rounds</th>'
                     '<th class="num">Rounds won</th>')
    else:
        siderows = "".join(
            f'<tr><td class="name"><span class="pill {sd}">{sd.upper()}</span></td>'
            f'<td class="num mono">{st["sides"][sd]["rounds"]}</td>'
            f'<td class="num">{rate(st["sides"][sd]["won"], st["sides"][sd]["rounds"])}</td></tr>'
            for sd in ("ct", "t"))
        side_head = ('<th>Side</th><th class="num">Rounds</th>'
                     '<th class="num">Rounds won</th>')

    # ---- buys
    buyrows = []
    if known:
        for kind, v in sorted(st["you_buys"].items()):
            buyrows.append(
                f'<tr><td class="name">{esc(kind)}</td>'
                f'<td class="num mono">{v["n"]}</td>'
                f'<td class="num">{rate(v["won"], v["n"])}</td></tr>')
        buy_head = '<th>Your buy</th>'
    else:
        for (side, kind), v in st["buys"].items():
            buyrows.append(
                f'<tr><td class="name"><span class="pill {side}">{side.upper()}</span> '
                f'{esc(kind)}</td><td class="num mono">{v["n"]}</td>'
                f'<td class="num">{rate(v["won"], v["n"])}</td></tr>')
        buy_head = '<th>Side and buy</th>' 

    if known:
        who = ", ".join(v["name"] for v in st["anchors"]["anchors"].values())
        n = st["anchors"]["matches"]
        roster_note = (
            f'<section><p class="note"><strong>These are your rounds, not both '
            f'sides\'.</strong> {esc(who)} appears in every one of your {n} matches '
            f'while opponents appear in one each, so whichever side they were on is '
            f'yours for that round. Everything above is counted from your side of '
            f'the game.</p></section>')
    else:
        roster_note = (
            '<section><p class="warn"><strong>These are both sides, not just '
            'yours.</strong> A demo carries no team names, only which side each '
            'player was on. Telling your side from your opponents\' needs a player '
            'who appears across several of your matches. Upload one more and '
            'this page switches to your rounds alone.</p></section>')

    body = f"""
  <section>
    <div class="stat-row">
      <div class="stat"><span class="stat-n">{st["matches"]}</span>
        <span class="label">matches</span></div>
      <div class="stat"><span class="stat-n">{f"{100 * y['won'] / y['rounds']:.0f}%" if known and y["rounds"] else st["rounds"]}</span>
        <span class="label">{"rounds you won" if known and y["rounds"] else "rounds"}</span></div>
      <div class="stat"><span class="stat-n">{len(st["maps"])}</span>
        <span class="label">maps played</span></div>
      <div class="stat"><span class="stat-n">{len(patterns) + len(pos)}</span>
        <span class="label">patterns found</span></div>
    </div>
  </section>

  {monday_block}

  {form_block}

  <section>
    <div class="sec-head"><span class="label">What repeats across your matches</span>
      <h2>Recurring patterns</h2></div>
    <p class="lede">Counted, never predicted. A line appears once it has
      {report_mod.MIN_PATTERN_CHANCES} chances behind it; under
      {report_mod.MIN_CHANCES} it shows raw counts rather than a percentage.</p>
    <div class="grid-chart">
      <div>{patterns_block}</div>
      <div class="chart">{patterns_chart}</div>
    </div>
  </section>

  {utility_block}

  {positional_block}

  <section>
    <div class="sec-head"><span class="label">Where the rounds went</span>
      <h2>Map pool</h2></div>
    <div class="tbl-wrap"><table>
      <thead><tr>{map_head}</tr></thead>
      <tbody>{"".join(maprows)}</tbody></table></div>
  </section>

  <section>
    <div class="sec-head"><span class="label">Side by side</span><h2>Sides</h2></div>
    <div class="tbl-wrap"><table>
      <thead><tr>{side_head}</tr></thead>
      <tbody>{siderows}</tbody></table></div>
  </section>

  <section>
    <div class="sec-head"><span class="label">By what they could afford</span>
      <h2>Buys</h2></div>
    <div class="tbl-wrap"><table>
      <thead><tr>{buy_head}<th class="num">Rounds</th>
        <th class="num">Rounds won</th></tr></thead>
      <tbody>{"".join(buyrows)}</tbody></table></div>
  </section>

  {roster_note}"""
    return html_page("Team stats", banner("Team stats", crumb=esc(team["name"]),
                                          label="Across every match you have sent in"),
                     body, user)



@app.get("/player/{steamid}", response_class=HTMLResponse)
def player_page(request: Request, steamid: str):
    """One player, match by match."""
    user, redirect = require_user(request)
    if redirect:
        return redirect
    team = db.team_for_user(user["id"])
    if team is None:
        return see_other("/dashboard")

    p = report_mod.player_matches(team["id"], steamid)
    if p is None:
        return HTMLResponse(page("Not found", banner("Not found"),
                                 '<section><p class="lede">No rounds for that player '
                                 'in your matches.</p></section>', user), status_code=404)

    DASH = "&ndash;"
    t = p["totals"]
    rows = []
    for m in p["matches"]:
        res = ('<span class="pill on">Won</span>' if m["result"] == "won"
               else '<span class="pill">Lost</span>')
        # An ADR well off this player's own average is the point of the page,
        # so it is marked rather than left for the reader to spot.
        delta = m["adr"] - t["adr"]
        flag = ""
        if m["rounds"] >= 10 and abs(delta) >= 25:
            flag = (f' <span class="thin">{"+" if delta > 0 else ""}{delta:.0f}</span>')
        clutch = (f'{m["clutch_won"]}/{m["clutch_tried"]}'
                  if m["clutch_tried"] else "&ndash;")
        blind = (f'{m["blind_per_flash"]:.2f}' if m["flashes_thrown"] else "&ndash;")
        rows.append(
            f'<tr><td class="name">'
            f'<a href="/match/{esc(m["match_key"])}">{map_chip(m["map_name"])}</a>'
            f'<div class="den" style="font-weight:400">{esc((m["played_at"] or "")[:10])}</div></td>'
            f'<td>{res}</td>'
            f'<td class="num mono">{esc(m["score"])}</td>'
            f'<td class="num mono">{m["rounds"]}</td>'
            f'<td class="num mono">{m["adr"]:.0f}{flag}</td>'
            f'<td class="num mono">{m["kills"]}{DASH}{m["deaths"]}{DASH}{m["assists"]}</td>'
            f'<td class="num mono">{m["kd"]:.2f}</td>'
            f'<td class="num mono">{m["hs_pct"]:.0f}%</td>'
            f'<td class="num mono">{m["opening_kills"]}/{m["opens"]}</td>'
            f'<td class="num mono">{m["trade_kills"] or "&ndash;"}</td>'
            f'<td class="num mono">{clutch}</td>'
            f'<td class="num mono">{m["multi_kills"] or "&ndash;"}</td>'
            f'<td class="num mono">{m["util_adr"]:.1f}</td>'
            f'<td class="num mono">{blind}</td>'
            f'<td class="num mono">{m["awp_kills"] or "&ndash;"}</td></tr>')

    # ---- utility, as four cards rather than four more columns
    #
    # The match table below already carries fifteen columns. Utility gets a
    # strip instead, because a season number for one player is not a thing you
    # read match by match anyway.
    if t["flashes_thrown"] or t["nades_value"]:
        ucards = []
        ucards.append(
            f'<div class="stat"><span class="stat-n">{t["enemies_flashed"]}</span>'
            f'<span class="label">opponents blinded</span>'
            f'<span class="den">from {t["flashes_thrown"]} flashes</span></div>')
        if t["flashes_landed"]:
            ucards.append(
                f'<div class="stat"><span class="stat-n">'
                f'{t["own_flash_pct"]:.0f}%</span>'
                f'<span class="label">of their blinds hit their own side</span>'
                f'<span class="den">{t["teammates_flashed"]} of '
                f'{t["flashes_landed"]}</span></div>')
        ucards.append(
            f'<div class="stat"><span class="stat-n">{t["flash_assists"]}</span>'
            f'<span class="label">flashes that got someone killed</span>'
            f'<span class="den">blinded, then died for it</span></div>')
        if t["nades_value"]:
            ucards.append(
                f'<div class="stat"><span class="stat-n">'
                f'${t["wasted_per_round"]:.0f}</span>'
                f'<span class="label">of utility wasted per round</span>'
                f'<span class="den">${t["nades_wasted"]:,} of '
                f'${t["nades_value"]:,} bought</span></div>')
        util_block = f"""
  <section>
    <div class="sec-head"><span class="label">What they threw</span>
      <h2>Utility</h2></div>
    <div class="stat-row">{"".join(ucards)}</div>
  </section>"""
    else:
        util_block = ""

    spread = p["best"] - p["worst"]
    body = f"""
  <section>
    <div class="stat-row">
      <div class="stat"><span class="stat-n">{len(p["matches"])}</span>
        <span class="label">matches</span></div>
      <div class="stat"><span class="stat-n">{t["adr"]:.0f}</span>
        <span class="label">ADR overall</span></div>
      <div class="stat"><span class="stat-n">{t["kd"]:.2f}</span>
        <span class="label">K/D</span></div>
      <div class="stat"><span class="stat-n">{p["worst"]:.0f}&ndash;{p["best"]:.0f}</span>
        <span class="label">worst to best ADR</span></div>
    </div>
    <p class="lede">Role: <strong>{esc(t["role"])}</strong>
      <span class="den">({esc(t["role_why"])})</span></p>
  </section>

  {util_block}

  <section>
    <div class="sec-head"><span class="label">Every match, oldest first</span>
      <h2>Match by match</h2></div>
    <p class="lede">Season totals hide whether a number is a level or an average of two
      very different nights. A match more than 25 ADR off this player's own average is
      marked, and the map name links to that match's report.</p>
    <div class="tbl-wrap"><table>
      <thead><tr><th>Match</th><th>Result</th><th class="num">Score</th>
        <th class="num">Rounds</th><th class="num">ADR</th>
        <th class="num">K{DASH}D{DASH}A</th><th class="num">K/D</th>
        <th class="num">HS</th><th class="num">Opening won</th>
        <th class="num" title="Kills that traded a teammate who had just died">Trades</th>
        <th class="num" title="Clutches won of clutches entered">Clutch</th>
        <th class="num" title="Rounds with two or more kills">Multi</th>
        <th class="num" title="Grenade and molotov damage">Nade dmg</th>
        <th class="num" title="Enemies blinded per flash thrown">Blind/flash</th>
        <th class="num">AWP</th></tr></thead>
      <tbody>{"".join(rows)}</tbody></table></div>
  </section>

  <section>
    <p class="note">A spread of <strong>{spread:.0f} ADR</strong> between this player's
      worst and best match. Consistency is its own skill, and it is invisible on a
      season average.</p>
  </section>"""
    return html_page(f'{p["name"]}', banner(p["name"], crumb=esc(team["name"]),
                                            label="Player"), body, user)


# ---------------------------------------------------------------- account

@app.get("/account", response_class=HTMLResponse)
def account(request: Request):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    team = db.team_for_user(user["id"])
    body = f"""
  <section>
    <div class="card">
      <h3>{esc(user["name"] or "–")}</h3>
      <p class="lede">{esc(user["email"])} · {esc(user["role"])}</p>
      <p class="den">{"Team: " + esc(team["name"]) if team else "No team yet"}</p>
    </div>
  </section>
  <section>
    <form method="post" action="/logout">{csrf_input(user)}
      <button class="btn ghost" type="submit">Log out</button></form>
  </section>"""
    return html_page("Account | Counterplay", banner("Account"), body, user)


# ---------------------------------------------------------------- lead form

@app.post("/api/lead")
async def api_lead(request: Request):
    """The landing page's form. No account, no password — just a way in.

    Kept separate from /signup because someone who wants to send demos before
    committing to an account should not be turned away, and a half-created
    account is worse than a row in a leads table.
    """
    data = await request.json()
    if not isinstance(data, dict):
        return {"ok": False, "error": "bad payload"}
    fields = {k: str(data.get(k, ""))[:2000] for k in
              ("team", "league", "role", "name", "email", "faceit_url", "note")}
    if auth.email_problem(fields["email"]):
        return {"ok": False, "error": "A valid email is needed."}
    if not fields["team"].strip() or not fields["name"].strip():
        return {"ok": False, "error": "Team and name are needed."}
    db.execute("""INSERT INTO leads (team, league, role, name, email, faceit_url,
                                     note, created_at)
                  VALUES (?,?,?,?,?,?,?,?)""",
               *(fields[k] for k in ("team", "league", "role", "name", "email",
                                     "faceit_url", "note")), db.utcnow())
    db.audit(None, "lead", fields["email"])
    return {"ok": True}


# ---------------------------------------------------------------- static

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    """The sales page, unless you already bought.

    A signed-in coach reaching the root is almost always trying to get back
    into the product rather than to read about it again, and the Counterplay
    mark in the league pages is the commonest way to arrive here. Sending them
    to their own dashboard makes that mark do what a mark is for.
    """
    if current(request):
        return see_other("/dashboard")
    return HTMLResponse((SITE / "index.html").read_text(encoding="utf-8"))


# ---- the league site, addressed without .html
#
# The pages are a folder of static files, but the address a coach sees should
# not have to say so. This resolves /league/<name> to <name>.html on disk, and
# permanently redirects the old .html address to the clean one so anything
# already linked or bookmarked still lands.
#
# Declared BEFORE the StaticFiles mount further down, because Starlette matches
# routes in the order they were added and the mount would otherwise take every
# path under /league first.
LEAGUE_DIR = SITE / "league"


@app.get("/league/{path:path}", response_class=HTMLResponse)
def league_page(path: str):
    if not LEAGUE_DIR.is_dir():
        return HTMLResponse("<h1>Not found</h1>", status_code=404)

    # Nothing may climb out of the league folder.
    clean = path.strip("/")
    if clean and (".." in clean or clean.startswith("/") or "\\" in clean):
        return HTMLResponse("<h1>Not found</h1>", status_code=404)

    if clean.endswith(".html"):
        target = "/league/" + clean[:-5]
        return RedirectResponse("/league/" if clean == "index.html" else target,
                                status_code=301)

    for candidate in ((LEAGUE_DIR / "index.html") if not clean else None,
                      LEAGUE_DIR / f"{clean}.html" if clean else None,
                      LEAGUE_DIR / clean / "index.html" if clean else None):
        if candidate is not None and candidate.is_file():
            return HTMLResponse(candidate.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Not found</h1>", status_code=404)


@app.post("/api/zones")
async def api_zones(request: Request):
    """Save the names a human put on the clustered zones. Admin only.

    Zone names are shared by every team on the platform: one list of 142
    names, used by every pattern on every report. This used to accept a write
    from anyone signed in, which meant the first coach with an account could
    rename Mirage for everybody by trying the naming page out.

    Shared knowledge, yes. Shared write access, no. `grantadmin.py` is how the
    flag is given, and it is deliberately not something a web page can do.
    """
    user = current(request)
    if user is None:
        return {"ok": False, "error": "sign in first"}
    if not user["is_admin"]:
        db.audit(user["id"], "zone_write_denied")
        return {"ok": False,
                "error": "zone names are shared across every team, so only an "
                         "admin can change them"}
    data = await request.json()
    names = data.get("names") if isinstance(data, dict) else None
    if not isinstance(names, dict):
        return {"ok": False, "error": "bad payload"}
    saved = 0
    for key, value in list(names.items())[:400]:
        try:
            map_name, idx = key.rsplit(":", 1)
            idx = int(idx)
        except (ValueError, AttributeError):
            continue
        label = str(value).strip()[:60]
        if label:
            db.execute("""INSERT INTO zone_names (map_name, zone_index, name, updated_at)
                          VALUES (?,?,?,?)
                          ON CONFLICT(map_name, zone_index)
                          DO UPDATE SET name=excluded.name, updated_at=excluded.updated_at""",
                       map_name, idx, label, db.utcnow())
        else:
            db.execute("DELETE FROM zone_names WHERE map_name=? AND zone_index=?",
                       map_name, idx)
        saved += 1
    db.audit(user["id"], "zone_names", f"{saved} zones")
    return {"ok": True, "saved": saved}


@app.get("/api/zones")
def api_zones_get():
    """Every name recorded so far, keyed as map:index."""
    return {r["map_name"] + ":" + str(r["zone_index"]): r["name"]
            for r in db.query("SELECT map_name, zone_index, name FROM zone_names")}


@app.get("/finish-zones.html", response_class=HTMLResponse)
def finish_zones_page():
    """Only the zones still without a name, drawn on the real map."""
    return HTMLResponse((SITE / "finish-zones.html").read_text(encoding="utf-8"))


@app.get("/nuke-zones.html", response_class=HTMLResponse)
def nuke_zones_page():
    """Nuke's naming sheet, split by floor — its bombsites are stacked."""
    return HTMLResponse((SITE / "nuke-zones.html").read_text(encoding="utf-8"))


@app.get("/zones.html", response_class=HTMLResponse)
def zones_page():
    """The map-naming sheet, generated from parsed positions.

    A working tool rather than a product page: it exists so a human can put
    names to the areas clustering found. Regenerate it whenever the corpus
    grows enough to change the map.
    """
    return HTMLResponse((SITE / "zones.html").read_text(encoding="utf-8"))


@app.get("/sample-report.html", include_in_schema=False)
def sample_report_dot_html():
    """The old address. Kept, and permanently pointed at the clean one.

    This link is on the landing page, in the league nav and in the outreach
    email, so it exists in places nobody can edit after the fact.
    """
    return RedirectResponse("/sample-report", status_code=301)


@app.get("/sample-report", response_class=HTMLResponse)
def sample_report(request: Request):
    """The example report, rendered in the product's own components.

    Built rather than served from a file, so it cannot drift from the look of
    the pages it is previewing — which is exactly what the old static copy had
    done, down to a different typeface and a different palette.
    """
    # zone_pictures is handed in rather than imported: it lives here, and
    # app.sample importing main would close the loop.
    return HTMLResponse(sample_page.render(current(request),
                                           pictures=zone_pictures))


# Map overview images, fetched by counterplay/radar.py. Absent until someone
# runs --fetch, and every drawing works without them.
if (SITE / "radars").is_dir():
    app.mount("/radars", StaticFiles(directory=SITE / "radars"), name="radars")


# The generated league site is served by league_page above, which gives it
# addresses without .html and redirects the old ones. It is deliberately not
# mounted as static files as well: two ways to reach the same page is one way
# too many, and the mount would have kept the .html addresses alive.
