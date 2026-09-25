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
import json
import os
import threading
import re
import secrets
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import (HTMLResponse, JSONResponse, RedirectResponse,
                               Response)
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.staticfiles import StaticFiles

from . import (advice, alert, auth, buys, charts, db, ingest, legal, mail,
               movement, traffic,
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
LEAGUES = ["NECC", "NACE Starleague", "ECAC", "Playfly", "ESEA",
           "FACEIT League", "Other"]
ROLES = [("coach", "Coach"), ("igl", "In-game leader"), ("player", "Player"),
         ("director", "Program director"), ("other", "Other")]

# Features that actually work today. Everything else in plans.py renders as
# "Coming" rather than being quietly listed as though it ships.
BUILT_FEATURES = {"match_reports", "player_stats", "team_stats",
                  "pattern_finder"}

# Where a working feature actually lives, so "Available" is clickable rather
# than a claim a coach has to go hunting to verify.
# A feature with no link renders as plain text, which is the right thing for
# one a reader cannot go and look at.
FEATURE_LINKS = {"match_reports": "/matches", "player_stats": "/players",
                 "team_stats": "/stats", "pattern_finder": "/stats"}

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


def match_href(match_key: str, share: str = "") -> str:
    """Where a link to a match points, which depends on how you got here.

    A reader holding a share link has no session, so /match/ would bounce them
    to a login screen. Every link out of a shared page has to stay inside the
    link's own space.
    """
    if share:
        return f"/r/{esc(share)}/m/{esc(match_key)}"
    return f"/match/{esc(match_key)}"


def share_nav(share: str, here: str) -> str:
    """The tabs across the top of a shared page.

    A link-holder has no account and therefore no nav, so without this the
    only route from the season to the roster was an arrow buried in a
    paragraph. Nobody found it.
    """
    if not share:
        return ""
    tabs = (("", "Season"), ("/players", "Players"))
    out = []
    for path, label in tabs:
        on = ' class="on"' if path == here else ""
        out.append(f'<a href="/r/{esc(share)}{path}"{on}>{label}</a>')
    return f'<nav class="sharenav">{"".join(out)}</nav>'


def player_href(steamid: str, share: str = "") -> str:
    """Where a link to one player points. Same reasoning as match_href."""
    if share:
        return f"/r/{esc(share)}/p/{esc(steamid)}"
    return f"/player/{esc(steamid)}"


def csrf_input(user) -> str:
    return f'<input type="hidden" name="csrf" value="{esc(user["csrf"])}">'


# ---------------------------------------------------------------- signup

SIGNUP_INTRO = (
    "Free this season. One person reads every sign-up, so a human will reply.")


def signup_form(values: dict | None = None, error: str = "") -> str:
    v = values or {}
    warn = f'<p class="warn">{esc(error)}</p>' if error else ""
    return f"""
  <section>
    <div class="card">
      {warn}
      <form class="stack" method="post" action="/signup">
        <div class="hp-field" aria-hidden="true">
          <label for="homepage">Homepage</label>
          <input type="text" id="homepage" name="homepage" value=""
                 autocomplete="off" tabindex="-1">
        </div>
        {form_field("team", "Team or program", value=v.get("team", ""))}
        {form_field("email", "Email", "email", v.get("email", ""), autocomplete="email")}
        {form_field("password", "Password", "password", required=True,
                    autocomplete="new-password", minlength="10")}
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
                faceit_url: str = Form(""), homepage: str = Form("")):
    values = {"team": team, "league": league, "role": role, "name": name,
              "email": email, "faceit_url": faceit_url}

    def fail(msg):
        return HTMLResponse(page("Add your team | Counterplay",
                                 banner("Add your team", label="Free this season"),
                                 signup_form(values, msg)), status_code=400)

    # The honeypot, checked before anything else so a bot costs us no work.
    # `homepage` is invisible to a person and irresistible to a form filler.
    if homepage.strip():
        db.audit(None, "signup_honeypot", f"team={team.strip()[:40]!r}")
        return fail("That submission looked automated. If you are a person, "
                    "clear the form and try again.")

    problem = auth.email_problem(email) or auth.password_problem(password)
    if problem:
        return fail(problem)
    if not team.strip():
        return fail("A team or program name is needed.")
    # The form no longer asks for a name, so the team stands in for one. It is
    # printed in the corner of the nav and nowhere else, and a team name there
    # is more use to the person reading it than their own email address.
    name = name.strip() or team.strip()
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
    alert.signup(team.strip(), email.strip(), league, role)

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
      <p class="lede">Enter your account email and we&rsquo;ll send a link to
        set a new password. It works once, for {resets.TOKEN_HOURS}
        hour{"s" if resets.TOKEN_HOURS != 1 else ""}.</p>
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


def advice_card(it, baseline: float) -> str:
    """One recommendation, with the count it was drawn from underneath.

    Lifted out of the Team stats page when the dashboard started drawing the
    top of the same list. Two renderings of one recommendation is two things
    to keep in step, and the one on the smaller page is the one that would
    have drifted.
    """
    tag = "keep doing this" if it["good"] else "worth changing"
    cls = "on" if it["good"] else "t"
    side = (it["side"] or "").upper()
    # A finding counted in flashes or in dollars brings its own closing line.
    # The rest are a share of rounds against the team's round win rate -- and
    # when there is only one count to compare, that belongs ON the count
    # rather than under it. A card that says "you win 2 of those 9" and then
    # "22% against your 49% overall, a gap of 27 points across 9 rounds" has
    # said one thing three ways.
    lines = list(it["evidence"])
    foot = it.get("foot")
    fig = ""
    if it.get("vs"):
        # Drawn as two bars instead of written as "80% in those 10 rounds
        # against 59% in your other 27". The counts stay in the evidence line
        # above it and in each bar's title.
        fig = charts.versus([
            (lab, report_mod.pct(won, of), f"{won} of {of}")
            for lab, won, of in it["vs"]])
    elif not foot and len(lines) == 1:
        lines[0] = (f'{lines[0]} ({it["rate"]:.0f}%), against '
                    f'{baseline:.0f}% overall')
    elif not foot:
        foot = (f'{it["rate"]:.0f}% against your {baseline:.0f}% overall, '
                f'across {it["of"]} rounds')
    ev = "".join(f'<li>{esc(e)}</li>' for e in lines)
    return (
        f'<div class="card advice{" good" if it["good"] else ""}">'
        f'<div style="display:flex;gap:9px;align-items:center;'
        f'flex-wrap:wrap"><span class="pill {cls}">{tag}</span>'
        + (f'<span class="pill {it["side"]}">{side}</span>' if side else "")
        + f'</div><h3>{esc(it["do"])}</h3>'
        f'<p class="lede">{esc(it["because"])}</p>'
        f'<ul class="den" style="margin:0;padding-left:17px">{ev}</ul>'
        + fig
        + (f'<p class="den">{esc(foot)}</p>' if foot else "")
        + '</div>')


def opening_tile(you) -> str:
    """The share of opening duels your side won, as a stat tile.

    Empty without a known side or without a single opening duel."""
    if not you:
        return ""
    took, lost = you["opening_took"], you["opening_lost"]
    if not took + lost:
        return ""
    return (f'<div class="stat" title="{took} of {took + lost}">'
            f'<span class="stat-n">{report_mod.pct(took, took + lost):.0f}%</span>'
            f'<span class="label">opening duels won</span></div>')


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
                  'reports fill in. Upload them soon: FACEIT and Valve both '
                  'delete match demos after a few weeks.</p>')

    # ---- what to work on, on the first screen
    #
    # This was two clicks away on Team stats, behind a dashboard that opened
    # with a grid of six feature cards, two of them "coming". A coach who logs
    # in on a Monday wants the things to run at practice, not a description of
    # the product they are already inside. The full ranked plan stays on Team
    # stats, grouped by map, because that is where practice gets planned; what
    # goes here is the top of it and a way through to the rest.
    #
    # Three cards, not eight. A summary you have to scroll has stopped being
    # one, and the ranking already puts the findings covering the most rounds
    # first.
    plan = advice.monday(team["id"]) if team else {"items": [], "baseline": 0.0}
    top = plan["items"][:3]
    if top:
        rest = len(plan["items"]) - len(top)
        through = (f'All {len(plan["items"])} of them, grouped by map'
                   if rest else "The same list, grouped by map")
        advice_block = f"""
  <section class="lead">
    <div class="sec-head"><span class="label">Read this one first</span>
      <h2>What to work on</h2></div>
    <div class="grid2">
      {"".join(advice_card(i, plan["baseline"]) for i in top)}</div>
    <p class="note" style="margin-top:12px">
      <a href="/stats">{through} &rarr;</a></p>
  </section>"""
    else:
        advice_block = ""

    # Record and recent form, so the first screen after logging in is about the
    # team rather than about the plan. Two cards used to read the same number
    # (uploaded, parsed) and the season went unmentioned.
    all_matches = report_mod.team_matches(team["id"]) if team else []
    done = [q for q in all_matches if q["result"]]
    wins = sum(1 for q in done if q["result"] == "W")
    record = f"{wins}&ndash;{len(done) - wins}" if done else "&ndash;"
    # Opening duels won is the fourth tile. It was rounds won, and before
    # that "Free, this season". The first real coach said rounds won is the
    # number coaches do not care about; who dies first is something to
    # practise.
    _st = report_mod.team_stats(team["id"]) if team else None
    _you = (_st["you"] if _st and _st["anchors"]["confident"] else None)
    won_tile = opening_tile(_you)
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
      {won_tile}
    </div>
    {status}
  </section>
  {advice_block}
  {form_block}

  <section>
    <div class="sec-head"><span class="label">Demos</span><h2>Upload</h2></div>
    <div class="card">
      <form class="stack" method="post" action="/upload"
            enctype="multipart/form-data">
        {csrf_input(user)}
        <label>Match demos
          <input type="file" name="demo" accept=".dem,.zst,.gz,.bz2" multiple required></label>
        <button type="submit">Upload</button>
        <p class="den">Pick as many as you like, a whole season at once.
          Upload files exactly as they download, up to 400&nbsp;MB each. The
          same match twice is stored once.</p>
        <p class="den"><strong>Demos expire.</strong> FACEIT and Valve both
          delete match demos after a few weeks, so save the ones worth keeping
          now.</p>
      </form>
      {DEMO_HELP}
    </div>
  </section>

  <section>
    <div class="sec-head"><span class="label">What your plan reaches</span>
      <h2>Features</h2></div>
    <p class="lede">What the product does today, and what is still being built.
      Everything is free this season.</p>
    <div class="grid2">{cards}</div>
  </section>"""

    return html_page("Dashboard | Counterplay",
                     banner("Dashboard", crumb=team_line), body, user)


# Where a demo comes from.
#
# The upload box described what a demo file looks like and never said how to
# get one, which is the first thing anybody asks and the one answer that was
# only in a founder's head. Folded closed, because a coach who already has a
# folder of demos does not need it and should not have to scroll past it.
#
# Both routes are written from files this system has actually parsed rather
# than from a help page: a Premier match arrives as
# `003837857386282877221_1976594227.dem` and a FACEIT one as
# `1-4cfc1e19-....dem.gz`. Neither needs unpacking or renaming, which is
# worth saying, because the instinct with a compressed file is to unzip it.
DEMO_HELP = """
      <details class="howto">
        <summary>Where do I find my demo files?</summary>
        <div class="tbl-plain">
          <p class="den"><strong>FACEIT, from the match room.</strong> Open the
            match page on faceit.com and use the download button in the middle
            of it. You get a file named like
            <code>1-4cfc1e19-....dem.gz</code>. <strong>Do not unzip it.</strong>
            Upload it exactly as it downloads.</p>
          <p class="den"><strong>Premier and Competitive, from the game.</strong>
            Open CS2 and go to <strong>Watch &rarr; Your Matches</strong>. Every
            match from roughly the last month is listed. Click one, then
            <strong>Download GOTV Demo</strong>. When it finishes, the file is in
            your CS2 folder under
            <code>game/csgo/replays</code> and is named like
            <code>003837857386282877221_1976594227.dem</code>. Upload it as it
            is.</p>
        </div>
      </details>"""


# A table of contents for a page that is eleven sections long.
#
# Built from the rendered headings rather than from a list maintained here,
# because the two would drift the first time somebody added a section. Empty
# and invisible without JavaScript, which is correct: with no script there is
# no smooth way to jump anyway, and an inert row of dead links is worse than
# no row.
#
# The highlight follows whichever heading is nearest the top of the viewport,
# recomputed on scroll rather than by IntersectionObserver, because sections
# here differ in height by a factor of twenty and an observer threshold that
# suits Coverage does not suit Players.
PAGE_NAV = """
  <nav class="pagenav" id="pagenav" hidden></nav>
  <script>
  (function () {
    var nav = document.getElementById('pagenav');
    if (!nav) return;
    var heads = [].slice.call(document.querySelectorAll('section .sec-head h2'));
    if (heads.length < 4) return;
    var links = [];
    heads.forEach(function (h, i) {
      var sec = h.closest('section');
      if (!sec.id) sec.id = 'sec' + i;
      var a = document.createElement('a');
      a.href = '#' + sec.id;
      a.textContent = h.textContent.trim();
      nav.appendChild(a);
      links.push({a: a, sec: sec});
    });
    function mark() {
      var best = 0, top = nav.getBoundingClientRect().bottom + 8;
      links.forEach(function (l, i) {
        if (l.sec.getBoundingClientRect().top <= top) best = i;
      });
      links.forEach(function (l, i) { l.a.className = i === best ? 'on' : ''; });
    }
    addEventListener('scroll', mark, {passive: true});
    nav.hidden = false;
    mark();
  })();
  </script>"""


# ---------------------------------------------------------------- upload

# Every name a demo arrives under. FACEIT serves .dem.gz today and .dem.zst
# historically, Valve serves .dem.bz2, and the game's own download is a plain
# .dem. The upload used to accept only .dem and .dem.zst, so a coach uploading
# straight from FACEIT was told their match was not a demo. The name is only a
# first filter; what the bytes are is decided by ingest.packing_of().
DEMO_SUFFIXES = (".dem", ".dem.zst", ".dem.gz", ".dem.bz2")
STORED_SUFFIX = {"zstd": ".dem.zst", "gzip": ".dem.gz", "bzip2": ".dem.bz2"}


def is_demo_name(name: str) -> bool:
    return (name or "").lower().endswith(DEMO_SUFFIXES)


async def _save_one(demo: UploadFile, team, user) -> tuple[str, str]:
    """Store one uploaded demo. Returns (outcome, detail) for the summary."""
    name = demo.filename or "unnamed"
    if not is_demo_name(name):
        return "skipped", f"{name}: not a demo file"

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
        # Keep the extension honest: ingest decides what to do by reading the
        # magic number, not the name, but the stored name should still say
        # what the bytes are.
        suffix = STORED_SUFFIX.get(ingest.packing_of(tmp), ".dem")
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
    if membership is None and user["is_admin"]:
        # The master account reads any team. Logged every time, because an
        # operator opening somebody's season should leave a trace even when
        # the operator is the only person who will ever read the log.
        db.audit(user["id"], "admin_view_team", f"team={team['id']}")
        membership = {"member_role": "admin"}
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




@app.get("/match/{match_key}", response_class=HTMLResponse)
def match_report(request: Request, match_key: str):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    return _match_body(match_key, user)


def _match_body(match_key: str, user=None, share: str = "", share_team=None):
    """One match, for a signed-in coach or for a link-holder.

    `share_team` is the team the LINK names, handed in rather than looked up,
    so a shared link opens the team it was made for even when a different
    coach happens to be signed in on that browser.
    """
    # A report belongs to whoever owns the demo behind it. One team's match is
    # never shown to another team - the same rule as /team, enforced the same way.
    owner = db.one("""SELECT d.team_id FROM matches m JOIN demos d ON d.id = m.demo_id
                       WHERE m.match_key = ?""", match_key)
    if owner is None:
        return HTMLResponse(page("Not found", banner("Not found"),
                                 '<section><p class="lede">No such match.</p></section>',
                                 user), status_code=404)
    if share:
        # The only check a shared link needs, and the only one it gets: this
        # match must belong to the team the link names. Anything else is
        # somebody else's match and this link does not reach it.
        if share_team is None or owner["team_id"] != share_team["id"]:
            return HTMLResponse(page("Not found", banner("Not found"),
                                     '<section><p class="lede">No such match.'
                                     '</p></section>', None, noindex=True),
                                status_code=404)
    elif owner["team_id"] is not None:
        member = db.one("SELECT 1 FROM team_members WHERE team_id = ? AND user_id = ?",
                        owner["team_id"], user["id"])
        if member is None:
            return HTMLResponse(page("Not yours", banner("Not yours"),
                                     '<section><p class="lede">That match belongs to '
                                     'another team.</p></section>', user),
                                status_code=403)

    # A MATCH COUNTS, IT DOES NOT RATE.
    #
    # `rate` warns below MIN_CHANCES because eight chances cannot support a
    # tendency. Every split of one match is small by construction - two pistol
    # rounds, six forces, five rounds through apartments - so twelve of the
    # nineteen figures on this page came back wearing a warning label about a
    # claim the page was not making. `count` prints the fraction and no
    # percentage, because the denominator here is the whole match.
    #
    # The season rate sits beside it where there is one, which is the number
    # that gives a match figure meaning: 3 of 6 forces is not high or low until
    # you know what your forces usually do.
    count = report_mod.count
    # Whose report the reader is looking at, established once and early:
    # three separate blocks below need it and one of them used to run
    # before it existed.
    team = share_team if share else (db.team_for_user(user["id"]) if user else None)

    r = report_mod.build(match_key, team["id"] if team else None)
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

    # ONE ROW, YOURS -- not one row per side.
    #
    # Sides swap at the half, so a CT row spanning a whole match held this
    # team's first half and their opponent's second: "3 of 16" was eight of
    # your rounds and eight of theirs added together. Where the side is known
    # per round the table is about the reader's team and says so.
    od = []
    you_open = r.get("you_opening")
    if you_open:
        rounds_lost = ", ".join(str(n) for n in you_open["lost_rounds"]) or "-"
        od.append(
            f'<tr><td class="name">{esc(team["name"]) if team else "You"}</td>'
            f'<td class="num">{count(you_open["saved"], you_open["lost"])}</td>'
            f'<td class="num">{count(you_open["converted"], you_open["taken"])}</td>'
            f'<td class="den">{esc(rounds_lost)}</td></tr>')
        open_head = "Rounds you lost it"
        open_lede = ""
        open_line = (
            f'<p class="note">After losing the first duel you won '
            f'{you_open["saved"]} of {you_open["lost"]}. After winning it, '
            f'{you_open["converted"]} of {you_open["taken"]}.</p>')
    else:
        for side in ("ct", "t"):
            o = r["opening"][side]
            rounds_lost = ", ".join(str(n) for n in o["lost_rounds"]) or "-"
            od.append(
                f'<tr><td class="name">{side.upper()}</td>'
                f'<td class="num">{count(o["saved"], o["lost"])}</td>'
                f'<td class="num">{count(o["converted"], o["taken"])}</td>'
                f'<td class="den">{esc(rounds_lost)}</td></tr>')
        open_head = "Rounds they lost it"
        open_line = ""
        open_lede = ("By side, because there is no way yet to tell which of "
                     "these two teams is yours. Sides swap at the half, so "
                     "neither row is one team. Upload a second match and this "
                     "becomes your rounds alone.")

    # The season's own record for the same buy, so the match figure has
    # something to be high or low against. Absent until a team has a season.
    season_buys = None
    if team:
        st_all = report_mod.team_stats(team["id"])
        if st_all and st_all["anchors"]["confident"]:
            season_buys = st_all["you_buys"]

    # Same correction as the table above, and it mattered more here: the
    # season column beside it has always been this team's, so a per-side match
    # column put two different teams in one row.
    br = []
    you_buys = r.get("you_buys")
    buy_head = "Your buy"
    if you_buys:
        source = [(None, kind, v) for kind, v in sorted(you_buys.items())]
    else:
        buy_head = "Side and buy"
        source = [(side, kind, v) for side in ("ct", "t")
                  for kind, v in sorted(r["buys"][side].items())]
    for side, kind, v in source:
        which = ", ".join(str(n) for n in v["rounds"])
        season = ""
        if season_buys is not None:
            sv = season_buys.get(kind)
            season = (f'<td class="num">{rate(sv["won"], sv["n"])}</td>'
                      if sv else f'<td class="num">{rate(0, 0)}</td>')
        label = (f'{side.upper()} {esc(kind)}' if side else esc(kind))
        br.append(f'<tr><td class="name">{label}</td>'
                  f'<td class="num">{count(v["won"], v["n"])}</td>'
                  f'{season}'
                  f'<td class="den">{esc(which)}</td></tr>')

    # ---- buy calls
    #
    # The two halves of what the first real coach asked for: was the team's
    # call right (judged, see app/buys.py and counterplay/economy.py), and
    # where did each player's buy go against it (read, no model). Only with
    # your side known, because both are about YOUR buys, and only on a demo
    # parsed with money in it (migration 23).
    calls_block = ""
    sides_here = (report_mod.our_sides(team["id"]) if team else {})
    sides_here = {rn: sd for (mk, rn), sd in sides_here.items()
                  if mk == match_key}
    if sides_here:
        mine = [c for c in buys.match_calls(match_key)
                if sides_here.get(c["round"]) == c["side"]]
        CALL = {"eco": "saved", "force": "forced", "full": "full bought"}
        OTHER = {"eco": "Saving", "force": "Forcing", "full": "A full buy"}
        cards = []
        for c in sorted((c for c in mine if c["flag"]),
                        key=lambda c: -c["gain"]):
            alt = c["options"][c["best"]]
            left = c["money"] - c["spent"]
            if c["made"] == "force" and alt["kind"] == "full":
                what = (f'You bought ${c["equip"]:,.0f} of equipment and kept '
                        f'${left:,.0f}. A full buy was in reach.')
            else:
                what = (f'You {CALL[c["made"]]} with ${c["money"]:,.0f} between '
                        f'you, holding ${c["equip"]:,.0f} of equipment.')
            fig = charts.versus([
                (f'What you did ({CALL[c["made"]]})', c["v"] / 2 * 100,
                 "Rounds you could expect to win out of this one and the next",
                 f'{c["v"]:.2f} of 2'),
                (OTHER[alt["kind"]], alt["v"] / 2 * 100,
                 "Rounds you could expect to win out of this one and the next",
                 f'{alt["v"]:.2f} of 2')], muted_second=False)
            cards.append(
                f'<div class="card"><p><strong>Round {c["round"]}</strong> '
                f'<span class="pill {c["side"]}">{c["side"].upper()}</span> '
                f'<span class="den">{"won" if c["won"] else "lost"}</span></p>'
                f'<p>{what} {OTHER[alt["kind"]]} '
                f'was worth about {c["gain"]:.2f} more rounds over this round '
                f'and the next.</p>{fig}</div>')
        per_player: dict = {}
        for c in mine:
            for n in c["notes"]:
                per_player.setdefault((n["steamid"], n["name"]), []).append(
                    f'round {c["round"]}, {n["text"]}')
        notes_list = "".join(
            f'<li><a href="{player_href(sid, share)}">{esc(name)}</a>: '
            f'{esc("; ".join(lines))}.</li>'
            for (sid, name), lines in sorted(per_player.items(),
                                             key=lambda kv: -len(kv[1])))
        if mine:
            calls_block = '<div class="buycalls">' + (
                (f'<h3>Calls worth a second look</h3>'
                 f'<p class="lede">Judged on what each side held and could '
                 f'afford, over this round and the next. Only calls where the '
                 f'other choice was worth a tenth of a round or more. The '
                 f'round after a pistol round is left out: college matches '
                 f'do not settle whether to force it.</p>'
                 f'<div class="grid2">{"".join(cards)}</div>'
                 if cards else
                 '<p class="note">No buy call this match where the other '
                 'choice was worth a tenth of a round more. The round after '
                 'a pistol round is not judged.</p>') +
                (f'<h3>Player buys against the team&rsquo;s call</h3>'
                 f'<ul class="buynotes">{notes_list}</ul>' if notes_list else '')
            ) + '</div>'

    # ---- scoreboard
    ROLE_CLASS = {"AWP": "role awp", "Entry": "role entry"}
    sb_blocks = []
    for sb_side in r["scoreboard"]:
        prows = []
        for a in sb_side["players"]:
            cls = ROLE_CLASS.get(a["role"], "role")
            util = a.get("util_damage", 0) or 0
            tk = a.get("trade_kills", 0) or 0
            ct_t, ct_w = a.get("clutch_tried", 0) or 0, a.get("clutch_won", 0) or 0
            prows.append(
                f'<tr><td class="name">'
                f'<a href="{player_href(a["steamid"], share)}">{esc(a["name"])}</a></td>'
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
        pill = "pill ct" if sb_side["side"] == "ct" else (
            "pill t" if sb_side["side"] == "t" else "pill")
        sb_blocks.append(
            f'<div style="display:flex;align-items:center;gap:10px;margin-top:6px">'
            f'<span class="{pill}">{esc(sb_side["label"])}</span>'
            f'<span class="den">{len(sb_side["players"])} players</span></div>'
            f'<div class="tbl-wrap"><table class="dense">'
            f'<thead><tr><th>Player</th><th>Role</th>'
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
    <p class="lede">{"Your team first." if r["scoreboard"] and
      r["scoreboard"][0]["label"] == "Your team" else
      "Teams are the side each player started on."} Roles come from what
      each player did.</p>
    {"".join(sb_blocks)}
  </section>""" if sb_blocks else "")

    # How early the first duel lands, which is the number the timeline column
    # beside it is full of and nobody wants to average by eye.

    # ---- the match as a picture, not as twenty-nine rows
    #
    # A round timeline is a time series and it was a table. Bars are rounds —
    # up for won, height for what was brought — and the line is the running
    # score difference, so a comeback looks like one.
    _sides = (report_mod._side_by_round(
        team["id"], report_mod.team_anchors(team["id"]).get("anchors", {}))
        if team else {})
    _us_ct = (lambda rn: _sides.get((match_key, rn)) == "ct") if _sides else None
    match_notes = advice.for_match(match_key, team["id"]) if team else []
    # Only the first card's rounds are shaded. Every card's together covered
    # most of a match and shaded nearly every column, which marks nothing.
    named_rounds = set(match_notes[0]["rounds"]) if match_notes else set()
    timeline_chart = charts.both(
        charts.round_timeline(r["rows"], _us_ct, marks=named_rounds),
        charts.round_timeline(r["rows"], _us_ct, width=320, compact=True,
                              marks=named_rounds))

    # Your record by side, for the tiles. "7-17, rounds won CT to T" counted
    # both teams' rounds by side and read like a score that was not one.
    by_side = {"ct": [0, 0], "t": [0, 0]}
    if _us_ct:
        for x in rows:
            sd = "ct" if _us_ct(x["round_num"]) else "t"
            by_side[sd][0 if bool(x["ct_won"]) == (sd == "ct") else 1] += 1

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
                + (f'<td class="num">{count(z["traded"] or 0, z["n"])}</td>'
                   if trades else "")
                + f'<td class="num">{count(z["won"], z["n"])}</td></tr>'
                for z in items)
            head = (f'<th class="num" title="First deaths here that a teammate '
                    f'traded back">Traded</th>' if trades else "")
            return (f'<div><div class="sec-head"><span class="label">{label}</span>'
                    f'<h3>{heading}</h3></div>'
                    f'<div class="tbl-wrap"><table class="dense">'
                    f'<thead><tr><th>Place</th>'
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
      <h2>Where you went this match</h2></div>
    <p class="lede">Your season's position readings, for this match
      only.</p>
    <div class="grid2">{"".join(blocks)}</div>
    <div class="zonerow">{figs}</div>
    <details><summary>Round by round</summary>
      <div class="tbl-wrap"><table><thead><tr><th class="num">#</th><th>Side</th>
        <th>Result</th><th>Group reached</th><th class="num">At</th>
        <th>First death</th></tr></thead><tbody>{"".join(rr)}</tbody></table></div>
    </details>
  </section>"""

    # ---- what this one match says
    #
    # Every card names its rounds. A section called "worth pulling up at
    # practice" whose findings do not say WHICH rounds to pull up is asking a
    # coach to go and find them, which is the work the page exists to do.
    notes_block = ""
    if match_notes:
        cards = []
        for n in match_notes:
            tag = "keep doing this" if n["good"] else "watch these back"
            rounds = ", ".join(str(x) for x in n["rounds"])
            cards.append(
                f'<div class="card advice{" good" if n["good"] else ""}">'
                f'<span class="pill {"on" if n["good"] else "t"}">{tag}</span>'
                f'<h3>{esc(n["do"])}</h3>'
                f'<p class="lede">{esc(n["because"])}</p>'
                f'<p class="den">{esc(n["evidence"])}</p>'
                f'<p class="rounds"><span class="label">Rounds</span> '
                f'<span class="mono">{esc(rounds)}</span></p></div>')
        notes_block = (
            '<section class="lead"><div class="sec-head"><span class="label">'
            'Worth pulling up at practice</span><h2>From this match</h2></div>'
            '<p class="lede">Rounds worth watching back, and why. The first '
            'card&rsquo;s rounds are shaded on the timeline above.</p>'
            f'<div class="grid2">{"".join(cards)}</div></section>')

    # THE SCORE.
    #
    # This used to read score_ct-score_t, which is rounds won by SIDE summed
    # over the whole match. Sides swap at the half, so neither number belongs
    # to a team: one 28-round Inferno showed "16-12" for a match actually won
    # 16-13, and a Mirage showed "22-6" for a 16-13. It is the first number a
    # coach reads and it was not the score.
    sc = report_mod.match_score(match_key, team["id"] if team else None)
    played = (m["ingested_at"] or "")[:10]
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
                nav_prev = (f'<a href="{match_href(o["match_key"], share)}">'
                            f'&larr; {esc(o["map"])} '
                            f'{o["us"]}{DASH}{o["them"]}</a>')
            if i > 0:                                # newer
                o = seq[i - 1]
                nav_next = (f'<a href="{match_href(o["match_key"], share)}">'
                            f'{esc(o["map"])} {o["us"]}{DASH}{o["them"]} &rarr;</a>')
    back = (f'<a class="den" href="/r/{esc(share)}">Back to the season</a>'
            if share else '<a class="den" href="/matches">All matches</a>')

    if _us_ct:
        tiles_by_side = "".join(
            f'<div class="stat"><span class="stat-n">{w}&ndash;{l}</span>'
            f'<span class="label">as {sd.upper()}</span></div>'
            for sd, (w, l) in (("t", by_side["t"]), ("ct", by_side["ct"]))
            if w + l)
    else:
        tiles_by_side = (
            f'<div class="stat"><span class="stat-n">{r["score_ct"]}&ndash;'
            f'{r["score_t"]}</span><span class="label">rounds won by the CT '
            f'side, then the T side</span></div>')
    # With your side known, the opening duels are the strip on the timeline
    # and the line under it. Without it, the by-side table stays.
    open_block = "" if open_line else f"""
  <section>
    <div class="sec-head"><span class="label">The first duel of the round</span>
      <h2>Opening duels</h2></div>
    <p class="lede">{esc(open_lede)}</p>
    <div class="tbl-wrap"><table>
      <thead><tr><th>Side</th>
        <th class="num">Won after losing it</th>
        <th class="num">Won after winning it</th><th>{open_head}</th></tr></thead>
      <tbody>{"".join(od)}</tbody></table></div>
  </section>"""
    match_nav = (f'<nav class="pager"><span>{nav_prev}</span>'
                 f'{back}<span>{nav_next}</span></nav>')

    body = f"""
  {match_nav}

  <section>
    <div class="sec-head"><span class="label">Every round</span><h2>Timeline</h2></div>
    <p class="lede">One bar per round: above the line you won it, below you
      lost it. Height is what you spent, and the tick is what they spent.
      The line on top is the score gap.</p>
    <div class="chart">{timeline_chart}</div>
    {open_line}
    <details><summary>Every round as a table</summary>
      <div class="tbl-wrap"><table>
        <thead><tr><th class="num">#</th><th>Won</th><th>Buy</th>
          <th class="num">CT $</th><th class="num">T $</th>
          <th class="num">Deaths</th><th>Opening duel</th><th>Plant</th></tr></thead>
        <tbody>{"".join(trs)}</tbody></table></div>
    </details>
  </section>

  {notes_block}

  <section>
    <div class="stat-row">
      <div class="stat"><span class="stat-n">{r["n_rounds"]}</span>
        <span class="label">rounds</span></div>
      {tiles_by_side}
      <div class="stat"><span class="stat-n">{r["plants"]}</span>
        <span class="label">bombs planted</span>
        <span class="den">of {r["n_rounds"]} rounds</span></div>
    </div>
  </section>

  {scoreboard_section}

  {open_block}

  <section>
    <div class="sec-head"><span class="label">By what they could afford</span>
      <h2>Buys</h2></div>
    {calls_block}
    <div class="tbl-wrap"><table>
      <thead><tr><th>{buy_head}</th><th class="num">This match</th>
        {'<th class="num" title="Your record on this buy across every match you '
          'have sent in, both sides together. It is a rate because it has the '
          'chances behind it; the column beside it does not.">Your season</th>'
          if season_buys is not None else ''}
        <th>Which rounds</th></tr></thead>
      <tbody>{"".join(br)}</tbody></table></div>
  </section>

  {where_block}

  <section>
    <p class="note">One match is small, so this page shows counts, with your
      season rate beside them.</p>
  </section>"""
    return html_page("Match report", head, body, user, noindex=bool(share))



@app.get("/players", response_class=HTMLResponse)
def players_page(request: Request):
    """Season player stats for the signed-in coach's own team."""
    user, redirect = require_user(request)
    if redirect:
        return redirect
    team = db.team_for_user(user["id"])
    if team is None:
        return see_other("/dashboard")
    return _players_body(team, user)


def _players_body(team, user=None, share: str = ""):
    """The roster, for a signed-in coach or for a link-holder."""
    shared_note = (
        share_nav(share, "/players") +
        f'<section><p class="note"><strong>Shared read-only.</strong> '
        f'Every player across {esc(team["name"])}&rsquo;s matches, including '
        f'the opponents they played. Click a name for that player&rsquo;s '
        f'own page.</p></section>') if share else ""
    squad = report_mod.squad(team["id"])
    DASH = "&ndash;"

    if not (squad["yours"] or squad["others"]):
        empty = (f'<section><p class="lede">No players yet, because '
                 f'{esc(team["name"])} has no parsed matches. This fills in '
                 f'from the first demo.</p></section>'
                 if share else empty_state("players", team["name"]))
        return html_page("Players", banner("Players", crumb=esc(team["name"])),
                         shared_note + empty, user, noindex=bool(share))

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
            # A share, like every other column here. "22/45" next to "17%" is
            # two units in one row and the eye has to change gear for it; the
            # counts are on the player's own page.
            opening = (f'{100.0 * a["opening_kills"] / a["opens"]:.0f}%'
                       if a["opens"] else "&ndash;")
            out.append(
                f'<tr><td class="name">'
                f'<a href="{player_href(a["steamid"], share)}">'
                f'{esc(a["name"])}</a>{thin}</td>'
                f'<td><span class="{cls}" title="{esc(a["role_why"])}">'
                f'{esc(a["role"])}</span></td>'
                f'<td class="num mono">{a["matches"]}</td>'
                f'<td class="num mono">{a["rounds"]}</td>'
                f'<td class="num mono">{a["adr"]:.0f}</td>'
                f'<td class="num mono">{ct_adr}/{t_adr}</td>'
                f'<td class="num mono">{a["kd"]:.2f}</td>'
                f'<td class="num mono">{a["hs_pct"]:.0f}%</td>'
                f'<td class="num mono">{opening}</td>'
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
            f'<th class="num" title="Damage per round as CT and as T, kept apart because a player strong on one side and weak on the other has a specific problem">CT / T</th><th class="num">K/D</th>'
            f'<th class="num">HS</th>'
            f'<th class="num" title="Share of the opening duels this player '
            f'took that they won">Opening</th>'
            f'<th class="num" title="Share of this player&rsquo;s deaths that a '
            f'teammate traded back">Traded</th>'
            f'<th class="num" title="Grenade and molotov damage per round">'
            f'Nade dmg/rd</th>'
            f'<th class="num">AWP</th></tr></thead>')

    yours, others = squad["yours"], squad["others"]
    # Regulars and one-offs are both YOURS -- they stood on your side -- and
    # they are not the same thing to a coach. The roster is the people who
    # keep coming back; the rest played with you once and their numbers are
    # still yours rather than the opposition's.
    regulars = [a for a in yours if a["matches"] >= 2]
    once = [a for a in yours if a["matches"] < 2]
    if not regulars:
        regulars, once = once, []

    blocks = []
    if regulars:
        blocks.append(
            f'<section><div class="sec-head"><span class="label">'
            f'Who keeps turning up</span><h2>Your players</h2></div>'
            f'<p class="lede">Everyone on your side in more than one match, '
            f'read from your demos.</p>'
            f'<div class="tbl-wrap"><table class="dense">{HEAD}'
            f'<tbody>{player_rows(regulars)}</tbody></table></div></section>')
    if once:
        blocks.append(
            f'<section><div class="sec-head"><span class="label">'
            f'On your side, once</span><h2>Played with you once</h2></div>'
            f'<p class="lede">Stand-ins and one-off fifths. Their rounds count '
            f'as yours.</p>'
            f'<details><summary>Show {len(once)} player'
            f'{"s" if len(once) != 1 else ""}</summary>'
            f'<div class="tbl-wrap"><table class="dense">{HEAD}'
            f'<tbody>{player_rows(once)}</tbody></table></div></details></section>')
    if others:
        note = ('' if yours else
                '<p class="note">Only one match so far, so everyone appears in all of '
                'it and there is no way yet to tell your players from theirs. Upload a '
                'second match and this splits itself.</p>')
        blocks.append(
            f'<section><div class="sec-head"><span class="label">'
            f'The other side of your matches</span>'
            f'<h2>Opponents</h2></div>{note}'
            f'<p class="lede">The players you faced, for context.</p>'
            f'<details><summary>Show {len(others)} opponent'
            f'{"s" if len(others) != 1 else ""}</summary>'
            f'<div class="tbl-wrap"><table class="dense">{HEAD}'
            f'<tbody>{player_rows(others)}</tbody></table></div></details></section>')

    total_rounds = sum(a["rounds"] for a in yours) or sum(a["rounds"] for a in others)
    matches = max((a["matches"] for a in (yours or others)), default=0)
    n_roster = len(regulars) or len(others)
    body = f"""
  <section>
    <div class="stat-row">
      <div class="stat"><span class="stat-n">{n_roster}</span>
        <span class="label">{"your players" if regulars else "players"}</span></div>
      <div class="stat"><span class="stat-n">{matches}</span>
        <span class="label">matches</span></div>
      <div class="stat"><span class="stat-n">{total_rounds}</span>
        <span class="label">player-rounds</span></div>
    </div>
  </section>
  {"".join(blocks)}
  <section>
    <p class="note">Under {report_mod.MIN_ROUNDS_FOR_ROLE} rounds a player is
      marked thin and gets no role. Trades, clutches and flashes are on each
      player&rsquo;s page.</p>
  </section>"""
    return html_page("Players", banner("Players", crumb=esc(team["name"]),
                                       label="Season player stats"),
                     shared_note + body, user, noindex=bool(share))



END_LABEL = {"surrender": "surrendered", "cut": "recording cut short"}


# Zone pictures, drawn once and reused.
#
# A pattern that says "top mid" is unreadable to anyone who did not name the
# zones themselves, and every one of these names was typed by one person
# looking at one picture. The picture belongs next to the table.
#
# Rendering costs a clustering pass over a map's samples, so it is cached: the
# stored zone model only changes when someone deliberately rebuilds it.
#
# BOUNDED, because the values are not small. Each entry is a finished SVG of
# tens of kilobytes and the key includes the set of places a page asked to be
# labelled, so a busy box accumulates one per team per section. Oldest out
# first: a map drawn for a page nobody is reading any more is the right thing
# to lose.
_ZONE_PIC: dict[tuple, list] = {}
ZONE_PIC_MAX = 64
# One drawing per key even when several readers ask at once. Same reasoning as
# the season cache: the work is seconds, and doing it once per person looking
# is the difference between a slow first load and a stalled box.
_ZONE_PIC_LOCKS: dict[tuple, threading.Lock] = {}
_ZONE_PIC_GUARD = threading.Lock()


def _zone_title(map_name: str, level) -> str:
    """What the drawing is, said once, for the people who cannot see it."""
    where = f", {level} floor" if level else ""
    return (f"Map of {map_name.replace('de_', '')}{where}, with your team's "
            f"positions drawn as a density field and the named places numbered")


def zone_pictures(map_name: str, show=None, width: int = 420,
                  stat_zones: bool = False) -> list[dict]:
    """One drawing per floor: [{"level": str|None, "svg": str}, ...].

    A split map gets BOTH floors, not the busier one. Nuke's whole difficulty
    is that its two bombsites sit 369 units above each other — drawing only the
    floor with more traffic hides the site the tables are talking about, which
    on Nuke is exactly the thing a coach came to see.

    `show` is the set of place names the page's tables refer to. Only those get
    a label; everything else is a faint dot.
    """
    # The stats go in the key, because the same map drawn for two different
    # readings is two different pictures. Fingerprinted rather than stored
    # whole: the dict is the cache KEY, so it has to be hashable and small.
    key = (map_name, tuple(sorted(show)) if show else None, width,
           bool(stat_zones))
    if key in _ZONE_PIC:
        return _ZONE_PIC[key]
    with _ZONE_PIC_GUARD:
        lock = _ZONE_PIC_LOCKS.setdefault(key, threading.Lock())
    with lock:
        if key in _ZONE_PIC:
            return _ZONE_PIC[key]
        out = _draw_zones(map_name, show, width, key, stat_zones)
    with _ZONE_PIC_GUARD:
        _ZONE_PIC_LOCKS.pop(key, None)
    return out


def _draw_zones(map_name: str, show, width: int, key,
                stat_zones: bool = False) -> list[dict]:
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
            # In stat mode every shape is a place the kills and deaths were
            # counted under, so it is keyed by the counting rule itself.
            grouped = (movement.groups_of_samples(map_name, x, y, z)
                       if stat_zones and len(x) else None)
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
                                             title=_zone_title(map_name, level),
                                             mask=msk,
                                             stat_zones=stat_zones,
                                             sample_key=(grouped[0][sel]
                                                         if grouped else None),
                                             centre_key=(
                                                 [int(grouped[1][i + 1])
                                                  for i in idx]
                                                 if grouped else None))})
    except Exception:
        out = []            # a missing picture must never break the page
    if len(_ZONE_PIC) >= ZONE_PIC_MAX:
        _ZONE_PIC.pop(next(iter(_ZONE_PIC)))
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
          <code>.dem.gz</code> file. Upload it as it is; there is no need to
          unpack it.</p></div>
      <div class="card"><h3>Valve matchmaking</h3>
        <p class="lede">In CS2: <b>Watch &rarr; Your Matches</b>, then Download beside
          the match. Files land in your <code>csgo/replays</code> folder.</p></div>
    </div>
    <p class="note"><strong>Demos expire.</strong> FACEIT and Valve both delete
      match demos after a few weeks, so save the ones worth keeping now. A season
      you cannot download is a season this cannot analyse.</p>
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
    # where the match sits in the season. Never truncated: the chart slants
    # its labels when they do not fit flat, and "mir" named no map at all.
    pts = [(f'{i + 1} {m["map"]}',
            m[metric], m["result"] or "")
           for i, m in enumerate(series) if m.get(metric) is not None]
    vals = [v for _, v, _ in pts]

    # THE SEASON'S OWN FIGURE, not the mean of the points drawn.
    #
    # Averaging eleven percentages gives every match one vote, so a six-round
    # surrender counts as much as a twenty-nine-round Mirage and the answer
    # drifts a point or two off the number Team stats prints from the same
    # rounds. Summing the numerators and dividing once is the season's
    # average, which is what the words "your average" mean everywhere else on
    # the site.
    shown = [m for m in series if m.get(metric) is not None]

    def weighted(rows):
        hit = sum(m["parts"][metric][0] for m in rows)
        of = sum(m["parts"][metric][1] for m in rows)
        if not of:
            return sum(m[metric] for m in rows) / len(rows) if rows else 0.0
        return (100.0 * hit / of) if unit else (hit / of)

    avg = weighted(shown) if shown else 0

    # Is it holding?
    #
    # A GAP THIS PAGE WILL CALL A CHANGE HAS TO BE BIGGER THAN CHANCE MAKES.
    # The old rule compared the last three with the rest and said "better" or
    # "worse" at three points apart. Run against a simulated team whose true
    # rate never moves, using this season's own match lengths, that fired in
    # 69% of seasons where nothing had happened. It was a coin flip with a
    # sentence wrapped round it, on the page whose whole question is whether
    # something held.
    #
    # Five matches and fourteen points brings it to 3% at eleven matches and
    # 0% at thirty. Five rather than three because three is about seventy
    # rounds and no length of season makes that side of the comparison any
    # bigger; fourteen points because below that, at these denominators, a
    # team that did nothing produces the gap anyway.
    RECENT = 5
    verdict = ""
    if len(shown) >= RECENT + 3:
        recent, before = shown[-RECENT:], shown[:-RECENT]
        r_avg, b_avg = weighted(recent), weighted(before)
        d = r_avg - b_avg
        n_recent = sum(m["parts"][metric][1] for m in recent)
        n_before = sum(m["parts"][metric][1] for m in before)

        # HOW BIG A GAP HAS TO BE BEFORE IT IS WORTH A WORD, read off this
        # season's own match to match spread rather than fixed.
        #
        # A constant was tried and it only works for one shape of number. The
        # three percentages are counts over counts and 14 points suits all
        # three; damage per round is a mean of a quantity and its spread has
        # nothing to do with theirs, so "it would take 14 points" was a number
        # borrowed from a different question. Two standard errors of the
        # difference between the two groups is the same statement for any of
        # them, and lands within a point of 14 for the percentages.
        def spread(rows):
            xs = [m[metric] for m in rows]
            mean = sum(xs) / len(xs)
            var = sum((x - mean) ** 2 for x in xs) / max(1, len(xs) - 1)
            return var / len(xs)

        # 2.3 rather than 2.0: two standard errors targets one season in
        # twenty, and with the spread itself estimated from five and six
        # matches it overshoots to about one in fourteen. Simulated at 2.0,
        # 2.3 and 2.6 against a team that never changes; 2.3 lands on 4 to 5%
        # at both eleven matches and thirty.
        need = 2.3 * (spread(recent) + spread(before)) ** 0.5
        # A season so consistent that the spread is near zero would call a
        # rounding error a change, so the gap also has to be visible in the
        # printed figures.
        need = max(need, 1.0)

        if abs(d) >= need:
            word = "better" if d > 0 else "worse"
            tail = (f'That is {word}, and further apart than your matches '
                    f'usually land. Worth asking what changed.')
        else:
            word = "about the same"
            # Saying WHY is the whole value of the line. Without it a reader
            # takes it as the page having found nothing worth looking for,
            # rather than having looked and found the difference inside the
            # noise.
            tail = (f'Too close to call: it would take a gap of about '
                    f'{need:.0f}{" points" if unit == "%" else " " + label.lower()}.')
        verdict = (
            f'<div class="note"><strong>Last {RECENT} matches:</strong> '
            f'{r_avg:.0f}{unit} over {n_recent} rounds. Before that, '
            f'{b_avg:.0f}{unit} over {n_before}. {tail}</div>')

    chart = charts.both(
        charts.trend(pts, unit=unit, is_pct=bool(unit), avg=avg),
        charts.trend(pts, width=320, unit=unit, is_pct=bool(unit), avg=avg,
                     compact=True))

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
        # EVERY match, including the ones where a column has no answer.
        #
        # This used to skip any match missing one of the three, which quietly
        # dropped a six-round surrender from a table headed "Every match"
        # because nobody on either side took an opening duel in it. A column
        # with nothing to say prints a dash; it does not delete the row.
        def cell(v, unit="%"):
            return f'{v:.0f}{unit}' if v is not None else "&ndash;"
        res = "&ndash;"
        if m["result"]:
            cls = "win" if m["result"] == "W" else "loss"
            res = f'<span class="res {cls}">{m["result"]}</span>'
        rows.append(
            f'<tr><td class="name">'
            f'<a href="/match/{esc(m["match_key"])}">{esc(m["map"])}</a></td>'
            f'<td>{res}</td>'
            f'<td class="num mono">'
            f'{m["us"] if m["us"] is not None else "&ndash;"}&ndash;'
            f'{m["them"] if m["them"] is not None else "&ndash;"}</td>'
            f'<td class="num mono">{m["win_pct"]:.0f}%</td>'
            f'<td class="num mono">{cell(m["adr"], "")}</td>'
            f'<td class="num mono">{cell(m["traded_pct"])}</td>'
            f'<td class="num mono">{cell(m["opening_pct"])}</td></tr>')
    rows = "".join(rows)

    body = f"""
  <section>
    <div class="sec-head"><span class="label">Match by match</span>
      <h2>{esc(label)}</h2></div>
    <p class="lede">{esc(blurb)} Oldest on the left. The dashed line is your
      average.</p>
    <div style="display:flex;gap:7px;flex-wrap:wrap">{tabs}</div>
    <div style="display:flex;gap:7px;flex-wrap:wrap">{map_tabs}</div>
    <div class="chart">{chart}</div>
    {verdict}
  </section>

  <section>
    <details><summary>See every match{" on " + esc(map.replace("de_", "")) if map else ""}</summary>
    <div class="tbl-wrap"><table>
      <thead><tr><th>Map</th><th>Result</th><th class="num">Score</th>
        <th class="num">Rounds won</th><th class="num">ADR</th>
        <th class="num">Traded</th><th class="num">Opening</th></tr></thead>
      <tbody>{rows}</tbody></table></div>
    </details>
  </section>

  <section>
    <p class="note">No line is fitted and nothing is predicted.</p>
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
    last_day = None
    for m in items:
        # The upload date heads its group of rows. Eleven rows that each said
        # "uploaded 2026-08-29" said it ten times too often.
        if m["uploaded"] != last_day:
            last_day = m["uploaded"]
            rows.append(f'<tr class="grp"><td colspan="3" class="den">'
                        f'Uploaded {esc(last_day)}</td></tr>')
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
        # Beside the map, not in a column of its own: a parsed match has no
        # status worth a cell, and every match is parsed by the time anyone
        # looks. One pill in eleven rows is not a column.
        status = ('' if m["status"] == "parsed"
                  else f' <span class="pill">{esc(m["status"])}</span>')
        rows.append(
            f'<tr><td class="name">{name}{cut}{status}'
            f'<div class="den" style="font-weight:400" title="{esc(m["filename"])}">'
            f'{esc(m["tier"] or "")}</div></td>'
            f'<td class="num">{score}</td>'
            f'<td class="num mono">{m["rounds"] or "&ndash;"}</td></tr>')

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
    <p class="lede">A demo has no match date, so the date shown is when you
      uploaded it. The order is the real one.</p>
    <div class="tbl-wrap"><table>
      <thead><tr><th>Match</th><th class="num">Score</th>
        <th class="num">Rounds</th></tr></thead>
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
    return _stats_body(team, user)


def _stats_body(team, user=None, share: str = ""):
    """The season report, for a signed-in coach or for a link-holder.

    `share` is the token when somebody followed a link instead of logging in.
    It changes where the match links point and nothing else: the roster is
    meant to read the same page the coach reads.
    """
    # Built here rather than at the end, because the empty season returns
    # before the end and a link-holder who arrives at an empty season still
    # needs to know what they are looking at and how to reach the roster.
    shared_note = (
        share_nav(share, "") +
        f'<section><p class="note"><strong>Shared read-only.</strong> '
        f'This is {esc(team["name"])}&rsquo;s season, sent to you by whoever '
        f'runs the team. Nothing here can be changed from this page and no '
        f'account is needed to read it.</p></section>') if share else ""
    st = report_mod.team_stats(team["id"])
    if st is None:
        # The signed-out version of this cannot be the signed-in one. The
        # empty state tells a coach to go and upload demos, and the person
        # holding a share link is the one player on the roster who cannot.
        empty = (f'<section><p class="lede">There is nothing here yet. '
                 f'{esc(team["name"])} has not had any matches parsed, so '
                 f'whoever sent you this link will have something to show you '
                 f'once they upload their first demo.</p></section>'
                 if share else empty_state("stats", team["name"]))
        return html_page("Team stats",
                         banner("Team stats", crumb=esc(team["name"])),
                         shared_note + empty, user, noindex=bool(share))

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
        # Grouped by map, because practice is planned one map at a time. The
        # ranking still decides the order of the groups and of the cards inside
        # them, so what matters most is still read first.
        groups = []
        for mp, items in plan["by_map"]:
            head = (f'<div class="sec-head"><h3>'
                    f'{"On " + esc(mp) if mp else "Across every map"}</h3></div>')
            groups.append(f'<div style="margin-bottom:22px">{head}'
                          f'<div class="grid2">'
                          f'{"".join(advice_card(i, plan["baseline"]) for i in items)}</div></div>')
        # The ranking, drawn. `stake` is rounds at stake and `good` says which
        # way it points, so the bar is the signed stake: left is what this
        # season is costing, right is what is earning. Same items as the
        # cards below, in the same order, so the two can never disagree.
        #
        # The direction comes from `good` and NOT from `gap`. gap is a rate
        # minus the season baseline, and for a utility finding the rate is a
        # share of FLASHES while the baseline is a share of ROUNDS, so the
        # subtraction is meaningless: advice.py says as much where it explains
        # why those findings carry their own footer. Signed by gap, "Fix who
        # your flashes land on" drew green, as a thing earning them rounds.
        # `good` is the same flag the card's own "worth changing" pill reads.
        def _sign(it):
            return 1.0 if it["good"] else -1.0

        ranked = []
        for it in plan["items"]:
            # A season-wide finding has no place, and labelling three of them
            # "across every map" says nothing three times. Its own headline is
            # the only thing that identifies it.
            side = (it["side"] or "").upper()
            if not it["zone"]:
                label = it["do"]
                ranked.append((label, _sign(it) * it["stake"],
                               f"{it['stake']:.0f} rounds"))
                continue
            label = f"{it['zone']}{', ' + side if side else ''}"
            if it["map"]:
                label = f"{label} on {it['map']}"
            ranked.append((label, _sign(it) * it["stake"],
                           f"{it['stake']:.0f} rounds"))
        gl = charts.diverging(ranked)
        # Shown, not folded away. It is the summary of the cards under it,
        # and it was hidden behind a toggle while two thousand pixels of
        # cards sat open.
        chart_block = (
            f'<div class="chart">{gl}<p class="den" style="margin:12px 0 0">'
            f'Longer bar, more rounds at stake. Left costs you rounds, right '
            f'wins them.</p></div>') if gl else ""

        monday_block = f"""
  <section class="lead">
    <div class="sec-head"><span class="label">Read this one first</span>
      <h2>What to work on</h2></div>
    <p class="lede">Biggest first: how far each one sits from your usual,
      times the rounds it covers.</p>
    {chart_block}
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
                f'<a class="formcard" href="{match_href(f["match_key"], share)}">'
                f'<span class="res {cls}">{esc(f["result"] or "?")}</span>'
                f'<span class="mono">{score}</span>'
                f'<span class="den">{esc(f["map"])}</span></a>')
        form_block = (
            f'<section><div class="sec-head"><span class="label">'
            f'Newest first</span><h2>Recent form</h2></div>'
            f'<p class="lede">Your last {len(form)}. Tap one for its '
            f'report.</p>'
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
        notes=[p_["detail"] for p_ in patterns]) if patterns else ""
    if patterns:
        # The table that used to sit under this repeated the chart row for
        # row. Its one extra, the note on each pattern, rides on the chart's
        # own labels behind the "i".
        patterns_block = f'<div class="chart">{patterns_chart}</div>'
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
              f'Counted per flash, not per player blinded. A blind counts '
              f'if it lasts {utility.MIN_BLIND_SECONDS} seconds or more.')
        kill_pct = 100.0 * uf["got_a_kill"] / uf["thrown"] if uf["thrown"] else 0
        ucard(f"{kill_pct:.0f}%", "of your flashes get somebody killed",
              f'{uf["got_a_kill"]} of {uf["thrown"]} thrown',
              f'An opponent it blinded died to one of you before the flash '
              f'wore off, or within {utility.KILL_GRACE_SECONDS:.0f} second '
              f'after. {uf["kills_from"]} opponents in all.')
        if us and us["molotovs"]:
            deny_pct = 100.0 * us["denied"] / us["molotovs"]
            ucard(f"{deny_pct:.0f}%", "of your molotovs deny space",
                  f'{us["denied"]} of {us["molotovs"]} thrown',
                  f'An opponent had to stand in it, walk out of it or go '
                  f'round it. {us["empty"]} burned with nobody near them.')
        if uu and uu["spent"]:
            ucard(f'${uu["per_round"]:.0f}', "of utility a round, unused at death",
                  f'${uu["wasted"]:,} of ${uu["spent"]:,} bought',
                  f'Still in a player\'s hand when they died, priced at what '
                  f'it cost. Utility a survivor kept is not counted.')

        utility_block = f"""
  <section>
    <div class="sec-head"><span class="label">What your utility did</span>
      <h2>Utility</h2></div>
    <p class="lede">What your utility achieved, counted per throw.</p>
    <div class="stat-row">{"".join(cards)}</div>
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
        ("death", "Where your first death happens",
         "Where the first of you dies, and whether it was traded. Untraded "
         "means playing 4 against 5. The bar is how often it happens, out of "
         "your rounds on that map and side."),
    )
    # Five rows, not twenty.
    #
    # "Where your first death happens" ran to twenty rows with seventeen of
    # them marked thin, which buried the one line worth acting on — mirage T,
    # top mid, first death in 8 of 32 rounds and one round won from them — at
    # position three of twenty. A table nobody reads to the bottom of should
    # not have a bottom.
    POS_TOP_N = 5

    # A row needs rounds on BOTH sides to be worth comparing. Under this many
    # in the rest of the map and side there is nothing to compare it to, and
    # "62% against 0% of two rounds" is not a finding.
    #
    # The same floor `rate()` uses, deliberately: a number too thin to print
    # as a percentage is too thin to rank a table by. At the pattern floor of
    # six, a seven-round row rendering as "2 / 7 thin" outranked comparable
    # rows with real denominators and a smaller gap.
    MIN_COMPARE = report_mod.MIN_CHANCES

    pos_blocks = []
    # Held back rather than appended, because it renders AFTER the first-death
    # table below it. A coach opens this part of the page to find out where
    # rounds are being lost; that is the death table. Where the group stands
    # twelve seconds in is the context for it, not the preface to it.
    early_block = ""
    # ---- where you are early: one section, one row per place
    #
    # The setup reading is the spine because it covers more rounds and is the
    # easier one to picture: two of you standing somewhere twelve seconds in.
    # The commit reading rides on the row as "this is as far as the group
    # got", which is the same place seen from the other end.
    early: dict = {}
    for q in pos:
        if q["kind"] not in ("setup", "commit"):
            continue
        early.setdefault((q["map"], q["side"], q["zone"]), {})[q["kind"]] = q

    rows_early = []
    for (mp, side, zone), pair in early.items():
        spine = pair.get("setup") or pair["commit"]
        com = pair.get("commit")
        # Rounds the difference is worth: how far apart the two groups are,
        # times the smaller of them. A 50-point gap over 8 rounds and a
        # 15-point gap over 30 are both real, and this weighs them the way a
        # coach would rather than letting the widest gap on the fewest rounds
        # win.
        cmp_ok = spine["hit"] >= MIN_COMPARE and spine["other"] >= MIN_COMPARE
        worth = (abs(spine["gap"]) / 100.0 * min(spine["hit"], spine["other"])
                 if cmp_ok else -1.0)
        rows_early.append({"q": spine, "commit": com, "cmp": cmp_ok,
                           "worth": worth, "map": mp, "side": side,
                           "zone": zone})
    rows_early.sort(key=lambda r: (-r["worth"], -r["q"]["hit"]))

    if rows_early:
        top = rows_early[:POS_TOP_N]
        hidden = len(rows_early) - len(top)
        trs = []
        for r in top:
            q = r["q"]
            how_often = report_mod.pct(q["hit"], q["of"]) or 0
            side_up = r["side"].upper()
            trs.append(
                f'<div class="op"><p class="op-head"><span class="pill '
                f'{r["side"]}">{side_up}</span> <strong>{esc(r["zone"])}'
                f'</strong> <span class="den" title="{q["hit"]} of {q["of"]}">'
                f'{esc(r["map"].replace("de_", ""))} &middot; {how_often:.0f}% '
                f'of your {side_up} rounds there</span></p>'
                + charts.versus([
                    ("Went there", report_mod.pct(q["won"], q["hit"]),
                     f'won {q["won"]} of {q["hit"]}'),
                    ("Didn't", report_mod.pct(q["other_won"], q["other"])
                     if r["cmp"] else None,
                     f'won {q["other_won"]} of {q["other"]}')])
                + '</div>')
        note = ""
        if hidden:
            note = (f'<p class="note">The {len(top)} of {len(rows_early)} '
                    f'places with the widest gap.</p>')
        # A round where three of you never held anything together is not a
        # round where you went somewhere else, so it is not in the denominator
        # of a row about how far the group got. How often that happens is
        # itself worth printing: it is most of them.
        pairs = {(q["map"], q["side"]): (q["side_rounds"], q["answered"])
                 for q in pos}
        all_r = sum(v[0] for v in pairs.values())
        ans = sum(v[1] for v in pairs.values())
        if all_r and ans < all_r:
            note += (f'<p class="note">In {all_r - ans} of {all_r} rounds '
                     f'three of you never stood together anywhere. Those '
                     f'rounds are left out.</p>')
        early_block = (
            f'<section><div class="sec-head"><span class="label">From position '
            f'data</span><h2>Where you are in the opening</h2></div>'
            f'<p class="lede">Where two or more of you stand '
            f'{int(movement.SETUP_AT)} seconds in, and how often you win from '
            f'there. Each place is compared with your other rounds on the '
            f'same map and side.</p>'
            f'<div class="chart op-list">{"".join(trs)}</div>{note}</section>')

    # Every place the three tables name, gathered BEFORE any of them render,
    # because the maps are drawn once from the union of all three. In map
    # order of first appearance, which is ranked order: the table rows arrive
    # worst-first, so the map that matters most is drawn first.
    shown_zones: dict[str, set] = {}
    for r in rows_early[:POS_TOP_N]:
        shown_zones.setdefault(r["map"], set()).add(r["zone"])
    chosen = []
    for kind, title, lede in POS_SECTIONS:
        sel = [q for q in pos if q["kind"] == kind]
        if not sel:
            continue
        hidden = max(0, len(sel) - POS_TOP_N)
        sel = sel[:POS_TOP_N]
        for q in sel:
            shown_zones.setdefault(q["map"], set()).add(q["zone"])
        chosen.append((kind, title, lede, sel, hidden))

    for kind, title, lede, sel, hidden in chosen:
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
        more = (f'<p class="note">The top {POS_TOP_N} of '
                f'{POS_TOP_N + hidden} places.</p>' if hidden else "")
        if trades:
            fig = charts.first_deaths([{
                "side": q["side"], "place": q["zone"],
                "map": q["map"].replace("de_", ""),
                "share": report_mod.pct(q["hit"], q["of"]) or 0,
                "traded": report_mod.pct(q["traded"], q["hit"]),
                "won": report_mod.pct(q["won"], q["hit"]),
                "title": f'{q["hit"]} of {q["of"]} {q["side"].upper()} rounds',
                "traded_title": f'{q["traded"]} of {q["hit"]}',
                "won_title": f'{q["won"]} of {q["hit"]}'} for q in sel])
            table = f'<div class="chart">{fig}</div>'
        else:
            table = (f'<div class="tbl-wrap"><table><thead><tr><th>Place</th>'
                     f'<th class="num">Rounds</th><th class="num">Of those, won'
                     f'</th></tr></thead><tbody>{"".join(rws)}</tbody></table>'
                     f'</div>')
        pos_blocks.append(
            f'<section><div class="sec-head"><span class="label">'
            f'From position data</span><h2>{title}</h2></div>'
            f'<p class="lede">{lede}</p>{table}{more}</section>')

    if early_block:
        pos_blocks.append(early_block)

    # ---- where the rounds are decided
    #
    # Four questions on ONE base drawing, switched by the pill row, in the
    # order they decide a round. See the note in movement.scan on why the
    # opening duel and its trade come first.
    #
    # The base is expensive (a map's round_positions, clustered, plus the
    # radar mask) and the readings on top are a few hundred bytes, so three
    # extra layers cost almost nothing. Flipping between them on a map that
    # does not move is also the point: it is how you see that the place you
    # set up is the place you lose the opening.
    # ---- where your rounds are decided
    #
    # See the note on the patch that wrote this: one drawing per map, thirty
    # filter combinations, summed in the browser.
    decided, zdata, znames = [], {}, {}
    decided_block = ""
    try:
        raw = movement.scan(team["id"])
        duels = raw.get("duels", {})
        for mp in sorted(duels, key=lambda m: -sum(
                sum(v[0] + v[1] for v in z.values())
                for z in duels[m].values())):
            rows = {}
            for z, buckets in duels[mp].items():
                rows[str(z)] = [[sd, ph, by, kd[0], kd[1]]
                                for (sd, ph, by), kd in sorted(buckets.items())]
            if not rows:
                continue
            zdata[mp] = rows
            znames[mp] = {str(k): v
                          for k, v in raw.get("names", {}).get(mp, {}).items()}
            for pic in zone_pictures(mp, show=set(), width=420,
                                     stat_zones=True):
                floor = (f' <span class="pill">{esc(pic["level"])}</span>'
                         if pic["level"] else "")
                decided.append(
                    f'<figure class="zonefig reading" data-map="{esc(mp)}">'
                    f'{pic["svg"]}<figcaption class="den"><strong>'
                    f'{esc(mp.replace("de_", ""))}</strong>{floor}'
                    f'</figcaption></figure>')
    except Exception:
        decided = []        # a missing picture must never break the page

    if decided:
        ROWS = [("side", [("all", "Overall"), ("t", "T side"), ("ct", "CT side")]),
                ("phase", [("all", "Overall"), ("pre", "Pre-plant"),
                           ("post", "Post-plant")]),
                ("buy", [("all", "Overall"), ("pistol", "Pistol"), ("eco", "Eco"),
                         ("force", "Force buy"), ("full", "Full buy")])]
        filters = "".join(
            f'<div class="zrow" data-f="{f}">' + "".join(
                f'<button type="button" class="pill zpill{" on" if i == 0 else ""}" '
                f'data-v="{v}">{esc(lab)}</button>'
                for i, (v, lab) in enumerate(opts)) + '</div>'
            for f, opts in ROWS)
        # Its own block, placed straight under "What to work on": where on
        # the map you win and lose fights is what the first real coach asked
        # for before anything else, and it sat below four other sections.
        decided_block = (
            f'<section><div class="sec-head"><span class="label">From position '
            f'data</span><h2>Where your rounds are decided</h2></div>'
            f'<p class="lede">Your kills and deaths in every place on the map. '
            f'<strong>Green means you win more fights there than you do '
            f'everywhere else</strong> under the same filter, red means fewer, '
            f'faint means the same or too little to say. Hover anywhere on the '
            f'map for the numbers.</p>'
            f'<div class="zfilters">{filters}</div>'
            f'<div class="zonerow">{"".join(decided)}</div>'
            f'<script>(function(){{'
            f'var D={json.dumps(zdata, separators=(",", ":"))},'
            f'N={json.dumps(znames, separators=(",", ":"))},'
            f'F={{side:"all",phase:"all",buy:"all"}},MIN=6;'
            f'function pl(n,w){{return n+" "+w+(n===1?"":"s");}}'
            f'function paint(){{'
            f'var figs=document.querySelectorAll(".zonefig[data-map]");'
            f'for(var a=0;a<figs.length;a++){{'
            f'var mp=figs[a].getAttribute("data-map"),d=D[mp]||{{}},n=N[mp]||{{}};'
            f'var tk=0,td=0,per={{}};'
            f'for(var z in d){{var k=0,x=0,r=d[z];'
            f'for(var b=0;b<r.length;b++){{var q=r[b];'
            f'if(F.side!=="all"&&q[0]!==F.side)continue;'
            f'if(F.phase!=="all"&&q[1]!==F.phase)continue;'
            f'if(F.buy!=="all"&&q[2]!==F.buy)continue;'
            f'k+=q[3];x+=q[4];}}'
            f'per[z]=[k,x];tk+=k;td+=x;}}'
            f'var base=td>0?tk/td:1;'
            f'var ps=figs[a].querySelectorAll(".zfill");'
            f'for(var p=0;p<ps.length;p++){{var el=ps[p],z=el.getAttribute("data-z");'
            f'var v=per[z]||[0,0],k=v[0],x=v[1],tot=k+x;'
            f'var ttl=el.querySelector("title"),nm=n[z]||"this place";'
            f'if(tot<MIN){{el.setAttribute("fill","var(--faint)");'
            f'el.setAttribute("opacity","0");'
            f'ttl.textContent=nm+": "+pl(k,"kill")+", "+pl(x,"death")+" here. '
            f'Too few to read anything into.";continue;}}'
            f'var kd=x>0?k/x:k,rel=(kd-base)/(base||1);'
            f'var good=rel>0.12,bad=rel<-0.12;'
            f'el.setAttribute("fill",good?"var(--good)":bad?"var(--bad)":"var(--faint)");'
            f'el.setAttribute("opacity",(good||bad)?String(Math.min(0.72,0.30+Math.abs(rel))):"0");'
            f'ttl.textContent=nm+": "+pl(k,"kill")+", "+pl(x,"death")+", K/D "+kd.toFixed(2)'
            f'+" against "+base.toFixed(2)+" everywhere else";}}}}}}'
            f'var rows=document.querySelectorAll(".zfilters .zrow");'
            f'for(var i=0;i<rows.length;i++){{(function(row){{'
            f'var bs=row.querySelectorAll(".zpill");'
            f'for(var j=0;j<bs.length;j++){{bs[j].addEventListener("click",function(){{'
            f'F[row.getAttribute("data-f")]=this.getAttribute("data-v");'
            f'for(var m=0;m<bs.length;m++){{bs[m].classList.toggle("on",bs[m]===this);}}'
            f'paint();}});}}}})(rows[i]);}}'
            f'paint();}})();</script></section>')

    # ---- the maps, once each, at the head of the three tables
    figs = []
    for mp, places in shown_zones.items():
        for pic in zone_pictures(mp, show=places, width=420):
            floor = (f' <span class="pill">{esc(pic["level"])}</span>'
                     if pic["level"] else "")
            figs.append(
                f'<figure class="zonefig">{pic["svg"]}'
                f'<figcaption class="den"><strong>'
                f'{esc(mp.replace("de_", ""))}</strong>{floor}</figcaption>'
                f'</figure>')
    if figs and pos_blocks:
        n = len(pos_blocks)
        pos_blocks.insert(0, (
            f'<section><div class="sec-head"><span class="label">From position '
            f'data</span><h2>The maps you play</h2></div>'
            f'<p class="lede">The places named below, drawn from your own '
            f'rounds.</p>'
            f'<div class="zonerow">{"".join(figs)}</div></section>'))

    if pos_blocks or decided_block:
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

    # With your side known, the map pool is a figure, and the Sides and Buys
    # tables go: the Recurring patterns chart already has "as CT", "as T" and
    # every buy, row for row. Without it, they are the only place both sides'
    # numbers appear, so they stay.
    if known:
        pool_fig = charts.sides([{
            "chip": map_chip(name), "matches": m["matches"],
            "all": report_mod.pct(m["you_won"], m["you_played"]),
            "all_title": f'{m["you_won"]} of {m["you_played"]}',
            "ct": report_mod.pct(m["you_ct_won"], m["you_ct"]),
            "ct_title": f'{m["you_ct_won"]} of {m["you_ct"]}',
            "t": report_mod.pct(m["you_t_won"], m["you_t"]),
            "t_title": f'{m["you_t_won"]} of {m["you_t"]}'}
            for name, m in st["maps"].items()])
        pool_block = (
            f'<section><div class="sec-head"><span class="label">Where the '
            f'rounds went</span><h2>Map pool</h2></div>'
            f'<p class="lede">Rounds won on each map, by side. The mark is '
            f'50%.</p><div class="chart">{pool_fig}</div></section>')
    else:
        pool_block = f"""
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
  </section>"""

    if known:
        # A coach is a perfectly good anchor, since they sit on your side
        # every match, but naming one here as a player is the same mistake
        # the roster made. Only people team_players() keeps are named.
        players = {a["steamid"] for a in report_mod.team_players(team["id"])}
        named = [v["name"] for sid, v in st["anchors"]["anchors"].items()
                 if sid in players]
        who = ", ".join(named)
        n = st["anchors"]["matches"]
        # The same floor team_anchors() applies, so the sentence is true.
        least = max(2, int(n * report_mod.ANCHOR_SHARE))
        how = (f"all {n} of your matches" if least >= n
               else f"at least {least} of your {n} matches")
        roster_note = (
            f'<section><p class="note"><strong>Every number here is your '
            f'side\'s rounds.</strong> Your side is whichever side {esc(who)} '
            f'{"was" if len(named) == 1 else "were"} on: '
            f'they played in {how}.</p></section>'
            if named else "")
    else:
        roster_note = (
            '<section><p class="warn"><strong>These are both sides, not just '
            'yours.</strong> A demo carries no team names, only sides. Telling '
            'yours apart needs a player who appears across several matches: '
            'upload one more and this page switches to your rounds '
            'alone.</p></section>')

    # Opening duels won, not rounds won; see opening_tile(). Without your
    # side known there is no "you" to have won a duel, so it is the count.
    second_tile = (opening_tile(y if known else None) or
                   f'<div class="stat"><span class="stat-n">{st["rounds"]}</span>'
                   f'<span class="label">rounds</span></div>')

    body = f"""
  {PAGE_NAV}
  <section>
    <div class="stat-row">
      <div class="stat"><span class="stat-n">{st["matches"]}</span>
        <span class="label">matches</span></div>
      {second_tile}
      <div class="stat"><span class="stat-n">{len(st["maps"])}</span>
        <span class="label">maps played</span></div>
      <div class="stat"><span class="stat-n">{len(plan["items"])}</span>
        <span class="label">to work on</span></div>
    </div>
  </section>

  {monday_block}

  {decided_block}

  {form_block}

  <section>
    <div class="sec-head"><span class="label">What repeats across your matches</span>
      <h2>Recurring patterns</h2></div>
    <p class="lede">Counted, never predicted. A line needs
      {report_mod.MIN_PATTERN_CHANCES} chances to appear.</p>
    {patterns_block}
  </section>

  {utility_block}

  {positional_block}

  {pool_block}

  {roster_note}"""
    body = shared_note + body
    return html_page("Team stats", banner("Team stats", crumb=esc(team["name"]),
                                          label="Across every match you have sent in"),
                     body, user, noindex=bool(share))



@app.get("/player/{steamid}", response_class=HTMLResponse)
def player_page(request: Request, steamid: str):
    """One player, match by match."""
    user, redirect = require_user(request)
    if redirect:
        return redirect
    team = db.team_for_user(user["id"])
    if team is None:
        return see_other("/dashboard")
    return _player_body(steamid, team, user)


def _player_body(steamid: str, team, user=None, share: str = ""):
    """One player, for a signed-in coach or for a link-holder.

    `player_matches` is scoped to the team, so an unknown steam id is a 404
    here rather than a window into anybody else's season. That is what makes
    this safe to put behind a share link.
    """
    p = report_mod.player_matches(team["id"], steamid)
    if p is None:
        return HTMLResponse(page("Not found", banner("Not found"),
                                 '<section><p class="lede">No rounds for that player '
                                 'in these matches.</p></section>', user,
                                 noindex=bool(share)), status_code=404)

    DASH = "&ndash;"
    t = p["totals"]
    rows, short_rows = [], []
    for m in p["matches"]:
        # The same W/L pill the rest of the site uses. "Won"/"Lost" in a
        # column of twelve numbers is two words doing a letter's work.
        res = (f'<span class="res {"win" if m["result"] == "won" else "loss"}">'
               f'{"W" if m["result"] == "won" else "L"}</span>')
        clutch = (f'{m["clutch_won"]}/{m["clutch_tried"]}'
                  if m["clutch_tried"] else "&ndash;")
        blind = (f'{m["blind_per_flash"]:.2f}' if m["flashes_thrown"] else "&ndash;")
        rows.append(
            f'<tr><td class="name">'
            f'<a href="{match_href(m["match_key"], share)}">'
            f'{map_chip(m["map_name"])}</a>'
            f'<div class="den" style="font-weight:400">{esc((m["added"] or "")[:10])}</div></td>'
            f'<td>{res}</td>'
            f'<td class="num mono">{esc(m["score"])}</td>'
            f'<td class="num mono">{m["rounds"]}</td>'
            f'<td class="num mono">{m["adr"]:.0f}</td>'
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
        short_rows.append(
            f'<tr><td class="name">'
            f'<a href="{match_href(m["match_key"], share)}">'
            f'{map_chip(m["map_name"])}</a></td>'
            f'<td>{res}</td>'
            f'<td class="num mono">{esc(m["score"])}</td>'
            f'<td class="num mono">{m["adr"]:.0f}</td>'
            f'<td class="num mono">{m["kills"]}{DASH}{m["deaths"]}{DASH}{m["assists"]}</td>'
            f'<td class="num mono">{m["opening_kills"]}/{m["opens"]}</td>'
            f'<td class="num mono">{m["trade_kills"] or "&ndash;"}</td></tr>')
    # Newest first, like every other list of matches on the site. The chart
    # above it reads oldest to newest, left to right, as a time axis does.
    rows.reverse()
    short_rows.reverse()

    # ADR in every match, as a picture. It replaces a "worst to best" tile
    # that let a six-round surrender set the range, and the +47 flags in
    # the table. Matches under ten rounds are drawn hollow.
    series = p["matches"]
    adr_pts = [(f'{i + 1} {m["map_name"].replace("de_", "")}', m["adr"],
                "W" if m["result"] == "won" else "L")
               for i, m in enumerate(series)]
    thin = {i for i, m in enumerate(series) if m["rounds"] < 10}
    adr_chart = charts.both(
        charts.trend(adr_pts, unit="", is_pct=False, avg=t["adr"],
                     hollow=thin, title="ADR in each match, oldest to newest"),
        charts.trend(adr_pts, width=320, unit="", is_pct=False, avg=t["adr"],
                     hollow=thin, compact=True,
                     title="ADR in each match, oldest to newest")
    ) if len(adr_pts) > 1 else ""
    adr_block = (f'<p class="lede">ADR in each match against this player&rsquo;s '
                 f'average. A hollow point is a match under ten rounds.</p>'
                 f'<div class="chart">{adr_chart}</div>') if adr_chart else ""

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
            f'<span class="den">with {t["flashes_thrown"]} flashes thrown</span></div>')
        # Same threshold as the team page, said once where the numbers are.
        blind_note = (
            f'<p class="den" style="margin-top:2px">A blind counts if it lasts '
            f'{utility.MIN_BLIND_SECONDS} seconds or more.</p>')
        if t["flashes_landed"]:
            ucards.append(
                f'<div class="stat"><span class="stat-n">'
                f'{t["own_flash_pct"]:.0f}%</span>'
                f'<span class="label">of the players they blinded were '
                f'teammates</span>'
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
                f'<span class="label">of utility a round, unused at death</span>'
                f'<span class="den">${t["nades_wasted"]:,} of '
                f'${t["nades_value"]:,} bought</span></div>')
        util_block = f"""
  <section>
    <div class="sec-head"><span class="label">What they threw</span>
      <h2>Utility</h2></div>
    <div class="stat-row">{"".join(ucards)}</div>
    {blind_note}
  </section>"""
    else:
        util_block = ""

    body = f"""
  <section>
    <div class="stat-row">
      <div class="stat"><span class="stat-n">{len(p["matches"])}</span>
        <span class="label">matches</span></div>
      <div class="stat"><span class="stat-n">{t["adr"]:.0f}</span>
        <span class="label">ADR overall</span></div>
      <div class="stat"><span class="stat-n">{t["kd"]:.2f}</span>
        <span class="label">K/D</span></div>
    </div>
    <p class="lede">Role: <strong>{esc(t["role"])}</strong>
      <span class="den">({esc(t["role_why"])})</span></p>
  </section>

  <section>
    <div class="sec-head"><span class="label">Every match</span>
      <h2>Match by match</h2></div>
    {adr_block}
    <div class="tbl-wrap" style="margin-top:14px"><table>
      <thead><tr><th>Match</th><th>Result</th><th class="num">Score</th>
        <th class="num">ADR</th><th class="num">K{DASH}D{DASH}A</th>
        <th class="num" title="Opening duels won, of those taken">Opening</th>
        <th class="num" title="Kills that traded a teammate who had just died">Trades</th>
        </tr></thead>
      <tbody>{"".join(short_rows)}</tbody></table></div>
    <details><summary>All columns</summary>
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
    </details>
  </section>

  {util_block}"""
    return html_page(f'{p["name"]}', banner(p["name"], crumb=esc(team["name"]),
                                            label="Player"),
                     share_nav(share, "/players") + body, user,
                     noindex=bool(share))


# ---------------------------------------------------------------- account

# ------------------------------------------------------- the shared report
#
# Everything under /r/ is reachable by holding the URL and nothing else. No
# session is read, so a coach signed in on the same browser sees exactly what
# a player sees, which is the only way to be sure the link works before
# sending it.
#
# A 404 rather than a 403 for a token that names nothing. There is no
# difference worth telling a stranger between "revoked" and "never existed",
# and a 403 confirms that a guess was close.
def _share_team(token: str):
    return db.team_by_share_token((token or "").strip())


def _share_404() -> HTMLResponse:
    return HTMLResponse(page("Not found", banner("Not found"),
                             '<section><p class="lede">This link is not valid. '
                             'It may have been revoked by whoever sent it.'
                             '</p></section>', None, noindex=True),
                        status_code=404)


@app.get("/r/{token}", response_class=HTMLResponse)
def shared_season(token: str):
    team = _share_team(token)
    if team is None:
        return _share_404()
    return _stats_body(team, None, share=token)


@app.get("/r/{token}/players", response_class=HTMLResponse)
def shared_players(token: str):
    team = _share_team(token)
    if team is None:
        return _share_404()
    return _players_body(team, None, share=token)


@app.get("/r/{token}/p/{steamid}", response_class=HTMLResponse)
def shared_player(token: str, steamid: str):
    team = _share_team(token)
    if team is None:
        return _share_404()
    return _player_body(steamid, team, None, share=token)


@app.get("/r/{token}/m/{match_key}", response_class=HTMLResponse)
def shared_match(token: str, match_key: str):
    team = _share_team(token)
    if team is None:
        return _share_404()
    return _match_body(match_key, None, share=token, share_team=team)


# --------------------------------------------------- making and revoking one
@app.post("/share/new")
def share_new(request: Request, csrf: str = Form("")):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    if not auth.check_csrf(user, csrf):
        return see_other("/account")
    team = db.team_for_user(user["id"])
    if team is None:
        return see_other("/dashboard")
    # 32 urlsafe characters out of secrets, which is the same generator the
    # session cookies use. Guessing one is not a threat model anybody needs to
    # think about at this length.
    token = secrets.token_urlsafe(24)
    # db.execute, not conn.execute: sqlite3 takes its parameters as ONE
    # sequence, so conn.execute(sql, a, b) is a TypeError and was a 500 on
    # the button that makes the link. db.execute(*args) is the wrapper that
    # packs them, and it commits.
    db.execute("UPDATE teams SET share_token = ? WHERE id = ?",
               token, team["id"])
    db.audit(user["id"], "share_new", f"team={team['id']}")
    return see_other("/account")


@app.post("/team/switch")
def team_switch(request: Request, team_id: str = Form(""), csrf: str = Form("")):
    """Point this account at a different one of its own teams."""
    user, redirect = require_user(request)
    if redirect:
        return redirect
    if not auth.check_csrf(user, csrf):
        return see_other("/account")
    try:
        wanted = int(team_id)
    except (TypeError, ValueError):
        return see_other("/account")
    # set_active_team refuses a team the user is not a member of, so a forged
    # id in the form gets a redirect rather than somebody else's season.
    if db.set_active_team(user["id"], wanted):
        db.audit(user["id"], "team_switch", f"team={wanted}")
    return see_other("/dashboard")


@app.post("/claim/new")
def claim_new(request: Request, csrf: str = Form("")):
    """Make a one-time link that hands this team to whoever opens it.

    For the case this product is actually sold in: a report is built FOR a
    coach out of their own public demos, and they then want it to be theirs.
    Without this, every such report is a demo that dies with the account that
    made it.
    """
    user, redirect = require_user(request)
    if redirect:
        return redirect
    if not auth.check_csrf(user, csrf):
        return see_other("/account")
    team = db.team_for_user(user["id"])
    if team is None or team["member_role"] != "owner":
        return see_other("/account")
    token = secrets.token_urlsafe(24)
    db.execute("UPDATE teams SET claim_token = ? WHERE id = ?", token, team["id"])
    db.audit(user["id"], "claim_new", f"team={team['id']}")
    return see_other("/account")


@app.post("/claim/revoke")
def claim_revoke(request: Request, csrf: str = Form("")):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    if not auth.check_csrf(user, csrf):
        return see_other("/account")
    team = db.team_for_user(user["id"])
    if team is not None and team["member_role"] == "owner":
        db.execute("UPDATE teams SET claim_token = NULL WHERE id = ?", team["id"])
        db.audit(user["id"], "claim_revoke", f"team={team['id']}")
    return see_other("/account")


@app.get("/claim/{token}", response_class=HTMLResponse)
def claim_page(request: Request, token: str):
    """Confirm a handover. GET never changes anything; the POST below does.

    Taking a team away from its current owner on a GET would mean any crawler,
    link preview or antivirus scanner that touched the address could perform
    it. So this page asks.
    """
    team = db.one("SELECT * FROM teams WHERE claim_token = ? AND claim_token != ''",
                  token) if token else None
    if team is None:
        raise StarletteHTTPException(status_code=404)

    user = current(request)
    if user is None:
        body = f"""
  <section>
    <div class="card">
      <h3>{esc(team["name"])} is being handed to you</h3>
      <p class="lede">Whoever built this team wants it to be yours: the
        season, the demos already in it, and the link you send your roster.</p>
      <p>Sign in first, or make an account, and then open this link again.</p>
      <p><a class="btn" href="/login">Log in</a>
         <a class="btn ghost" href="/signup">Make an account</a></p>
      <p class="den">Nothing has changed yet.</p>
    </div>
  </section>"""
        return HTMLResponse(page("Claim a team | Counterplay",
                                 banner("Claim a team"), body, noindex=True))

    roster = db.query("""SELECT u.email FROM team_members m
                           JOIN users u ON u.id = m.user_id
                          WHERE m.team_id = ?""", team["id"])
    others = ", ".join(esc(r["email"]) for r in roster) or "nobody"
    body = f"""
  <section>
    <div class="card">
      <h3>Take over {esc(team["name"])}?</h3>
      <p class="lede">You will become the owner. Everything already in the
        team comes with it: every demo, every match report, and the season.</p>
      <p class="den">Whoever has it now ({others}) loses access when you
        accept. If you want them to keep reading it, send them the roster
        link afterwards.</p>
      <form method="post" action="/claim/{esc(token)}">{csrf_input(user)}
        <button class="btn" type="submit">Yes, this team is mine</button>
      </form>
      <p class="den">Signed in as {esc(user["email"])}. If that is the wrong
        account, log out and open this link again.</p>
    </div>
  </section>"""
    return HTMLResponse(page("Claim a team | Counterplay",
                             banner("Claim a team"), body, user, noindex=True))


@app.post("/claim/{token}")
def claim_accept(request: Request, token: str, csrf: str = Form("")):
    """Perform the handover. The token burns, because ownership is not replayable."""
    user, redirect = require_user(request)
    if redirect:
        return redirect
    if not auth.check_csrf(user, csrf):
        return see_other("/account")
    team = db.one("SELECT * FROM teams WHERE claim_token = ? AND claim_token != ''",
                  token) if token else None
    if team is None:
        raise StarletteHTTPException(status_code=404)

    with db.connect() as c:
        # A complete handover, not a shared login. The people who held it lose
        # access, because a team that was built for somebody as a pitch should
        # not leave the builder reading their season forever. The new owner can
        # always send the roster link back.
        c.execute("DELETE FROM team_members WHERE team_id = ?", (team["id"],))
        c.execute("""INSERT INTO team_members (team_id, user_id, member_role,
                                               created_at)
                     VALUES (?,?,?,?)""",
                  (team["id"], user["id"], "owner", db.utcnow()))
        c.execute("UPDATE teams SET claim_token = NULL WHERE id = ?",
                  (team["id"],))
        c.execute("UPDATE users SET active_team_id = ? WHERE id = ?",
                  (team["id"], user["id"]))
    db.audit(user["id"], "claim_accept", f"team={team['id']}")
    return see_other("/dashboard")


@app.post("/share/revoke")
def share_revoke(request: Request, csrf: str = Form("")):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    if not auth.check_csrf(user, csrf):
        return see_other("/account")
    team = db.team_for_user(user["id"])
    if team is None:
        return see_other("/dashboard")
    db.execute("UPDATE teams SET share_token = NULL WHERE id = ?", team["id"])
    db.audit(user["id"], "share_revoke", f"team={team['id']}")
    return see_other("/account")


@app.get("/account", response_class=HTMLResponse)
def account(request: Request):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    team = db.team_for_user(user["id"])

    # The link to send the roster. Shown in full and selectable rather than
    # behind a "copy" button that needs JavaScript to do anything: the normal
    # use of this page is a coach coming back to re-read a link they already
    # made, and text you can select always works.
    if team is None:
        share_block = ""
    elif team["share_token"]:
        # mail.SITE_URL, not the request's own host: the reset emails already
        # use it, and a link a coach is about to paste somewhere else must be
        # the site's public address rather than whatever proxy header arrived.
        link = f"{mail.SITE_URL.rstrip('/')}/r/{esc(team['share_token'])}"
        share_block = f"""
  <section>
    <div class="card">
      <h3>Your roster&rsquo;s link</h3>
      <p class="lede">Anyone with this link can read your season and match
        reports, no account needed. They can&rsquo;t change anything or see
        other teams.</p>
      <p><a href="{link}" class="mono" style="overflow-wrap:anywhere">{link}</a></p>
      <p class="den">Send it to your players. Revoke it any time: the old
        link stops working at once.</p>
      <form method="post" action="/share/revoke">{csrf_input(user)}
        <button class="btn ghost" type="submit">Revoke and make a new one</button>
      </form>
    </div>
  </section>"""
    else:
        share_block = f"""
  <section>
    <div class="card">
      <h3>Share with your roster</h3>
      <p class="lede">Make a link your players can open to read your season
        and your match reports. No account for them to create, and they cannot
        change anything.</p>
      <form method="post" action="/share/new">{csrf_input(user)}
        <button class="btn" type="submit">Make a link</button>
      </form>
    </div>
  </section>"""

    # More than one team is not the coach case, it is the case of somebody
    # building a report FOR a coach before that coach has an account. Without
    # a picker the second team is unreachable: team_for_user() falls back to
    # the oldest membership and nothing else in the UI names the others.
    mine = db.teams_for_user(user["id"])
    if len(mine) > 1:
        options = "".join(
            f'<option value="{t["id"]}"'
            f'{" selected" if team is not None and t["id"] == team["id"] else ""}>'
            f'{esc(t["name"])}'
            f'{" (not yours)" if t["member_role"] == "admin" else ""}'
            f'</option>' for t in mine)
        switch_block = f"""
  <section>
    <div class="card">
      <h3>Which team are you working on?</h3>
      <p class="lede">{"This is the master account, so every team on the site is listed. The ones marked <em>not yours</em> you can read but not hand over." if user["is_admin"] else f"You are on {len(mine)} of them."} Everything else on the
        site, the dashboard, the uploads and the roster link, follows this
        choice.</p>
      <form class="stack" method="post" action="/team/switch">{csrf_input(user)}
        <label>Team<select name="team_id">{options}</select></label>
        <button class="btn" type="submit">Switch</button>
      </form>
    </div>
  </section>"""
    else:
        switch_block = ""

    # Handing a team over. The report that wins a coach is usually built for
    # them out of their own public demos, before they have an account at all,
    # and a report they cannot own is a demo with a shelf life.
    if team is None or team["member_role"] != "owner":
        claim_block = ""
    elif team["claim_token"]:
        clink = f"{mail.SITE_URL.rstrip('/')}/claim/{esc(team['claim_token'])}"
        claim_block = f"""
  <section>
    <div class="card">
      <h3>Handover link for {esc(team["name"])}</h3>
      <p class="lede">Whoever opens this and signs in becomes the owner of
        this team. They get the demos, the match reports and the season.</p>
      <p><a href="{clink}" class="mono" style="overflow-wrap:anywhere">{clink}</a></p>
      <p class="den">It works once and then stops. <strong>You lose access
        when they accept</strong>, which is the point: it is a handover, not
        a shared login. Send it to one person, not a channel.</p>
      <form method="post" action="/claim/revoke">{csrf_input(user)}
        <button class="btn ghost" type="submit">Cancel this link</button>
      </form>
    </div>
  </section>"""
    else:
        claim_block = f"""
  <section>
    <div class="card">
      <h3>Give this team to somebody</h3>
      <p class="lede">Built {esc(team["name"])} for another coach? Make a
        one-time link that hands it over, demos and all.</p>
      <p class="den">You lose access when they accept it.</p>
      <form method="post" action="/claim/new">{csrf_input(user)}
        <button class="btn ghost" type="submit">Make a handover link</button>
      </form>
    </div>
  </section>"""

    body = f"""
  <section>
    <div class="card">
      <h3>{esc(user["name"] or "–")}</h3>
      <p class="lede">{esc(user["email"])} · {esc(user["role"])}</p>
      <p class="den">{"Team: " + esc(team["name"]) if team else "No team yet"}</p>
    </div>
  </section>
  {switch_block}
  {share_block}
  {claim_block}
  <section>
    <form method="post" action="/logout">{csrf_input(user)}
      <button class="btn ghost" type="submit">Log out</button></form>
  </section>"""
    return html_page("Account | Counterplay", banner("Account"), body, user)


# ---------------------------------------------------------------- lead form

# /api/lead is gone.
#
# It backed a "tell us about your team" form on the landing page, which was
# replaced by the signup button. The form went and the route stayed: an
# unauthenticated, unthrottled POST that inserted a row into `leads` for
# anybody who read the page source. An endpoint with no caller is not a
# feature, it is a way in. The `leads` table is left alone; it holds real rows
# from before the form was removed.


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


# ---- the icon
#
# Three files for one mark, because browsers ask for it three ways and the
# oldest way is the one that 404s silently in a tab strip:
#
#   favicon.svg          what a current browser uses; one file, any size
#   favicon.ico          what older ones request by convention, at /favicon.ico
#                        whether or not the page says so
#   apple-touch-icon.png what iOS uses when a coach saves the page to a phone
#
# Served by name rather than by mounting `site/`, because that directory also
# holds the generated league pages and the zone-naming tools, and a mount
# would put both back at addresses this app deliberately does not answer.
ICONS = {"/favicon.svg": ("favicon.svg", "image/svg+xml"),
         "/favicon.ico": ("favicon.ico", "image/x-icon"),
         "/apple-touch-icon.png": ("apple-touch-icon.png", "image/png"),
         "/icon-192.png": ("icon-192.png", "image/png"),
         "/icon-512.png": ("icon-512.png", "image/png")}

# What a phone reads when somebody saves this to a home screen: the name to
# print under the icon, which icon to draw, and what colour to paint round
# it while it opens.
#
# `display: browser` deliberately. The alternatives hide the address bar,
# which is right for an app and wrong for this one: a coach who saved a
# report should be able to see where they are, and a page arguing that every
# number is checkable should not open in a window that hides its own URL.
MANIFEST = """{
  "name": "Counterplay: match analysis for league teams",
  "short_name": "Counterplay",
  "description": "Your Counter-Strike matches, read round by round.",
  "start_url": "/",
  "scope": "/",
  "display": "browser",
  "background_color": "#141119",
  "theme_color": "#5B21B6",
  "icons": [
    {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
    {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
    {"src": "/favicon.svg", "sizes": "any", "type": "image/svg+xml"}
  ]
}"""


@app.get("/site.webmanifest", include_in_schema=False)
def webmanifest():
    return Response(MANIFEST, media_type="application/manifest+json",
                    headers={"Cache-Control": "public, max-age=86400"})


def _icon_route(path: str, name: str, kind: str):
    @app.get(path, include_in_schema=False)
    def serve(_name=name, _kind=kind):
        f = SITE / _name
        if not f.is_file():
            return Response(status_code=404)
        # A year, and the names never change. An icon that has to be
        # re-fetched on every page view is the smallest possible waste
        # repeated the most times.
        return Response(f.read_bytes(), media_type=_kind,
                        headers={"Cache-Control": "public, max-age=31536000"})
    return serve


for _p, (_n, _k) in ICONS.items():
    _icon_route(_p, _n, _k)


# ---- who visited
#
# Admin only, and the flag is given by grantadmin.py, which is deliberately
# not something a web page can do. Everyone else gets the 404 they would get
# for any address that is not theirs, rather than a 403: a page you may not
# see should not confirm it exists.
#
# There is no script on the landing page feeding this. It reads Caddy's own
# access log, which is why the privacy section did not need a word changing
# to add it. See app/traffic.py.
@app.get("/admin/traffic", response_class=HTMLResponse)
def admin_traffic(request: Request):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    if not user["is_admin"]:
        raise StarletteHTTPException(status_code=404)

    t = traffic.read(force=request.query_params.get("fresh") == "1")
    if t.get("error"):
        return html_page("Traffic | Counterplay", banner("Traffic"),
                         f'<p class="note">{esc(t["error"])}</p>', user,
                         noindex=True)

    first, last = t["covers"]
    stat = (lambda n, label: f'<div class="stat"><span class="stat-n">{n}</span>'
                             f'<span class="label">{esc(label)}</span></div>')

    # The daily series, newest last, as the trends page draws a season.
    pts = [(d[5:], real, "") for d, _v, _p, real in t["series"]]
    chart = (f'<div class="chart">{charts.trend(pts, unit="", is_pct=False)}</div>'
             if len(pts) > 1 else "")

    rows = "".join(
        f'<tr><td class="name">{esc(p)}</td>'
        f'<td class="num">{n}</td></tr>' for p, n in t["pages"])
    refs = "".join(
        f'<tr><td class="name">{esc(r)}</td><td class="num">{n}</td></tr>'
        for r, n in t["referrers"])
    if not refs:
        refs = ('<tr><td colspan="2" class="den">Nothing. Every visit was '
                'typed, pasted, or arrived without a referrer.</td></tr>')

    ok = t["signup"].get(303, 0)
    rejected = sum(n for code, n in t["signup"].items() if code != 303)

    body = f"""
  <section>
    <div class="stat-row">
      {stat(t["real_browsers"], "real browsers")}
      {stat(t["saw_home"], "opened the landing page")}
      {stat(t["went_deeper"], "got past it")}
      {stat(ok, "signups accepted")}
    </div>
    <p class="note">{esc(first or "?")} to {esc(last or "?")}, {t["days_counted"]}
      days. An address is not a person: a phone on a carrier network shares one
      with thousands, and the same reader on wifi and then on data counts
      twice. These are a floor, counted the same way every time, so they are
      worth comparing with each other and not worth quoting as a headcount.</p>
  </section>

  <section>
    <div class="sec-head"><span class="label">Per day</span>
      <h2>Real browsers</h2></div>
    <p class="lede">An address that asked for a page AND for the images on it.
      Anything that requested the HTML and nothing else was not rendering it.</p>
    {chart}
  </section>

  <section>
    <div class="sec-head"><span class="label">What reached the server</span>
      <h2>Almost none of it is a person</h2></div>
    <div class="tbl-wrap"><table>
      <thead><tr><th>Source</th><th class="num">Requests</th></tr></thead>
      <tbody>
        <tr><td class="name">Vulnerability scanners
          <span class="den">({t["scanner_addresses"]} addresses that probed for
          wordpress, .env or .git)</span></td>
          <td class="num">{t["scanner_hits"]}</td></tr>
        <tr><td class="name">Declared bots and crawlers</td>
          <td class="num">{t["declared_bots"]}</td></tr>
        <tr><td class="name">Page views by everything else</td>
          <td class="num">{t["real_views"]}</td></tr>
        <tr><td class="name"><strong>Total</strong></td>
          <td class="num"><strong>{t["requests"]}</strong></td></tr>
      </tbody></table></div>
  </section>

  <section class="grid2">
    <div>
      <div class="sec-head"><span class="label">Pages</span><h3>What they opened</h3></div>
      <div class="tbl-wrap"><table>
        <thead><tr><th>Path</th><th class="num">Views</th></tr></thead>
        <tbody>{rows}</tbody></table></div>
    </div>
    <div>
      <div class="sec-head"><span class="label">Referrers</span><h3>Where they came from</h3></div>
      <div class="tbl-wrap"><table>
        <thead><tr><th>Host</th><th class="num">Visits</th></tr></thead>
        <tbody>{refs}</tbody></table></div>
      <p class="note" style="margin-top:12px">Signup form submitted
        <strong>{ok + rejected}</strong> times: {ok} accepted,
        {rejected} rejected by validation or the honeypot.</p>
    </div>
  </section>

  <section>
    <p class="den">Read from {t["log_bytes"] // 1048576}MB of access log,
      cached until the file grows.
      <a href="/admin/traffic?fresh=1">Re-read it now</a>.
      No script on the landing page feeds this and no cookie is set for it.</p>
  </section>"""

    return html_page("Traffic | Counterplay",
                     banner("Traffic", label="Admin"), body, user, noindex=True)


# ---- the page for an address that is not here
#
# FastAPI answers an unclaimed path with `{"detail":"Not Found"}`, which is
# right for a client parsing a response and wrong for a coach who mistyped
# the address or followed a link from an email after a page moved.
#
# Anything under /api/ keeps the JSON, and so does a caller that did not ask
# for HTML, because something reading a response should not be handed a
# document. Everything else gets the same shell as the rest of the site,
# noindex, with the two links worth having from a dead end.
@app.exception_handler(StarletteHTTPException)
async def not_found(request: Request, exc: StarletteHTTPException):
    wants_html = "text/html" in (request.headers.get("accept") or "")
    if (exc.status_code != 404 or not wants_html
            or request.url.path.startswith("/api/")):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    body = """
  <section>
    <p class="lede">The address you asked for is not here. It may have moved,
      or it may never have existed; either way nothing is broken at your end.</p>
    <p style="margin-top:18px">
      <a class="btn" href="/">Back to the start</a>
      <a class="btn btn-ghost" href="/sample-report"
         style="margin-left:9px">See a sample report</a></p>
  </section>"""
    return HTMLResponse(
        page("Not found | Counterplay",
             banner("Not found", label="404"), body, noindex=True),
        status_code=404)


# ---- what a crawler is allowed to ask for
#
# Six pages on this site are public: the landing page, the sample report, the
# two legal pages and the two ways in. Everything else is behind a session or
# behind a share token, and a crawler that walks into one gets a login page
# for its trouble, which is a wasted fetch for both of us.
#
# Two entries earn their place for a reason other than tidiness. `/r/` holds
# the share links, and a capability URL in an index is not a capability any
# more; the pages already say `noindex`, and this says it a second time before
# the fetch rather than after. `/zones.html` is 6.4MB of zone-naming tool that
# nobody outside this box has any use for.
#
# A disallow is not a permission check. Everything here is also enforced in
# the handler; this only stops well-behaved crawlers from asking.
ROBOTS = """User-agent: *
Disallow: /r/
Disallow: /reset/
Disallow: /account
Disallow: /dashboard
Disallow: /team/
Disallow: /match/
Disallow: /player/
Disallow: /players
Disallow: /stats
Disallow: /trends
Disallow: /matches
Disallow: /unsubscribe
Disallow: /zones.html
Disallow: /finish-zones.html
Disallow: /nuke-zones.html
Disallow: /api/

Sitemap: https://counterplaycs.com/sitemap.xml
"""

# The public pages, listed once. No `lastmod`: a date that is not maintained
# is worse than no date, because a crawler believes it.
SITEMAP_PAGES = ("/", "/sample-report", "/signup", "/login", "/privacy", "/terms")


@app.get("/robots.txt", include_in_schema=False)
def robots_txt():
    return Response(ROBOTS, media_type="text/plain",
                    headers={"Cache-Control": "public, max-age=86400"})


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap_xml():
    urls = "".join(
        f"<url><loc>https://counterplaycs.com{p}</loc></url>"
        for p in SITEMAP_PAGES)
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
           f'{urls}</urlset>')
    return Response(xml, media_type="application/xml",
                    headers={"Cache-Control": "public, max-age=86400"})


# Map overview images, fetched by counterplay/radar.py. Absent until someone
# runs --fetch, and every drawing works without them.
if (SITE / "radars").is_dir():
    app.mount("/radars", StaticFiles(directory=SITE / "radars"), name="radars")

# The map silhouettes the chips are masked with, built by mapicons.py. Mounted
# the same way and equally optional: without them map_chip falls back to the
# radar image it used before.
if (SITE / "icons").is_dir():
    app.mount("/icons", StaticFiles(directory=SITE / "icons"), name="icons")


# The landing page's video loop and its poster frame. StaticFiles answers Range
# requests, which a <video> needs; the page also works with the directory
# missing, because the band falls back to its poster and then to nothing.
if (SITE / "media").is_dir():
    app.mount("/media", StaticFiles(directory=SITE / "media"), name="media")


# The generated league site is served by league_page above, which gives it
# addresses without .html and redirects the old ones. It is deliberately not
# mounted as static files as well: two ways to reach the same page is one way
# too many, and the mount would have kept the .html addresses alive.
