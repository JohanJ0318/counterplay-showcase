"""End-to-end smoke test. Run it against localhost, then against production.

    python -m app.smoke
    python -m app.smoke --url https://counterplaycs.com
    python -m app.smoke --demo path/to/a.dem        # also exercises upload

The point of the --url flag is that this is the SAME test both times. Local and
deployed differ in exactly the places that break a web app — proxy body limits,
request timeouts, HTTPS-only cookies, a worker that is not running — and those
differences are invisible until something real goes through them. Running one
script against both is how you find out before a coach does.

It creates a throwaway account, exercises the whole flow, and prints what it
made so you can delete it. It never touches existing data, and it never asserts
on a demo you did not give it.
"""
from __future__ import annotations

import argparse
import http.cookiejar as cookiejar
import io
import json
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PASSWORD = "smoke-test-password"


class Result:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.notes: list[str] = []

    def check(self, ok: bool, label: str, detail: str = "") -> bool:
        if ok:
            self.passed += 1
            print(f"  PASS  {label}")
        else:
            self.failed += 1
            print(f"  FAIL  {label}" + (f"\n          {detail}" if detail else ""))
        return ok

    def note(self, text: str):
        self.notes.append(text)
        print(f"  note  {text}")


class Client:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.jar = cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar))

    def get(self, path: str):
        try:
            r = self.opener.open(self.base + path, timeout=60)
            return r.status, r.read().decode("utf-8", "replace"), r.url
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace"), e.url

    def post(self, path: str, fields: dict):
        data = urllib.parse.urlencode(fields).encode()
        try:
            r = self.opener.open(urllib.request.Request(self.base + path, data=data),
                                 timeout=120)
            return r.status, r.read().decode("utf-8", "replace"), r.url
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace"), e.url

    def upload(self, path: str, csrf: str, filename: str, blob: bytes):
        b = "----smoke" + secrets.token_hex(8)
        out = io.BytesIO()
        out.write(f"--{b}\r\nContent-Disposition: form-data; name=\"csrf\"\r\n\r\n"
                  f"{csrf}\r\n".encode())
        out.write(f"--{b}\r\nContent-Disposition: form-data; name=\"demo\"; "
                  f"filename=\"{filename}\"\r\n"
                  f"Content-Type: application/octet-stream\r\n\r\n".encode())
        out.write(blob)
        out.write(f"\r\n--{b}--\r\n".encode())
        req = urllib.request.Request(
            self.base + path, data=out.getvalue(),
            headers={"Content-Type": f"multipart/form-data; boundary={b}"})
        try:
            r = self.opener.open(req, timeout=900)
            return r.status, r.url
        except urllib.error.HTTPError as e:
            return e.code, e.url

    def secure_cookie(self) -> bool | None:
        """Whether the session cookie is marked Secure. None if there is none."""
        for c in self.jar:
            if c.name == "cp_session":
                return bool(c.secure)
        return None


def csrf_from(html: str) -> str | None:
    m = re.search(r'name="csrf" value="([^"]+)"', html)
    return m.group(1) if m else None


