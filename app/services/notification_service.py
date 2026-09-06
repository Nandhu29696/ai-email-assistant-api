"""
WebSocket notification manager.
Maintains active connections and broadcasts real-time alerts.
"""
from __future__ import annotations
from fastapi import WebSocket
from loguru import logger
import json


class NotificationManager:
    """Manages WebSocket connections and broadcasts notifications."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.connection_users: dict[WebSocket, tuple[int, str]] = {}

    async def connect(self, websocket: WebSocket, user_id: int, role: str):
        await websocket.accept()
        self.active_connections.append(websocket)
        self.connection_users[websocket] = (user_id, role)
        logger.info(f"WS client connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections = [
            ws for ws in self.active_connections if ws is not websocket
        ]
        self.connection_users.pop(websocket, None)
        logger.info(f"WS client disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, notification: dict):
        """Send notification JSON to all connected clients."""
        payload = json.dumps(notification)
        target_user_id = notification.get("user_id")
        dead: list[WebSocket] = []
        for ws in self.active_connections:
            user_id, role = self.connection_users.get(ws, (None, ""))
            if target_user_id is not None and user_id != target_user_id and role != "admin":
                continue
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def broadcast_notification(self, notification_dict: dict):
        """Broadcast a full Notification object (matching frontend Notification type)."""
        await self.broadcast(notification_dict)

    async def send_email_notification(
        self,
        email_id: str,
        subject: str,
        sender: str,
        priority: str,
        sentiment: str,
        notification_type: str = "new_email",
    ):
        """Convenience method to broadcast a new email notification."""
        await self.broadcast(
            {
                "type": notification_type,
                "email_id": email_id,
                "subject": subject,
                "sender": sender,
                "priority": priority,
                "sentiment": sentiment,
            }
        )


# Singleton instance used across the app
notification_manager = NotificationManager()
