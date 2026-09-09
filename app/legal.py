"""Privacy policy, terms, and the unsubscribe an outreach email needs.

WHY THIS EXISTS BEFORE THERE IS A SECOND USER
---------------------------------------------
`player_rounds` holds Steam IDs and in-game names for over twenty-five
thousand players, almost none of whom signed up for anything. They appear
because they were in a demo somebody uploaded. That is defensible, it is what
every Counter-Strike analytics tool does, and it is not defensible in silence:
a person has to be able to read what is held about them and ask for it to go.

The landing page already promises "ask us to delete your team's data and we
delete it". A promise made on a marketing page and nowhere else is the kind of
thing that is fine right up until it is not.

THESE ARE DRAFTS, AND THE PAGE SAYS SO
--------------------------------------
Written to be accurate about what this system actually does, which is the part
a lawyer cannot do for you. They are not legal advice and have not been
reviewed by anybody qualified. The banner at the top of each page says exactly
that, and it disappears once COUNTERPLAY_LEGAL_REVIEWED is set.

ONE CONTACT DETAIL, NOT THREE
-----------------------------
An email address, and that is all. An earlier version also published an
operator name and a postal address and told the reader the pages were
incomplete without them. Both were wrong:

  * No US law requires a solo operator to publish a legal name in a privacy
    policy. California's CalOPPA wants the policy and a contact method, not an
    identity. A name is a trust decision, not a legal one.
  * The postal address requirement is CAN-SPAM, and it applies to commercial
    EMAIL rather than to a website. It belongs in the footer of the outreach
    message, which is where `deploy/outreach-email.md` puts it. Password
    resets are transactional and exempt from it altogether.

What is left is the one detail that makes the promise on these pages mean
anything: a way to ask. It comes from the environment so that the published
address can be changed without a deploy.
"""
from __future__ import annotations

import os

from .theme import esc

EMAIL = os.environ.get("COUNTERPLAY_LEGAL_EMAIL", "")
REVIEWED = os.environ.get("COUNTERPLAY_LEGAL_REVIEWED", "") == "1"

UPDATED = "September 2026"


def complete() -> bool:
    """Whether these pages can do their job, which needs one thing."""
    return bool(EMAIL)


def _draft_banner() -> str:
    if complete() and REVIEWED:
        return ""
    what = ("" if EMAIL else
            " It also has no contact address configured, so nobody can act on it.")
    return (f'<p class="warn"><strong>Draft.</strong> This page describes what '
            f'the system actually does and has not been reviewed by a lawyer.'
            f'{esc(what)}</p>')


def _contact_block() -> str:
    """The address to write to, and nothing else.

    An earlier version printed a name and a postal address beside it. Neither
    is required of these pages, and a home address published on a page that
    scrapers read is permanent in a way a person cannot take back.
    """
    if not EMAIL:
        return ('<p class="den">No contact address is configured on this '
                'server yet.</p>')
    return (f'<p class="den"><a href="mailto:{esc(EMAIL)}">{esc(EMAIL)}</a>'
            f'</p>')


def privacy_body() -> str:
    return f"""
  <section>
    {_draft_banner()}
    <p class="lede">Last updated {UPDATED}. Plain English, because a policy
      nobody reads protects nobody.</p>
  </section>

  <section>
    <div class="sec-head"><span class="label">If you have an account</span>
      <h2>What we hold about you</h2></div>
    <div class="card">
      <p>Your email address, the name you gave, your team name and league, a
        scrambled version of your password that cannot be turned back into it,
        and the dates you signed up and last signed in.</p>
      <p>The match demos you upload, and everything we work out from them:
        rounds, kills, positions, buys and the reports on this site.</p>
      <p>We do not use trackers, we do not run advertising, and we do not sell
        anything to anybody.</p>
    </div>
  </section>

  <section>
    <div class="sec-head"><span class="label">If you have never heard of us</span>
      <h2>Why you might be in here anyway</h2></div>
    <div class="card">
      <p>A Counter-Strike demo records everyone who played the match. When a
        coach uploads one, it contains their opponents as well as their own
        team. So this system holds the Steam ID and in-game name of every
        player in every uploaded match, including yours if you played against
        somebody who uses Counterplay.</p>
      <p>What we do with it: build the numbers in that match's report, and
        contribute to anonymous league-wide averages. What we do not do:
        build a profile page about you, show your name to anyone who was not
        in that match, or sell or publish the demo file.</p>
      <p><strong>You can have it removed.</strong> Email us with your Steam ID
        and we will delete every row that refers to you. We do not require an
        account, a reason, or anything else.</p>
    </div>
  </section>

  <section>
    <div class="sec-head"><span class="label">Where it lives</span>
      <h2>Storage, sharing and how long we keep it</h2></div>
    <div class="card">
      <p>Everything sits on one server rented from Hetzner Online GmbH in
        Nuremberg, Germany, and in backups of that server. Nobody else
        processes it. There is no analytics provider, no advertising network
        and no third-party database.</p>
      <p>Match data is kept while it is useful to the team that uploaded it.
        Demo files are kept so that reports can be rebuilt when the parser
        improves. Ask us to delete a team's data and we delete the rows and
        the files, which is the promise the front page makes.</p>
      <p>If you have an account you can also ask for a copy of everything we
        hold about you, and we will send it.</p>
    </div>
  </section>

  <section>
    <div class="sec-head"><span class="label">Getting in touch</span>
      <h2>Contact</h2></div>
    <div class="card">
      <p>Deletion requests, access requests, corrections, or anything else
        about this page:</p>
      {_contact_block()}
    </div>
  </section>"""


