"""WebSocket Manager Service - Manages per-analysis WebSocket connections.

Handles real-time progress streaming for analysis pipelines including
stage changes, heartbeats, partial results, completion, and error events.

Requirements: 10.1, 10.2, 10.3, 10.4
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set
from uuid import UUID

from fastapi import WebSocket, WebSocketDisconnect

from app.models.schemas import PipelineStage, WSEvent

logger = logging.getLogger(__name__)

# Heartbeat interval in seconds
HEARTBEAT_INTERVAL_SECONDS = 5


class WebSocketManager:
    """Singleton manager for per-analysis WebSocket connections.

    Tracks active connections and current pipeline state per analysis,
    enabling reconnection support and event broadcasting.
    """

    _instance: Optional["WebSocketManager"] = None

    def __new__(cls) -> "WebSocketManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True

        # analysis_id -> set of connected WebSockets
        self._connections: Dict[str, Set[WebSocket]] = {}
        # analysis_id -> current pipeline state info
        self._pipeline_state: Dict[str, dict] = {}
        # analysis_id -> heartbeat asyncio task
        self._heartbeat_tasks: Dict[str, asyncio.Task] = {}

    @classmethod
    def reset(cls) -> None:
        """Reset singleton instance (for testing)."""
        cls._instance = None

    async def connect(
        self, websocket: WebSocket, analysis_id: str, user_id: str
    ) -> None:
        """Register a WebSocket connection for an analysis.

        Args:
            websocket: The WebSocket connection to register.
            analysis_id: The analysis ID to subscribe to.
            user_id: The authenticated user ID.
        """
        await websocket.accept()

        if analysis_id not in self._connections:
            self._connections[analysis_id] = set()

        self._connections[analysis_id].add(websocket)
        logger.info(
            f"WebSocket connected for analysis {analysis_id} (user: {user_id})"
        )

        # If pipeline is already running, send current state to reconnecting client
        current_state = self.get_current_state(analysis_id)
        if current_state is not None:
            event = WSEvent(
                event_type="stage_change",
                stage=current_state.get("stage"),
                data=current_state.get("data"),
                timestamp=datetime.now(timezone.utc),
            )
            await self._send_to_socket(websocket, event)

    async def disconnect(self, websocket: WebSocket, analysis_id: str) -> None:
        """Remove a WebSocket connection for an analysis.

        Args:
            websocket: The WebSocket connection to remove.
            analysis_id: The analysis ID to unsubscribe from.
        """
        if analysis_id in self._connections:
            self._connections[analysis_id].discard(websocket)
            if not self._connections[analysis_id]:
                del self._connections[analysis_id]

        logger.info(f"WebSocket disconnected for analysis {analysis_id}")

    async def emit_stage_change(
        self, analysis_id: str, stage: PipelineStage
    ) -> None:
        """Send stage change event to all connected clients.

        Updates internal pipeline state and broadcasts to all subscribers.

        Args:
            analysis_id: The analysis ID.
            stage: The new pipeline stage.
        """
        self._pipeline_state[analysis_id] = {
            "stage": stage,
            "data": None,
        }

        event = WSEvent(
            event_type="stage_change",
            stage=stage,
            timestamp=datetime.now(timezone.utc),
        )
        await self._broadcast(analysis_id, event)

    async def emit_heartbeat(self, analysis_id: str) -> None:
        """Send heartbeat event to all connected clients.

        Args:
            analysis_id: The analysis ID.
        """
        current = self._pipeline_state.get(analysis_id, {})
        event = WSEvent(
            event_type="heartbeat",
            stage=current.get("stage"),
            timestamp=datetime.now(timezone.utc),
        )
        await self._broadcast(analysis_id, event)

    async def emit_partial_result(
        self, analysis_id: str, data: dict
    ) -> None:
        """Send partial scorer result to all connected clients.

        Args:
            analysis_id: The analysis ID.
            data: The partial result data (e.g., a completed scorer's output).
        """
        current_state = self._pipeline_state.get(analysis_id, {})
        event = WSEvent(
            event_type="partial_result",
            stage=current_state.get("stage"),
            data=data,
            timestamp=datetime.now(timezone.utc),
        )
        await self._broadcast(analysis_id, event)

    async def emit_complete(self, analysis_id: str, data: dict) -> None:
        """Send completion event with scorecard data.

        Args:
            analysis_id: The analysis ID.
            data: The complete scorecard data.
        """
        self._pipeline_state[analysis_id] = {
            "stage": PipelineStage.COMPLETE,
            "data": data,
        }

        event = WSEvent(
            event_type="complete",
            stage=PipelineStage.COMPLETE,
            data=data,
            timestamp=datetime.now(timezone.utc),
        )
        await self._broadcast(analysis_id, event)

        # Clean up after completion
        await self.stop_heartbeat(analysis_id)

    async def emit_error(self, analysis_id: str, error_message: str) -> None:
        """Send error event to all connected clients.

        Args:
            analysis_id: The analysis ID.
            error_message: Description of the error.
        """
        self._pipeline_state[analysis_id] = {
            "stage": PipelineStage.FAILED,
            "data": {"error": error_message},
        }

        event = WSEvent(
            event_type="error",
            stage=PipelineStage.FAILED,
            data={"error": error_message},
            timestamp=datetime.now(timezone.utc),
        )
        await self._broadcast(analysis_id, event)

        # Clean up after error
        await self.stop_heartbeat(analysis_id)

    def get_current_state(self, analysis_id: str) -> Optional[dict]:
        """Get current pipeline state for reconnection support.

        Args:
            analysis_id: The analysis ID.

        Returns:
            Dict with 'stage' and 'data' keys, or None if no state exists.
        """
        return self._pipeline_state.get(analysis_id)

    async def start_heartbeat(self, analysis_id: str) -> None:
        """Start periodic heartbeat task for an analysis.

        Sends heartbeat events every 5 seconds while the analysis is active.

        Args:
            analysis_id: The analysis ID.
        """
        # Stop existing heartbeat if any
        await self.stop_heartbeat(analysis_id)

        async def _heartbeat_loop():
            try:
                while True:
                    await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
                    await self.emit_heartbeat(analysis_id)
            except asyncio.CancelledError:
                pass

        task = asyncio.create_task(_heartbeat_loop())
        self._heartbeat_tasks[analysis_id] = task
        logger.debug(f"Heartbeat started for analysis {analysis_id}")

    async def stop_heartbeat(self, analysis_id: str) -> None:
        """Stop the heartbeat task for an analysis.

        Args:
            analysis_id: The analysis ID.
        """
        task = self._heartbeat_tasks.pop(analysis_id, None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        logger.debug(f"Heartbeat stopped for analysis {analysis_id}")

    def cleanup_analysis(self, analysis_id: str) -> None:
        """Remove all state for a completed/failed analysis.

        Call this after the analysis terminal state has been consumed by clients.

        Args:
            analysis_id: The analysis ID to clean up.
        """
        self._pipeline_state.pop(analysis_id, None)
        self._connections.pop(analysis_id, None)

    async def shutdown(self) -> None:
        """Gracefully close all active WebSocket connections and heartbeat tasks."""
        # Cancel all heartbeats
        for analysis_id in list(self._heartbeat_tasks.keys()):
            await self.stop_heartbeat(analysis_id)

        # Close all connections
        for analysis_id, sockets in list(self._connections.items()):
            for ws in list(sockets):
                try:
                    await ws.close(code=1001, reason="Server shutting down")
                except Exception:
                    pass
            sockets.clear()

        self._connections.clear()
        self._pipeline_state.clear()
        logger.info("WebSocket manager shut down")

    async def _broadcast(self, analysis_id: str, event: WSEvent) -> None:
        """Broadcast an event to all connected clients for an analysis.

        Handles individual connection failures gracefully by removing
        dead connections.

        Args:
            analysis_id: The analysis ID.
            event: The WSEvent to broadcast.
        """
        sockets = self._connections.get(analysis_id, set())
        if not sockets:
            return

        dead_sockets: List[WebSocket] = []

        for ws in sockets:
            try:
                await self._send_to_socket(ws, event)
            except Exception:
                dead_sockets.append(ws)

        # Remove dead connections
        for ws in dead_sockets:
            sockets.discard(ws)
            logger.debug(
                f"Removed dead WebSocket connection for analysis {analysis_id}"
            )

    async def _send_to_socket(self, websocket: WebSocket, event: WSEvent) -> None:
        """Send a single event to a WebSocket connection.

        Serializes the WSEvent model to JSON for transmission.

        Args:
            websocket: The target WebSocket.
            event: The WSEvent to send.
        """
        await websocket.send_json(event.model_dump(mode="json"))


# Module-level singleton instance
ws_manager = WebSocketManager()
