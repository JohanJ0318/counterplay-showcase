#!/usr/bin/env bash
# The handover, over real HTTP, against a throwaway database.
#
# Row-level tests already cover the rules. This covers the part they cannot:
# that the routes are wired, the CSRF token round-trips, the GET does not
# perform the handover, and the POST does.
set -u
PORT=8097
ROOT="C:/Users/Johan/counterplay"
TMP="C:/Users/Johan/AppData/Local/Temp/claude/C--Users-Johan-counterplay/99c781a0-a946-4a00-93b6-d8fb0b00b4d4/scratchpad/e2e"
rm -rf "$TMP"; mkdir -p "$TMP"
BASE="http://127.0.0.1:$PORT"

cd "$ROOT" || exit 1
export COUNTERPLAY_DB="$TMP/e2e.db"
export COUNTERPLAY_INSECURE_COOKIES=1   # http on localhost only, never prod
export COUNTERPLAY_SITE_URL="$BASE"

python -m uvicorn app.main:app --host 127.0.0.1 --port $PORT --log-level warning \
  > "$TMP/server.log" 2>&1 &
UVI=$!

cleanup() {
  kill "$UVI" 2>/dev/null
  # CLAUDE.md: pkill does not reliably kill uvicorn here. Find the listener.
  PID=$(netstat -ano | grep ":$PORT " | grep LISTENING | awk '{print $5}' | head -1)
  [ -n "${PID:-}" ] && taskkill //PID "$PID" //F >/dev/null 2>&1
}
trap cleanup EXIT

for _ in $(seq 1 40); do
  curl -s -o /dev/null "$BASE/" && break
  sleep 0.5
done

say() { printf '%-52s %s\n' "$1" "$2"; }

# ---------------------------------------------------------------- two accounts
A="$TMP/a.jar"; B="$TMP/b.jar"
curl -s -c "$A" -b "$A" -o /dev/null -X POST "$BASE/signup" \
  -d "team=Builder Team&league=NECC&role=coach&email=builder@example.edu&password=correct-horse-battery&homepage="
curl -s -c "$B" -b "$B" -o /dev/null -X POST "$BASE/signup" \
  -d "team=Coach Own Team&league=NECC&role=coach&email=coach@example.edu&password=correct-horse-battery&homepage="

ACC_A=$(curl -s -b "$A" "$BASE/account")
say "builder signed up and reached /account" "$(echo "$ACC_A" | grep -c 'Builder Team')"

# ------------------------------------------------------------- make a handover
CSRF=$(echo "$ACC_A" | grep -o 'name="csrf" value="[^"]*"' | head -1 | sed 's/.*value="//;s/"//')
say "csrf token present on /account" "$([ -n "$CSRF" ] && echo yes || echo NO)"

curl -s -b "$A" -c "$A" -o /dev/null -X POST "$BASE/claim/new" -d "csrf=$CSRF"
ACC_A=$(curl -s -b "$A" "$BASE/account")
TOKEN=$(echo "$ACC_A" | grep -o "$BASE/claim/[A-Za-z0-9_-]*" | head -1 | sed "s|$BASE/claim/||")
say "handover link created" "$([ -n "$TOKEN" ] && echo yes || echo NO)"

# ------------------------------------------------- a GET must NOT hand it over
curl -s -o /dev/null "$BASE/claim/$TOKEN"                    # anonymous
curl -s -b "$B" -o /dev/null "$BASE/claim/$TOKEN"            # signed in, GET only
STILL=$(curl -s -b "$A" "$BASE/account" | grep -c 'Builder Team')
say "after two GETs, builder still owns it" "$STILL"

ANON=$(curl -s "$BASE/claim/$TOKEN")
say "anonymous claim page asks you to sign in" "$(echo "$ANON" | grep -ci 'make an account')"

# --------------------------------------------------------------- now accept it
PAGE_B=$(curl -s -b "$B" "$BASE/claim/$TOKEN")
CSRF_B=$(echo "$PAGE_B" | grep -o 'name="csrf" value="[^"]*"' | head -1 | sed 's/.*value="//;s/"//')
say "confirm page warns about losing access" "$(echo "$PAGE_B" | grep -ci 'loses access')"
curl -s -b "$B" -c "$B" -o /dev/null -X POST "$BASE/claim/$TOKEN" -d "csrf=$CSRF_B"

say "coach now sees Builder Team" "$(curl -s -b "$B" "$BASE/account" | grep -c 'Builder Team')"
say "builder no longer sees Builder Team" "$(curl -s -b "$A" "$BASE/account" | grep -c 'Builder Team')"
say "token is spent (404 on reuse)" "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/claim/$TOKEN")"

# --------------------------------------------------------- everything else 200
for p in / /login /signup /sample-report /privacy /terms /robots.txt /sitemap.xml; do
  say "GET $p" "$(curl -s -o /dev/null -w '%{http_code}' "$BASE$p")"
done
for p in /dashboard /account /matches /players /trends /stats /upload; do
  say "GET $p (signed in)" "$(curl -s -b "$B" -o /dev/null -w '%{http_code}' "$BASE$p")"
done
say "GET /admin/traffic as a normal user" "$(curl -s -b "$B" -o /dev/null -w '%{http_code}' "$BASE/admin/traffic")"
say "GET /api/lead (should be 404)" "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/lead")"

echo
echo "--- server errors, if any ---"
grep -iE "traceback|error|exception" "$TMP/server.log" | head -5 || echo "none"