def terms_body() -> str:
    return f"""
  <section>
    {_draft_banner()}
    <p class="lede">Last updated {UPDATED}. Counterplay is free for the
      collegiate season and is run by one person, which is the honest context
      for everything below.</p>
  </section>

  <section>
    <div class="sec-head"><span class="label">The deal</span>
      <h2>What you get and what it costs</h2></div>
    <div class="card">
      <p>Upload your team's match demos and get reports back. Free for this
        season, with no card and no trial that turns into a charge. If that
        ever changes we will say so before it does, not after.</p>
      <p>You keep your data. We do not claim ownership of your demos or your
        reports, and we do not show one team's report to another team.</p>
    </div>
  </section>

  <section>
    <div class="sec-head"><span class="label">What we ask</span>
      <h2>Using it reasonably</h2></div>
    <div class="card">
      <p>Upload demos from matches you took part in or coached. Do not upload
        somebody else's private scrims to look at their team.</p>
      <p>One account per person. Do not try to break into other teams' data,
        and do not hammer the server hard enough to take it down for everyone
        else.</p>
      <p>We can close an account that does those things. We would rather send
        an email first, and we will.</p>
    </div>
  </section>

  <section>
    <div class="sec-head"><span class="label">The unglamorous part</span>
      <h2>No warranty, and the limits of that</h2></div>
    <div class="card">
      <p>The numbers here are arithmetic over what the demo recorded, and the
        product is deliberately built so you can check any of them. They are
        still produced by software written by one person, and software has
        bugs. Do not bet money on them.</p>
      <p>The service is provided as it is, with no guarantee that it will be
        available, correct, or running next month. We are not liable for
        losses arising from using it. Nothing here limits any right you have
        that cannot be limited by agreement.</p>
      <p>Counterplay is not affiliated with Valve, FACEIT, ESEA, NECC or any
        collegiate association.</p>
    </div>
  </section>

  <section>
    <div class="sec-head"><span class="label">Getting in touch</span>
      <h2>Contact</h2></div>
    <div class="card">{_contact_block()}</div>
  </section>"""


def unsubscribed_body(email: str, already: bool) -> str:
    line = ("That address was already on the do-not-email list."
            if already else "Done. That address will not be emailed again.")
    return f"""
  <section>
    <div class="card">
      <p class="lede">{esc(line)}</p>
      <p class="den">{esc(email)}</p>
      <p class="den">This only covers outreach. If you have an account, it
        still gets the emails it needs to work, like a password reset you
        asked for.</p>
      <p class="den"><a href="/">Back to the site</a></p>
    </div>
  </section>"""


def unsubscribe_form(email: str = "", error: str = "") -> str:
    warn = f'<p class="warn">{esc(error)}</p>' if error else ""
    return f"""
  <section>
    <div class="card">
      {warn}
      <p class="lede">Put in the address you were emailed at and we will stop.
        No account needed and no reason required.</p>
      <form class="stack" method="post" action="/unsubscribe">
        <label>Email
          <input type="email" name="email" value="{esc(email)}"
                 autocomplete="email" required></label>
        <button type="submit">Stop emailing this address</button>
      </form>
    </div>
  </section>"""