def run(base: str, demo: Path | None) -> int:
    r = Result()
    stamp = secrets.token_hex(4)
    email = f"smoke-{stamp}@example.com"
    team = f"Smoke Test {stamp}"
    https = base.startswith("https://")

    print(f"\nCounterplay smoke test  ->  {base}\n")

    # --- public pages -------------------------------------------------------
    print("PUBLIC PAGES")
    a = Client(base)
    for label, path in [("landing", "/"), ("signup", "/signup"),
                        ("login", "/login"), ("sample report", "/sample-report.html"),
                        ("league site", "/league/")]:
        code, _, _ = a.get(path)
        r.check(code == 200, f"{label} serves", f"got {code}")
    code, _, _ = a.get("/dashboard")
    r.check(code in (200, 303) , "dashboard reachable when signed out (redirects)")

    # --- signup -------------------------------------------------------------
    print("\nSIGNUP AND SESSION")
    code, body, url = a.post("/signup", dict(
        team=team, league="NECC", role="coach", name="Smoke Test",
        email=email, password=PASSWORD))
    if not r.check(code == 200 and "/dashboard" in url,
                   "signup creates an account and signs in", f"got {code} {url}"):
        print("\n  Signup failed — nothing below can run. Stopping.")
        return 1
    r.note(f"created account {email} / team {team!r} — delete it when you are done")

    secure = a.secure_cookie()
    if https:
        r.check(secure is True, "session cookie is marked Secure over HTTPS",
                "COUNTERPLAY_INSECURE_COOKIES is set in production — remove it")
    else:
        r.check(secure is False, "session cookie is not Secure over plain HTTP",
                "cookies are Secure but this is http:// — you would not stay logged in")

    code, body, _ = a.post("/signup", dict(
        team="Dup", league="NECC", role="coach", name="Dup",
        email=email.upper(), password=PASSWORD))
    r.check(code == 400 and "already an account" in body,
            "the same email cannot register twice, in any case")
    code, _, _ = a.post("/signup", dict(team="X", league="NECC", role="coach",
                                        name="X", email=f"x-{stamp}@example.com",
                                        password="short"))
    r.check(code == 400, "a short password is refused")

    # --- signed-in pages ----------------------------------------------------
    print("\nSIGNED-IN PAGES")
    pages = {}
    for label, path in [("dashboard", "/dashboard"), ("players", "/players"),
                        ("team stats", "/stats"), ("account", "/account")]:
        code, html, _ = a.get(path)
        pages[label] = html
        r.check(code == 200, f"{label} serves", f"got {code}")
    r.check("Pricing" not in pages.get("dashboard", ""),
            "no pricing anywhere in the signed-in nav")
    code, _, _ = a.get("/pricing")
    r.check(code == 404, "the pricing page is gone", f"got {code}")

    # --- CSRF ---------------------------------------------------------------
    print("\nCSRF")
    token = csrf_from(pages["dashboard"])
    if r.check(bool(token), "the dashboard carries a CSRF token"):
        code, _, _ = a.post("/logout", dict(csrf="wrong-token"))
        r.check(code == 403, "logout with a bad token is refused", f"got {code}")
        code, html, _ = a.get("/dashboard")
        r.check(code == 200 and "Dashboard" in html,
                "the session survives a refused logout")

    # --- isolation ----------------------------------------------------------
    print("\nTEAM ISOLATION")
    slug = re.search(r'href="/team/([a-z0-9-]+)"', pages["dashboard"])
    b = Client(base)
    b.post("/signup", dict(team=f"Rival {stamp}", league="ECAC", role="coach",
                           name="Rival", email=f"rival-{stamp}@example.com",
                           password=PASSWORD))
    r.note(f"created second account rival-{stamp}@example.com — delete it too")
    if slug:
        code, _, _ = b.get(f"/team/{slug.group(1)}")
        r.check(code == 403, "another team's page is refused", f"got {code}")
    else:
        r.note("no team link found on the dashboard, skipped the isolation check")

    # --- upload -------------------------------------------------------------
    print("\nUPLOAD")
    if token:
        code, _ = a.upload("/upload", token, "not-a-demo.txt", b"hello")
        r.check(code == 400, "a non-demo file is refused", f"got {code}")
        code, _ = a.upload("/upload", "wrong-token", "x.dem", b"HL2DEMO" + b"\0" * 200)
        r.check(code == 403, "upload with a bad CSRF token is refused", f"got {code}")

        if demo is not None:
            size = demo.stat().st_size
            print(f"        uploading {demo.name} ({size/1e6:.0f} MB) ...")
            started = time.time()
            code, url = a.upload("/upload", token, demo.name, demo.read_bytes())
            took = time.time() - started
            ok = r.check("/team/" in url or code == 200,
                         f"a real demo uploads ({took:.0f}s)", f"got {code} {url}")
            if ok:
                r.note("upload accepted — now check the worker picks it up:")
                r.note("  python -m app.worker --once     (locally)")
                r.note("  journalctl -u counterplay-worker -f     (deployed)")
        else:
            r.note("no --demo given, so the real upload path was not exercised")
            r.note("this is the single most likely thing to break in production")

    # --- lead form ----------------------------------------------------------
    print("\nLANDING PAGE FORM")
    req = urllib.request.Request(
        base + "/api/lead",
        data=json.dumps(dict(team="Smoke", name="Smoke", email=f"lead-{stamp}@example.com",
                             league="NECC", role="coach", note="smoke test")).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            r.check(json.loads(resp.read()).get("ok") is True, "the lead form accepts a lead")
    except Exception as e:
        r.check(False, "the lead form accepts a lead", str(e))

    # --- summary ------------------------------------------------------------
    print(f"\n{'=' * 58}")
    print(f"{r.passed} passed, {r.failed} failed")
    if r.failed:
        print("\nSomething above is broken. Do not send the link to a coach yet.")
    else:
        print("\nEverything checked out.")
    if r.notes:
        print("\nLeft behind (clean these up):")
        for n in r.notes:
            print(f"  {n}")
    return 1 if r.failed else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Smoke-test a Counterplay install")
    ap.add_argument("--url", default="http://127.0.0.1:8000",
                    help="where to test; use your real domain after deploying")
    ap.add_argument("--demo", type=str,
                    help="a .dem or .dem.zst to actually upload — the one check "
                         "that most often fails only in production")
    args = ap.parse_args()
    demo = Path(args.demo) if args.demo else None
    if demo is not None and not demo.exists():
        print(f"no such file: {demo}")
        return 2
    return run(args.url, demo)


if __name__ == "__main__":
    sys.exit(main())
