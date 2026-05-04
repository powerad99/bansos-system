"""WebSocket endpoint untuk realtime event.

Connect via: ws://<host>/ws?token=<JWT>
Server akan broadcast event:
  - penerima.created / penerima.updated
  - distribusi.created / distribusi.scanned
  - fraud.detected
"""
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.core.security import decode_access_token
from app.core.ws_manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket, token: str = Query(...)):
    payload = decode_access_token(token)
    if not payload or not payload.get("sub"):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await ws_manager.connect(websocket)
    try:
        # initial hello
        await websocket.send_json({"event": "connected", "data": {"user_id": payload["sub"]}})
        # Keep alive: kita hanya consume ping client (kalau ada)
        while True:
            msg = await websocket.receive_text()
            # Echo back ping atau abaikan
            if msg.lower() == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
    except Exception as e:
        logger.warning("WS error: %s", e)
        await ws_manager.disconnect(websocket)
