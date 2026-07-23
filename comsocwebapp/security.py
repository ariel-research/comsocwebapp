"""Dependency-free CSRF protection for the built-in forms.

Every state-changing request in this package is a POST from a rendered form, so
one synchroniser token per session is enough: it is stored in the (signed,
HttpOnly, SameSite=Lax) session cookie, rendered into each form by the
``csrf_token()`` template global, and compared in constant time before any POST
view runs.

Applications that already use Flask-WTF can skip this by passing
``WTF_CSRF_ENABLED``-style protection of their own; set ``CSRF_ENABLED = False``
in the config to disable the check here.
"""

import secrets
from hmac import compare_digest

from flask import abort, current_app, request, session

__all__ = ["csrf_token", "init_app"]

_SESSION_KEY = "_csrf_token"


def csrf_token() -> str:
    """Return this session's token, minting one on first use."""
    if _SESSION_KEY not in session:
        session[_SESSION_KEY] = secrets.token_urlsafe(32)
    return session[_SESSION_KEY]


def init_app(app) -> None:
    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def check_csrf():
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return
        if not current_app.config.get("CSRF_ENABLED", True):
            return
        expected = session.get(_SESSION_KEY)
        submitted = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if not expected or not submitted or not compare_digest(expected, submitted):
            abort(400, "Missing or invalid CSRF token. Please reload the form.")
