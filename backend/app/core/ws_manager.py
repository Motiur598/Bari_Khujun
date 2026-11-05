"""Live WebSocket connections, keyed by user id.

One user can have several sockets open at once (two tabs, a phone and a laptop); every push goes to all of them.
The registry lives in this process's memory, so it only sees users connected to this worker. Running several
workers needs a shared broker (e.g. Redis pub/sub) in front of `send_personal_json`.
"""

import logging
from typing import Any

from bson import ObjectId
from fastapi import WebSocket
from fastapi.encoders import jsonable_encoder

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self.active: dict[str, list[WebSocket]] = {}

    def connect(self, user_id: str, websocket: WebSocket) -> bool:
        """Register an accepted socket. True when this is the user's first one (they just came online)."""
        sockets = self.active.setdefault(user_id, [])
        sockets.append(websocket)
        return len(sockets) == 1

    def disconnect(self, user_id: str, websocket: WebSocket) -> bool:
        """Forget a socket. True when it was the user's last one (they just went offline)."""
        sockets = self.active.get(user_id)
        if not sockets or websocket not in sockets:
            return False
        sockets.remove(websocket)
        if sockets:
            return False
        del self.active[user_id]
        return True

    def is_online(self, user_id: Any) -> bool:
        return bool(self.active.get(str(user_id)))

    def online_users(self) -> set[str]:
        return set(self.active)

    async def send_personal_json(self, user_id: Any, payload: dict) -> bool:
        """Push `payload` to every socket the user has open. True if at least one socket took it.

        A socket that fails to send is dropped from the registry; its own receive loop finishes the cleanup.
        """
        key = str(user_id)
        data = jsonable_encoder(payload, custom_encoder={ObjectId: str})
        delivered = False
        for websocket in list(self.active.get(key, [])):
            try:
                await websocket.send_json(data)
                delivered = True
            except Exception:  # closed mid-send, network gone: the socket is dead either way
                logger.debug("Dropping a dead socket for user %s", key)
                self.disconnect(key, websocket)
        return delivered


ws_manager = ConnectionManager()
