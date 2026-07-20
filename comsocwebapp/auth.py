"""Authentication, registration and invitation tokens.

Access to a setting is mediated by a row in ``invitations``:

* a **personal** token (``is_generic = 0``) is consumed the first time it is
  redeemed -- ``is_used`` flips to 1 and the link dies;
* a **generic** token (``is_generic = 1``) may be redeemed by many people, so
  double-participation is prevented by the unique index on ``users.email``
  instead of by the token itself.
"""

from __future__ import annotations

import functools
import secrets

from flask import (
    Blueprint, flash, g, redirect, render_template, request, session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from . import db

bp = Blueprint("auth", __name__, url_prefix="/auth")

TOKEN_BYTES = 24  # 24 random bytes -> 32 URL-safe characters.


# --------------------------------------------------------------------------
# Token generation / redemption
# --------------------------------------------------------------------------

def generate_token() -> str:
    """Return a fresh, URL-safe, cryptographically random invitation code."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def create_invitation(setting_id: int, is_generic: bool = False) -> str:
    """Create one invitation row for ``setting_id`` and return its token."""
    token = generate_token()
    db.execute(
        "INSERT INTO invitations (setting_id, token, is_generic, is_used)"
        " VALUES (?, ?, ?, 0)",
        (setting_id, token, 1 if is_generic else 0),
    )
    return token


def create_invitations(setting_id: int, count: int, is_generic: bool = False) -> list[str]:
    """Create ``count`` invitations at once (one per invited participant)."""
    return [create_invitation(setting_id, is_generic) for _ in range(count)]


def find_invitation(token: str) -> dict | None:
    """Return the invitation row for ``token`` if it is still redeemable."""
    invitation = db.query_one(
        "SELECT id, setting_id, token, is_generic, is_used"
        " FROM invitations WHERE token = ?",
        (token,),
    )
    if invitation is None:
        return None
    if invitation["is_generic"] == 0 and invitation["is_used"] == 1:
        return None
    return invitation


def consume_invitation(invitation: dict) -> None:
    """Mark a personal invitation as spent.  Generic ones stay reusable."""
    if invitation["is_generic"] == 0:
        db.execute("UPDATE invitations SET is_used = 1 WHERE id = ?", (invitation["id"],))


# --------------------------------------------------------------------------
# User creation
# --------------------------------------------------------------------------

def create_user(email: str | None, password: str | None, is_admin: bool = False,
                is_dummy: bool = False) -> int:
    """Insert a user and return its id.

    Dummy users are created with ``email = None`` and no password: they exist
    only to carry simulated preferences and can never log in.
    """
    return db.insert_returning_id(
        "INSERT INTO users (email, password_hash, is_admin, is_dummy, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (
            email,
            generate_password_hash(password) if password else None,
            1 if is_admin else 0,
            1 if is_dummy else 0,
            db.utcnow_text(),
        ),
    )


def find_user_by_email(email: str) -> dict | None:
    return db.query_one(
        "SELECT id, email, password_hash, is_admin, is_dummy FROM users WHERE email = ?",
        (email,),
    )


# --------------------------------------------------------------------------
# Session plumbing
# --------------------------------------------------------------------------

@bp.before_app_request
def load_logged_in_user() -> None:
    """Populate ``g.user`` from the session cookie on every request."""
    user_id = session.get("user_id")
    g.user = None if user_id is None else db.query_one(
        "SELECT id, email, is_admin, is_dummy FROM users WHERE id = ?", (user_id,)
    )


def login_required(view):
    """Redirect anonymous visitors to the login page."""
    @functools.wraps(view)
    def wrapped(**kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.path))
        return view(**kwargs)
    return wrapped


def admin_required(view):
    """Allow only administrators through."""
    @functools.wraps(view)
    def wrapped(**kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.path))
        if not g.user["is_admin"]:
            flash("Administrator access is required for that page.", "error")
            return redirect(url_for("participant.index")), 403
        return view(**kwargs)
    return wrapped


# --------------------------------------------------------------------------
# Views
# --------------------------------------------------------------------------

@bp.route("/register", methods=("GET", "POST"))
def register():
    """Register a participant, redeeming the invitation token from the link."""
    token = request.values.get("token", "")
    invitation = find_invitation(token) if token else None

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        error = None

        if invitation is None:
            error = "This invitation link is invalid or has already been used."
        elif not email:
            error = "Email is required."
        elif not password:
            error = "Password is required."
        elif find_user_by_email(email) is not None:
            # On a generic link this is also the double-voting guard.
            error = "That email address is already registered."

        if error is None:
            user_id = create_user(email, password)
            consume_invitation(invitation)
            session.clear()
            session["user_id"] = user_id
            session["setting_id"] = invitation["setting_id"]
            return redirect(url_for("participant.ballot", setting_id=invitation["setting_id"]))
        flash(error, "error")

    return render_template("auth/register.html", token=token, invitation=invitation)


@bp.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = find_user_by_email(email)

        # One generic message for both cases, so the form cannot be used to
        # enumerate registered email addresses.
        if user is None or not user["password_hash"] \
                or not check_password_hash(user["password_hash"], password):
            flash("Incorrect email or password.", "error")
        else:
            session.clear()
            session["user_id"] = user["id"]
            target = request.args.get("next")
            if target and target.startswith("/"):  # never redirect off-site
                return redirect(target)
            return redirect(url_for("admin.dashboard") if user["is_admin"]
                            else url_for("participant.index"))

    return render_template("auth/login.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/invite/<token>")
def invite(token: str):
    """Entry point for an invitation link: register, or vote if already known."""
    invitation = find_invitation(token)
    if invitation is None:
        flash("This invitation link is invalid or has already been used.", "error")
        return render_template("auth/login.html"), 404
    if g.user is not None:
        consume_invitation(invitation)
        return redirect(url_for("participant.ballot", setting_id=invitation["setting_id"]))
    return redirect(url_for("auth.register", token=token))
