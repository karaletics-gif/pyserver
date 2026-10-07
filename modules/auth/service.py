"""
modules/auth/service.py – authentication service layer.

Public API
----------
  register(name, email, password, role)  → User
  login(email, password, request)        → (User, session_token)
  logout(request)                        → None
  change_password(user_id, old_pw, new_pw) → User
  get_current_user(request)              → User | None
  require_auth(request)                  → User  (raises AuthError if not)
"""

from __future__ import annotations

from database.orm             import QuerySet
from change_password.users.model      import User
from modules.auth.passwords   import hash_password, verify_password, needs_rehash, validate_password
from modules.auth.permissions import is_valid_role, ROLE_HIERARCHY
from modules.auth.sessions    import sessions


# ── Exceptions ────────────────────────────────────────────────────────────────

class AuthError(Exception):
    """Raised for all auth failures (wrong password, inactive account, etc.)."""

class RegistrationError(Exception):
    """Raised when user registration cannot proceed."""


# ── Registration ──────────────────────────────────────────────────────────────

def register(
    name:     str,
    email:    str,
    password: str,
    *,
    role:     str = "member",
    bio:      str = "",
    allow_weak_password: bool = False,
) -> User:
    """
    Create and return a new User.

    Raises RegistrationError on validation failures.
    """
    # ── Validate ──────────────────────────────────────────────────────
    name  = name.strip()
    email = email.strip().lower()

    if not name:
        raise RegistrationError("Name is required.")
    if not email or "@" not in email:
        raise RegistrationError("A valid email address is required.")
    try:
        validate_password(password, allow_weak=allow_weak_password)
    except ValueError as exc:
        raise RegistrationError(str(exc)) from exc
    if not is_valid_role(role):
        raise RegistrationError(f"Unknown role {role!r}.")

    # ── Uniqueness check ──────────────────────────────────────────────
    if QuerySet(User).filter(email=email).exists():
        raise RegistrationError(f"An account with email {email!r} already exists.")

    # ── Persist ───────────────────────────────────────────────────────
    user = User.objects.create(
        name     = name,
        email    = email,
        password = hash_password(password),
        role     = role,
        bio      = bio,
        active   = 1,
    )
    return user


# ── Login / logout ────────────────────────────────────────────────────────────

def login(email: str, password: str, request=None) -> tuple[User, str]:
    """
    Verify credentials and create a session.

    Returns (user, session_token).
    Raises AuthError on any failure (deliberately vague to prevent enumeration).
    """
    email = (email or "").strip().lower()

    try:
        user = QuerySet(User).filter(email=email).get(email=email)
    except (User.DoesNotExist, User.MultipleObjectsReturned):
        # Constant-time: always hash even if no user found
        hash_password("dummy_constant_time_work")
        raise AuthError("Invalid email or password.")

    if not user.active:
        raise AuthError("This account has been deactivated.")

    if not verify_password(password, user.password):
        raise AuthError("Invalid email or password.")

    # Silently upgrade hash if iterations have changed
    if needs_rehash(user.password):
        user.password = hash_password(password)
        user.save()

    # Create session
    token = sessions.create(
        user_id = user.id,
        email   = user.email,
        role    = user.role,
        name    = user.name,
    )
    return user, token


def logout(request) -> None:
    """Destroy the session attached to *request*."""
    token = sessions.extract_token(request)
    if token:
        sessions.delete(token)


# ── Current-user helpers ──────────────────────────────────────────────────────

def get_current_user(request) -> User | None:
    """
    Return the User for the session cookie on *request*, or None.

    Rehydrates the User from DB on every call (no stale cache).
    Attaches the result to request.user for the duration of the request.
    """
    # Already resolved this request?
    if getattr(request, "_auth_user_resolved", False):
        return getattr(request, "user", None)

    token = sessions.extract_token(request)
    data  = sessions.get(token)

    user: User | None = None
    if data and "user_id" in data:
        try:
            user = QuerySet(User).filter(active=1).get(id=data["user_id"])
            # Refresh role from DB (may have changed since session was created)
            if user.role != data.get("role"):
                sessions.update(token, role=user.role)
        except (User.DoesNotExist, User.MultipleObjectsReturned):
            sessions.delete(token)
            user = None

    request.user = user
    request._auth_user_resolved = True
    return user


def require_auth(request) -> User:
    """Return current user or raise AuthError."""
    user = get_current_user(request)
    if user is None:
        raise AuthError("Authentication required.")
    return user


# ── Account management ────────────────────────────────────────────────────────

def change_password(
    user_id:      int,
    old_password: str,
    new_password: str,
    *,
    allow_weak_password: bool = False,
) -> User:
    """
    Change a user's password after verifying the old one.
    Invalidates all existing sessions for the user.
    """
    try:
        user = QuerySet(User).get(id=user_id)
    except User.DoesNotExist:
        raise AuthError("User not found.")

    if not verify_password(old_password, user.password):
        raise AuthError("Current password is incorrect.")
    try:
        validate_password(new_password, allow_weak=allow_weak_password)
    except ValueError as exc:
        raise AuthError(str(exc)) from exc

    user.password = hash_password(new_password)
    user.save()

    # Revoke all sessions for this user
    sessions.delete_for_user(user_id)
    return user


def update_role(
    user_id:    int,
    new_role:   str,
    changed_by: User,
) -> User:
    """
    Change a user's role.  Only admins may do this.
    Refreshes the user's active sessions so the new role takes effect
    without requiring re-login.
    """
    from modules.auth.permissions import can
    if not can(changed_by, "manage_roles"):
        raise AuthError("You do not have permission to change roles.")
    if not is_valid_role(new_role):
        raise AuthError(f"Unknown role: {new_role!r}")

    try:
        user = QuerySet(User).get(id=user_id)
    except User.DoesNotExist:
        raise AuthError(f"User id={user_id} not found.")

    user.role = new_role
    user.save()

    # Update any live sessions
    with sessions._lock:
        for data in sessions._store.values():
            if data.get("user_id") == user_id:
                data["role"] = new_role

    return user
