"""WebSocket connection manager - broadcast event realtime ke client.

Event yang di-broadcast:
- penerima.created / penerima.updated
- distribusi.created
- fraud.detected
"""
import asyncio
import json
import logging
from typing import Any, Dict, List

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.active: List[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self.active.append(ws)
        logger.info("WS connected (total=%d)", len(self.active))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            if ws in self.active:
                self.active.remove(ws)
        logger.info("WS disconnected (total=%d)", len(self.active))

    async def broadcast(self, event: str, data: Dict[str, Any]) -> None:
        message = json.dumps({"event": event, "data": data}, default=str)
        dead: List[WebSocket] = []
        for ws in list(self.active):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)


ws_manager = ConnectionManager()


def broadcast_sync(event: str, data: Dict[str, Any]) -> None:
    """Helper untuk dipanggil dari context sync (router biasa).

    Pakai asyncio.create_task kalau ada event loop, kalau tidak skip diam-diam.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(ws_manager.broadcast(event, data))
    except RuntimeError:
        # Tidak ada event loop, abaikan (mis. di test sync)
        pass
