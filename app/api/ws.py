"""WebSocket endpoint for real-time analysis progress streaming.

Provides the /ws/analysis/{analysis_id} endpoint with JWT authentication
via query parameter and reconnection support.

Requirements: 10.1, 10.2, 10.3, 10.4
"""

import logging
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from jose import JWTError, jwt

from app.api.dependencies import JWT_ALGORITHM, JWT_SECRET
from app.services.ws_manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter()


def _authenticate_ws_token(token: Optional[str]) -> Optional[str]:
    """Validate a JWT token from WebSocket query parameter.

    Args:
        token: The JWT token string from the query param.

    Returns:
        The user_id (sub claim) if valid, None otherwise.
    """
    if token is None:
        return None

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id: Optional[str] = payload.get("sub")
        return user_id
    except JWTError:
        return None


@router.websocket("/ws/analysis/{analysis_id}")
async def analysis_websocket(
    websocket: WebSocket,
    analysis_id: str,
    token: Optional[str] = Query(default=None),
) -> None:
    """WebSocket endpoint for streaming analysis progress events.

    Authenticates the client via JWT token in query parameter,
    registers the connection with the WebSocket manager, and keeps
    the connection alive until the client disconnects or the server shuts down.

    On reconnection, the current pipeline state is sent immediately.

    Args:
        websocket: The WebSocket connection.
        analysis_id: The analysis ID to subscribe to.
        token: JWT token for authentication (query parameter).
    """
    # Authenticate via JWT query param
    user_id = _authenticate_ws_token(token)
    if user_id is None:
        await websocket.close(code=4001, reason="Authentication required")
        return

    # Register connection
    await ws_manager.connect(websocket, analysis_id, user_id)

    try:
        # Keep connection alive - listen for client messages (ping/pong, close)
        while True:
            # We don't expect meaningful messages from the client,
            # but we need to await to detect disconnection
            data = await websocket.receive_text()
            # Client can send "ping" for keep-alive
            if data == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket, analysis_id)
    except Exception as e:
        logger.warning(
            f"WebSocket error for analysis {analysis_id}: {str(e)}"
        )
        await ws_manager.disconnect(websocket, analysis_id)
