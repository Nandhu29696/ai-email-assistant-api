"""Role-based access: admin → client → user.

* admin  — every mailbox, user and setting.
* client — a customer account: its own mailboxes and the users (staff) it created.
* user   — staff of one client: works with that client's mailboxes exactly like the
           client does, but cannot manage logins.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.email import EmailIntegration
    from app.models.user import User

ROLES = ("admin", "client", "user")


def account_id(user: "User") -> int | None:
    """The client account whose mailboxes this login works with (None = admin, sees all).

    A user without a client gets 0, which matches no mailbox.
    """
    if user.role == "admin":
        return None
    if user.role == "user":
        return user.client_id or 0
    return user.id


def owns(user: "User", integration: "EmailIntegration") -> bool:
    """May this login see and manage this mailbox?"""
    account = account_id(user)
    return account is None or (integration.owner_user_id is not None and integration.owner_user_id == account)


def scope_mailboxes(query, user: "User"):
    """Limit a query that involves EmailIntegration to the mailboxes this login may see."""
    from app.models.email import EmailIntegration
    account = account_id(user)
    return query if account is None else query.filter(EmailIntegration.owner_user_id == account)


def owner_for_new_mailbox(user: "User") -> int:
    """Owner recorded on a mailbox this login connects (a user connects it for its client)."""
    return user.client_id if user.role == "user" and user.client_id else user.id
