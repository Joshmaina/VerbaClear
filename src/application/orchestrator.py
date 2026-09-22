"""
Master Pipeline Orchestrator for VerbaClear.
Unifies Audio Capture (Phase 1), Lexical Intelligence (Phase 2), and Real-Time WebSockets (Phase 3).
"""

import asyncio
from datetime import datetime
import logging
import threading
import time
from typing import Optional
import uuid

from src.api.ws.hub import WebSocketHub
from src.api.ws.rate_limiter import StageDisplayQueueManager
from src.application.audio_pipeline import AudioASRPipeline
from src.domain.models import AudienceCompanionCard, StageOverlayCard, TranscribedSegment
from src.infrastructure.nlp.filter import LexicalFilterEngine

logger = logging.getLogger(__name__)


class VerbaClearOrchestrator:
    """
    Central operational engine running the full live pipeline:
    Microphone -> VAD -> faster-whisper -> spaCy Lemmatizer -> NGSL Bloom Filter ->
    SQLite Lexicon -> Staggered Stage Overlay & Immediate Audience Mobile Broadcast.
    """

    def __init__(
        self,
        audio_pipeline: Optional[AudioASRPipeline] = None,
        lexical_filter: Optional[LexicalFilterEngine] = None,
        ws_hub: Optional[WebSocketHub] = None,
        session_id: Optional[str] = None,
        active_pack_id: Optional[str] = None,
    ):
        self.session_id = session_id or f"sess_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.active_pack_id = active_pack_id

        self.ws_hub = ws_hub or WebSocketHub()
        self.lexical_filter = lexical_filter or LexicalFilterEngine()
        self.stage_queue = StageDisplayQueueManager(
            dispatch_coroutine=self.ws_hub.broadcast_stage,
            min_display_separation_s=4.0,
        )

        self._async_loop: Optional[asyncio.AbstractEventLoop] = None
        self._is_active = False

        # Session vocabulary history for mobile attendee onboarding and export
        self._session_history = []
        self._history_lock = threading.Lock()

        # Audio pipeline with callback
        self.audio_pipeline = audio_pipeline or AudioASRPipeline(
            on_segment_callback=self._handle_transcribed_segment,
        )

    def attach_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Attaches the main ASGI asyncio event loop for threadsafe coroutine scheduling."""
        self._async_loop = loop

    def start(self) -> None:
        """Starts audio pipeline, queue workers, and telemetry broadcasts."""
        if self._is_active:
            logger.warning("Orchestrator is already active.")
            return

        self._is_active = True
        self.stage_queue.start(loop=self._async_loop)
        self.audio_pipeline.start()
        logger.info("VerbaClear Master Orchestrator started (Session ID: %s)", self.session_id)

    async def stop(self) -> None:
        """Gracefully shuts down pipeline and releases hardware/network resources."""
        if not self._is_active:
            return

        logger.info("Stopping VerbaClear Master Orchestrator...")
        self._is_active = False
        self.audio_pipeline.stop()
        await self.stage_queue.stop()
        logger.info("VerbaClear Master Orchestrator shut down cleanly.")

    def _handle_transcribed_segment(self, segment: TranscribedSegment) -> None:
        """
        Invoked on audio thread whenever ASR produces a transcribed text chunk.
        Dispatches linguistic analysis and schedules async WebSocket broadcasts.
        """
        if not segment.text or not self._is_active:
            return

        # Phase 2: Linguistic and Frequency Evaluation
        evaluations = self.lexical_filter.evaluate_sentence(segment.text)
        if not evaluations:
            return

        logger.info(
            "Extracted %d uncommon vocabulary items from: \"%s\"",
            len(evaluations),
            segment.text,
        )

        now_formatted = datetime.now().strftime("%H:%M:%S")

        for ev in evaluations:
            card_id = f"crd_{uuid.uuid4().hex[:8]}"

            # Retrieve punchy synonyms, phonetics, and simplified definitions
            synonyms = self.lexical_filter.resolve_synonyms(ev.lemma, active_pack_id=self.active_pack_id)
            phonetic_ipa, definition = self.lexical_filter.resolve_definition_and_phonetics(
                ev.lemma, active_pack_id=self.active_pack_id
            )

            # 1. Build Stage Overlay Card (Ambient Glance)
            stage_card = StageOverlayCard(
                card_id=card_id,
                word=ev.lemma,
                synonyms=synonyms,
                display_duration_s=7.0,
            )

            # 2. Build Audience Mobile Companion Card (Deep Dive Notebook)
            audience_card = AudienceCompanionCard(
                card_id=card_id,
                word=ev.lemma,
                part_of_speech=ev.part_of_speech,
                phonetic_ipa=phonetic_ipa,
                synonyms=synonyms,
                definition=definition or f"Specialized terminology: {ev.lemma}.",
                context_sentence=ev.context_sentence,
                spoken_time_formatted=now_formatted,
                domain_badge="Domain" if self.active_pack_id else "General",
            )

            # Schedule threadsafe async dispatch into ASGI event loop
            if self._async_loop and self._async_loop.is_running():
                asyncio.run_coroutine_threadsafe(self._dispatch_cards(stage_card, audience_card), self._async_loop)
            else:
                logger.warning("No active asyncio event loop attached to orchestrator.")

    async def _dispatch_cards(self, stage_card: StageOverlayCard, audience_card: AudienceCompanionCard) -> None:
        """Dispatches cards to respective stage and audience queues and records history."""
        with self._history_lock:
            self._session_history.append(audience_card)
            if len(self._session_history) > 500:
                self._session_history.pop(0)

        # Enqueue for staggered stage display
        await self.stage_queue.enqueue(stage_card)

        # Immediate broadcast to audience mobile devices
        await self.ws_hub.broadcast_audience(audience_card)

    def add_card_to_history(self, card: AudienceCompanionCard) -> None:
        """Directly inserts a card into session history (used in tests/simulations)."""
        with self._history_lock:
            self._session_history.append(card)
            if len(self._session_history) > 500:
                self._session_history.pop(0)

    def get_session_cards(self) -> list:
        """Returns all vocabulary cards emitted during the active session."""
        with self._history_lock:
            return list(self._session_history)

    def get_telemetry(self) -> dict:
        """Returns snapshot of real-time appliance performance metrics."""
        metrics = self.audio_pipeline.metrics
        return {
            "sessionId": self.session_id,
            "isActive": self._is_active,
            "audioStreamActive": self.audio_pipeline.audio_source.is_active,
            "totalFramesProcessed": metrics.total_frames_processed,
            "totalSpeechChunks": metrics.total_speech_chunks_emitted,
            "totalSessionWords": len(self._session_history),
            "lastInferenceLatencyMs": round(metrics.last_inference_latency_ms, 1),
            "avgInferenceLatencyMs": round(metrics.average_inference_latency_ms, 1),
            "connectedStageClients": self.ws_hub.stage_client_count,
            "connectedAudienceClients": self.ws_hub.audience_client_count,
            "stageQueueDepth": self.stage_queue.queue_size,
        }
