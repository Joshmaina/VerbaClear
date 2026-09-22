"""
Real-Time WebSocket Hub for VerbaClear.
Implements BroadcasterPort to dispatch synchronized stage and audience events over WebSockets.
Follows the RFC 6455 specification and JSON contracts in Docs/DATA_DICTIONARY.md.
"""

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Set
from fastapi import WebSocket, WebSocketDisconnect

from src.domain.interfaces import BroadcasterPort
from src.domain.models import AudienceCompanionCard, StageOverlayCard

logger = logging.getLogger(__name__)


class WebSocketHub(BroadcasterPort):
    """
    Manages active WebSocket connections across segregated channels:
    - Stage presentation screens (/ws/stage)
    - Audience mobile companions (/ws/audience)
    - Administrative telemetry (/ws/telemetry)
    """

    def __init__(self):
        self._stage_sockets: Set[WebSocket] = set()
        self._audience_sockets: Set[WebSocket] = set()
        self._telemetry_sockets: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect_stage(self, websocket: WebSocket) -> None:
        """Registers a stage presentation display client."""
        await websocket.accept()
        async with self._lock:
            self._stage_sockets.add(websocket)
        logger.info("Stage screen connected (Total stage clients: %d)", len(self._stage_sockets))

    async def disconnect_stage(self, websocket: WebSocket) -> None:
        """Unregisters a stage client upon disconnect."""
        async with self._lock:
            self._stage_sockets.discard(websocket)
        logger.info("Stage screen disconnected (Remaining stage clients: %d)", len(self._stage_sockets))

    async def connect_audience(self, websocket: WebSocket) -> None:
        """Registers an attendee mobile companion client."""
        await websocket.accept()
        async with self._lock:
            self._audience_sockets.add(websocket)
        logger.info("Audience companion connected (Total audience clients: %d)", len(self._audience_sockets))

    async def disconnect_audience(self, websocket: WebSocket) -> None:
        """Unregisters an audience client upon disconnect."""
        async with self._lock:
            self._audience_sockets.discard(websocket)
        logger.info("Audience companion disconnected (Remaining audience clients: %d)", len(self._audience_sockets))

    async def connect_telemetry(self, websocket: WebSocket) -> None:
        """Registers an AV telemetry monitor."""
        await websocket.accept()
        async with self._lock:
            self._telemetry_sockets.add(websocket)

    async def disconnect_telemetry(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._telemetry_sockets.discard(websocket)

    @property
    def stage_client_count(self) -> int:
        return len(self._stage_sockets)

    @property
    def audience_client_count(self) -> int:
        return len(self._audience_sockets)

    async def broadcast_stage(self, card: StageOverlayCard) -> None:
        """
        Dispatches lightweight lower-third card payload to connected stage screens.
        Adheres to contract: STAGE_DISPLAY_POP
        """
        payload = {
            "eventId": f"evt_{card.card_id}",
            "topic": "STAGE_DISPLAY_POP",
            "timestamp": int(time.time() * 1000),
            "data": {
                "cardId": card.card_id,
                "word": card.word.title(),
                "synonyms": card.synonyms,
                "displayDurationSeconds": card.display_duration_s,
                "theme": {
                    "accentColor": card.accent_color,
                    "position": "bottom-right",
                },
            },
        }
        await self._broadcast_to_set(self._stage_sockets, payload)

    async def broadcast_audience(self, card: AudienceCompanionCard) -> None:
        """
        Dispatches comprehensive educational payload to all connected mobile companions.
        Adheres to contract: AUDIENCE_VOCABULARY_CARD
        """
        payload = {
            "eventId": f"evt_{card.card_id}",
            "topic": "AUDIENCE_VOCABULARY_CARD",
            "timestamp": int(time.time() * 1000),
            "data": {
                "cardId": card.card_id,
                "word": card.word.title(),
                "partOfSpeech": card.part_of_speech.value,
                "phoneticIpa": card.phonetic_ipa,
                "synonyms": card.synonyms,
                "definition": card.definition,
                "contextSentence": card.context_sentence,
                "spokenTimeFormatted": card.spoken_time_formatted,
                "domainBadge": card.domain_badge,
            },
        }
        await self._broadcast_to_set(self._audience_sockets, payload)

    async def broadcast_telemetry(self, telemetry_data: Dict[str, Any]) -> None:
        """Dispatches operational health telemetry to AV consoles."""
        payload = {
            "topic": "SYSTEM_TELEMETRY",
            "timestamp": int(time.time() * 1000),
            "data": telemetry_data,
        }
        await self._broadcast_to_set(self._telemetry_sockets, payload)

    async def _broadcast_to_set(self, socket_set: Set[WebSocket], payload: Dict[str, Any]) -> None:
        """High-throughput async broadcast with automatic dead socket cleanup."""
        if not socket_set:
            return

        message_str = json.dumps(payload)
        dead_sockets: List[WebSocket] = []

        async def _send(ws: WebSocket):
            try:
                await ws.send_text(message_str)
            except (WebSocketDisconnect, ConnectionResetError, RuntimeError):
                dead_sockets.append(ws)
            except Exception as e:
                logger.warning("Error pushing WebSocket frame: %s", str(e))
                dead_sockets.append(ws)

        async with self._lock:
            active_sockets = list(socket_set)

        if active_sockets:
            await asyncio.gather(*[_send(ws) for ws in active_sockets], return_exceptions=True)

        if dead_sockets:
            async with self._lock:
                for ws in dead_sockets:
                    socket_set.discard(ws)
