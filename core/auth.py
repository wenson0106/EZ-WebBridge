"""
EZ-Portal Authentication Module for EZ-WebBridge.

Uses Flask sessions for stateful login. Passwords are stored as
scrypt hashes via Python's built-in hashlib (no extra deps).
"""

import hashlib
import os
import secrets
from functools import wraps
from flask import session, redirect, url_for, request


# ── Password Hashing ──────────────────────────────────────────

def hash_password(password: str) -> str:
    """Hash a plaintext password with scrypt + random salt.
    Returns a storable string: 'scrypt$salt_hex$hash_hex'.
    """
    salt = os.urandom(16)
    dk = hashlib.scrypt(
        password.encode('utf-8'),
        salt=salt,
        n=16384, r=8, p=1,
        dklen=32,
    )
    return f"scrypt${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a plaintext password against a stored hash string."""
    try:
        algo, salt_hex, hash_hex = stored_hash.split('$')
        if algo != 'scrypt':
            return False
        salt = bytes.fromhex(salt_hex)
        dk = hashlib.scrypt(
            password.encode('utf-8'),
            salt=salt,
            n=16384, r=8, p=1,
            dklen=32,
        )
        return secrets.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


# ── Session Helpers ───────────────────────────────────────────

ADMIN_SESSION_KEY = 'ez_portal_admin'
PORTAL_SESSION_KEY = 'ez_portal_authed'        # visitor auth (per-service)
PORTAL_SERVICE_KEY = 'ez_portal_services_ok'   # set of authed service IDs


def login_admin(user_id: int):
    """Mark current session as authenticated admin."""
    session[ADMIN_SESSION_KEY] = user_id
    session.permanent = True


def logout_admin():
    session.pop(ADMIN_SESSION_KEY, None)


def is_admin_logged_in() -> bool:
    return ADMIN_SESSION_KEY in session


def require_admin(f):
    """Decorator — redirects to /portal/login if not authenticated."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not is_admin_logged_in():
            return redirect(url_for('portal_login_page', next=request.path))
        return f(*args, **kwargs)
    return decorated


def login_visitor_for_service(service_id: int):
    """Mark the visitor as authenticated for a specific service."""
    authed = session.get(PORTAL_SERVICE_KEY, [])
    if service_id not in authed:
        authed.append(service_id)
    session[PORTAL_SERVICE_KEY] = authed


def is_visitor_authed_for_service(service_id: int) -> bool:
    return service_id in session.get(PORTAL_SERVICE_KEY, [])
