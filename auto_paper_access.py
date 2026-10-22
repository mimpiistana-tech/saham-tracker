"""Fail-closed authorization helper for PAPER-ONLY administration.

No network calls, broker orders or side effects.
"""
import hmac
import os


def paper_admin_authorized(headers, environ=None):
    """Require a sufficiently long configured bearer secret and exact match."""
    env = os.environ if environ is None else environ
    if not hasattr(env, "get") or not hasattr(headers, "get"):
        return False
    expected = env.get("AUTO_PAPER_ADMIN_TOKEN", "")
    authorization = headers.get("Authorization", "")
    if not isinstance(expected, str) or len(expected) < 32:
        return False
    if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
        return False
    supplied = authorization[len("Bearer "):]
    if len(supplied) < 32 or supplied != supplied.strip():
        return False
    return hmac.compare_digest(supplied, expected)
