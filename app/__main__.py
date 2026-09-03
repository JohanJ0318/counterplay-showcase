"""python -m app  —  run the development server."""
import os
import uvicorn

if __name__ == "__main__":
    # Local runs are plain HTTP, so the Secure cookie flag has to come off or
    # no session survives the redirect after login. Never set this in production.
    os.environ.setdefault("COUNTERPLAY_INSECURE_COOKIES", "1")
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
