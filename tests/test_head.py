"""HEAD answers like the GET it asks about, with no body.

Uptime monitors and link checkers send HEAD. FastAPI refused it on every
page (405), so a monitor pointed at the site read it as down. Driven here as
an ASGI server would drive it, because TestClient needs a package this
machine does not have.
"""
import asyncio

from app.main import HeadAsGet


def _run(method):
    seen = {}

    async def inner(scope, receive, send):
        seen["method"] = scope["method"]
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-length", b"5")]})
        await send({"type": "http.response.body", "body": b"hello"})

    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request", "body": b""}

    scope = {"type": "http", "method": method, "path": "/"}
    asyncio.run(HeadAsGet(inner)(scope, receive, send))
    return seen["method"], sent


def test_head_runs_the_get_and_drops_the_body():
    method, sent = _run("HEAD")
    assert method == "GET"
    assert sent[0]["status"] == 200
    assert dict(sent[0]["headers"])[b"content-length"] == b"5"
    assert sent[1]["body"] == b""


def test_get_is_untouched():
    method, sent = _run("GET")
    assert method == "GET"
    assert sent[1]["body"] == b"hello"


def test_post_is_never_turned_into_anything():
    method, _ = _run("POST")
    assert method == "POST"
