"""Registration and login through Google, GitHub or ORCID.

The feature is entirely optional and degrades quietly:

* if `Authlib <https://authlib.org/>`_ is not installed, or
* if a provider has no client id / secret in the configuration,

then that provider simply does not appear on the login page and its route
returns a clear error.  A deployment that only wants email + password needs to
do nothing at all.

Configuration -- per provider, from the environment or ``app.config``::

    OAUTH_GOOGLE_CLIENT_ID / OAUTH_GOOGLE_CLIENT_SECRET
    OAUTH_GITHUB_CLIENT_ID / OAUTH_GITHUB_CLIENT_SECRET
    OAUTH_ORCID_CLIENT_ID  / OAUTH_ORCID_CLIENT_SECRET

The redirect URI to register with the provider is::

    https://<your-host>/auth/oauth/<provider>/callback

Identity model: a provider account is keyed on ``(auth_provider,
auth_subject)`` in the ``users`` table, *not* on the email address.  ORCID does
not release an email under the ``/authenticate`` scope, and GitHub users may
keep theirs private, so the provider's own stable subject id is the only
identifier we can always rely on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

__all__ = [
    "PROVIDERS", "Provider", "authlib_available", "configured_providers",
    "get_client", "fetch_identity", "init_app",
]


@dataclass(frozen=True)
class Provider:
    """Everything needed to talk to one OAuth provider."""
    name: str
    label: str
    #: Passed straight to Authlib's ``oauth.register()``.
    register_kwargs: dict[str, Any]
    #: token + client -> (subject, email, display_name)
    identity: Callable[[Any, Any], tuple[str, str | None, str | None]]


# --------------------------------------------------------------------------
# Per-provider identity extraction
# --------------------------------------------------------------------------

def _google_identity(client, token):
    """Google is a full OpenID Connect provider: the id_token carries both the
    stable subject and a verified email, and Authlib has already parsed it."""
    info = token.get("userinfo") or client.userinfo(token=token)
    return str(info["sub"]), info.get("email"), info.get("name")


def _github_identity(client, token):
    """GitHub is plain OAuth 2, so the profile needs a second call -- and a
    third when the user keeps their address private."""
    profile = client.get("user", token=token).json()
    email = profile.get("email")
    if not email:
        addresses = client.get("user/emails", token=token).json()
        primary = next(
            (a for a in addresses if a.get("primary") and a.get("verified")),
            next((a for a in addresses if a.get("verified")), None),
        )
        email = primary["email"] if primary else None
    return str(profile["id"]), email, profile.get("name") or profile.get("login")


def _orcid_identity(client, token):
    """ORCID returns the researcher's iD and name in the token response itself.

    The ``/authenticate`` scope grants no access to the email address, which is
    exactly why users are keyed on the subject id rather than on their email.
    """
    return str(token["orcid"]), None, token.get("name")


PROVIDERS: dict[str, Provider] = {
    "google": Provider(
        name="google",
        label="Google",
        register_kwargs={
            "server_metadata_url":
                "https://accounts.google.com/.well-known/openid-configuration",
            "client_kwargs": {"scope": "openid email profile"},
        },
        identity=_google_identity,
    ),
    "github": Provider(
        name="github",
        label="GitHub",
        register_kwargs={
            "access_token_url": "https://github.com/login/oauth/access_token",
            "authorize_url": "https://github.com/login/oauth/authorize",
            "api_base_url": "https://api.github.com/",
            "client_kwargs": {"scope": "read:user user:email"},
        },
        identity=_github_identity,
    ),
    "orcid": Provider(
        name="orcid",
        label="ORCID",
        register_kwargs={
            "access_token_url": "https://orcid.org/oauth/token",
            "authorize_url": "https://orcid.org/oauth/authorize",
            "api_base_url": "https://pub.orcid.org/v3.0/",
            "client_kwargs": {"scope": "/authenticate"},
        },
        identity=_orcid_identity,
    ),
}


# --------------------------------------------------------------------------
# Availability
# --------------------------------------------------------------------------

def authlib_available() -> bool:
    try:
        import authlib  # noqa: F401
    except ImportError:
        return False
    return True


def _credentials(config, name: str) -> tuple[str | None, str | None]:
    prefix = f"OAUTH_{name.upper()}"
    return config.get(f"{prefix}_CLIENT_ID"), config.get(f"{prefix}_CLIENT_SECRET")


def configured_providers(app=None) -> list[Provider]:
    """The providers this deployment can actually offer, in display order."""
    from flask import current_app

    app = app or current_app
    if not authlib_available():
        return []
    return [provider for provider in PROVIDERS.values()
            if all(_credentials(app.config, provider.name))]


def get_client(name: str):
    """Return the Authlib client for ``name``, or None if it is not usable."""
    from flask import current_app

    registry = current_app.extensions.get("comsocwebapp_oauth")
    if registry is None:
        return None
    return getattr(registry, name, None)


def fetch_identity(name: str, client, token) -> tuple[str, str | None, str | None]:
    """``(subject, email, display_name)`` for the signed-in provider account."""
    return PROVIDERS[name].identity(client, token)


# --------------------------------------------------------------------------
# Wiring
# --------------------------------------------------------------------------

def init_app(app) -> None:
    """Register every configured provider with Authlib.

    Missing Authlib or missing credentials are not errors: the app starts
    normally and offers password login only.
    """
    providers = configured_providers(app)
    if not providers:
        return

    from authlib.integrations.flask_client import OAuth

    registry = OAuth(app)
    for provider in providers:
        client_id, client_secret = _credentials(app.config, provider.name)
        registry.register(
            name=provider.name,
            client_id=client_id,
            client_secret=client_secret,
            **provider.register_kwargs,
        )
    app.extensions["comsocwebapp_oauth"] = registry
