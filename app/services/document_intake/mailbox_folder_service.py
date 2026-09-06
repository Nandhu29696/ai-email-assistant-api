"""
Mailbox folder service (§5 steps 10/11) — Gmail label-based "move to folder".
Gmail has no true folders; success/failure is represented by removing INBOX
and applying the configured success/failed label, creating labels on first use.
"""
from __future__ import annotations
from loguru import logger


def _get_or_create_label_id(service, label_name: str) -> str | None:
    """Find a label by name (supports nested 'Parent/Child' labels), creating it if missing."""
    try:
        labels = service.users().labels().list(userId="me").execute().get("labels", [])
        for label in labels:
            if label.get("name") == label_name:
                return label.get("id")

        created = (
            service.users()
            .labels()
            .create(
                userId="me",
                body={
                    "name": label_name,
                    "labelListVisibility": "labelShow",
                    "messageListVisibility": "show",
                },
            )
            .execute()
        )
        return created.get("id")
    except Exception as exc:
        logger.warning(f"[mailbox_folder_service] Failed to get/create label '{label_name}': {exc}")
        return None


def move_to_label(service, gmail_message_id: str, label_name: str, remove_inbox: bool = True) -> bool:
    """Remove INBOX (optional) and apply the given label to a Gmail message."""
    label_id = _get_or_create_label_id(service, label_name)
    if not label_id:
        return False

    try:
        body: dict = {"addLabelIds": [label_id]}
        if remove_inbox:
            body["removeLabelIds"] = ["INBOX", "UNREAD"]
        service.users().messages().modify(userId="me", id=gmail_message_id, body=body).execute()
        return True
    except Exception as exc:
        logger.warning(f"[mailbox_folder_service] Failed to move message {gmail_message_id} to '{label_name}': {exc}")
        return False


def move_to_success(service, gmail_message_id: str, success_folder_label: str) -> bool:
    return move_to_label(service, gmail_message_id, success_folder_label)


def move_to_failed(service, gmail_message_id: str, failed_folder_label: str) -> bool:
    return move_to_label(service, gmail_message_id, failed_folder_label)
