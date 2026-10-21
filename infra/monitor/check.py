"""The uptime check, run on AWS Lambda every five minutes (infra/monitor.tf).

Fetches three addresses and publishes one number to CloudWatch: how many
failed. The alarm on that number sends the email, so a two-hour outage is
one email when it starts and one when it ends, not twenty-four. If this
function itself breaks, no number arrives and the alarm treats that as a
failure too.

/health is the check only this system needs: the worker can die while every
page still loads. It answers 503 when the worker has not looped for 30
minutes (STALE_AFTER in app/main.py).

Standard library and boto3 only, both in the Lambda runtime, so there is
nothing to package.
"""
import time
import urllib.error
import urllib.request

SITE = "https://counterplaycs.com"
PATHS = ("/", "/sample-report", "/health")
TIMEOUT = 10      # seconds before a request counts as down
SLOW = 5          # seconds before an answer counts as too slow

# "uptime" is in traffic.DECLARED_BOT, so /admin/traffic does not count these
# 8,640 requests a month as visitors. tests/test_health.py guards it.
USER_AGENT = "counterplay-uptime/1.0"


def check(path: str) -> str | None:
    """None if the page is fine, else a short reason."""
    # Ask for gzip as a browser does. Uncompressed, the sample report is 237KB
    # and its download time measured the line, not the site; the body is only
    # read to the end, never decoded, so nothing needs unpacking.
    req = urllib.request.Request(SITE + path, headers={
        "User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        status = e.code
    except Exception as e:                      # DNS, TLS, refused, timeout
        return f"{path}: {type(e).__name__}: {e}"
    took = time.monotonic() - started
    if status != 200:
        return f"{path}: HTTP {status}"
    if took > SLOW:
        return f"{path}: slow, {took:.1f}s"
    return None


def handler(event, context):
    import boto3
    problems = [p for p in (check(path) for path in PATHS) if p]
    for p in problems:
        print("FAIL", p)                         # lands in CloudWatch Logs
    if not problems:
        print("ok")
    boto3.client("cloudwatch").put_metric_data(
        Namespace="Counterplay",
        MetricData=[{"MetricName": "FailedChecks", "Value": len(problems),
                     "Unit": "Count"}])
    return {"failed": problems}
