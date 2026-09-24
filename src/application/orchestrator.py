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
from src.infrastructure.nlp.context_packs import ContextPackManager
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

        self.ws_hub = ws_hub or WebSocketHub()
        self.lexical_filter = lexical_filter or LexicalFilterEngine()
        self.pack_manager = ContextPackManager(repo=self.lexical_filter.lexicon_repo)
        if active_pack_id:
            self.pack_manager.activate_pack(active_pack_id)
            self.active_pack_id = self.pack_manager.active_pack_id
        else:
            self.active_pack_id = None

        self.stage_queue = StageDisplayQueueManager(
            dispatch_coroutine=self.ws_hub.broadcast_stage,
            min_display_separation_s=4.0,
        )

        self._async_loop: Optional[asyncio.AbstractEventLoop] = None
        self._is_active = False
        self._telemetry_task: Optional[asyncio.Task] = None

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
        if self._is_active and (self._telemetry_task is None or self._telemetry_task.done()):
            self._telemetry_task = loop.create_task(self._telemetry_broadcaster_loop(), name="TelemetryLoop")

    def start(self) -> None:
        """Starts audio pipeline, queue workers, and telemetry broadcasts."""
        if self._is_active:
            logger.warning("Orchestrator is already active.")
            return

        self._is_active = True
        self.stage_queue.start(loop=self._async_loop)
        self.audio_pipeline.start()

        if self._async_loop and self._async_loop.is_running():
            self._telemetry_task = self._async_loop.create_task(
                self._telemetry_broadcaster_loop(), name="TelemetryLoop"
            )
        logger.info("VerbaClear Master Orchestrator started (Session ID: %s)", self.session_id)

    async def stop(self) -> None:
        """Gracefully shuts down pipeline and releases hardware/network resources."""
        if not self._is_active:
            return

        logger.info("Stopping VerbaClear Master Orchestrator...")
        self._is_active = False
        if self._telemetry_task:
            self._telemetry_task.cancel()
            try:
                await self._telemetry_task
            except asyncio.CancelledError:
                pass
            self._telemetry_task = None

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
        evaluations = self.lexical_filter.evaluate_sentence(segment.text, active_pack_id=self.active_pack_id)
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
            domain_badge = self.pack_manager.active_pack_badge if self.active_pack_id else "General"
            audience_card = AudienceCompanionCard(
                card_id=card_id,
                word=ev.lemma,
                part_of_speech=ev.part_of_speech,
                phonetic_ipa=phonetic_ipa,
                synonyms=synonyms,
                definition=definition or f"Specialized terminology: {ev.lemma}.",
                context_sentence=ev.context_sentence,
                spoken_time_formatted=now_formatted,
                domain_badge=domain_badge,
            )

            # Schedule threadsafe async dispatch into ASGI event loop
            if self._async_loop and self._async_loop.is_running():
                asyncio.run_coroutine_threadsafe(self._dispatch_cards(stage_card, audience_card), self._async_loop)
            else:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._dispatch_cards(stage_card, audience_card))
                except RuntimeError:
                    with self._history_lock:
                        self._session_history.append(audience_card)
                        if len(self._session_history) > 500:
                            self._session_history.pop(0)
                    logger.warning("No active asyncio event loop attached to orchestrator; recorded card to history directly.")

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

    async def _telemetry_broadcaster_loop(self) -> None:
        """Periodic telemetry heartbeat pushed to AV monitoring consoles at 4Hz (every 250ms)."""
        while self._is_active:
            try:
                if self.ws_hub.telemetry_client_count > 0:
                    data = self.get_telemetry()
                    await self.ws_hub.broadcast_telemetry(data)
                await asyncio.sleep(0.25)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Telemetry loop error: %s", str(e))
                await asyncio.sleep(1.0)

    async def blackout_stage(self) -> int:
        """Purges pending stage queue items and forces stage screen to blank immediately."""
        dropped = self.stage_queue.clear_queue()
        await self.ws_hub.broadcast_stage_blackout()
        logger.info("Stage blackout triggered. Dropped %d queued cards.", dropped)
        return dropped

    async def dismiss_stage_card(self) -> None:
        """Dismisses the active lower-third stage overlay card early."""
        await self.ws_hub.broadcast_stage_dismiss()
        logger.info("Stage card dismissed early by operator.")

    async def inject_card(
        self,
        word: str,
        synonyms: list,
        definition: str,
        phonetic_ipa: str = "",
        domain_badge: str = "Manual",
        duration_s: float = 7.0,
    ) -> str:
        """Manually injects an arbitrary vocabulary card from the AV control console."""
        card_id = f"crd_inj_{uuid.uuid4().hex[:6]}"
        now_formatted = datetime.now().strftime("%H:%M:%S")

        stage_card = StageOverlayCard(
            card_id=card_id,
            word=word.strip(),
            synonyms=synonyms,
            display_duration_s=duration_s,
        )

        from src.domain.models import PartOfSpeech
        audience_card = AudienceCompanionCard(
            card_id=card_id,
            word=word.strip(),
            part_of_speech=PartOfSpeech.NOUN,
            phonetic_ipa=phonetic_ipa or None,
            synonyms=synonyms,
            definition=definition,
            context_sentence="Injected live by AV operator.",
            spoken_time_formatted=now_formatted,
            domain_badge=domain_badge,
        )

        await self._dispatch_cards(stage_card, audience_card)
        return card_id

    def toggle_audio(self) -> bool:
        """Toggles audio mute/unmute. Returns new muted boolean state."""
        return self.audio_pipeline.toggle_mute()

    def set_active_pack(self, pack_id: Optional[str]) -> bool:
        """Switches or deactivates the domain context pack on the fly."""
        success = self.pack_manager.activate_pack(pack_id)
        if success:
            self.active_pack_id = self.pack_manager.active_pack_id
        return success

    def get_telemetry(self) -> dict:
        """Returns snapshot of real-time appliance performance metrics."""
        metrics = self.audio_pipeline.metrics
        return {
            "sessionId": self.session_id,
            "isActive": self._is_active,
            "isMuted": getattr(self.audio_pipeline, "is_muted", False),
            "audioStreamActive": self.audio_pipeline.audio_source.is_active,
            "vuRms": metrics.current_vu_rms,
            "vuDbfs": metrics.current_dbfs,
            "vadProb": metrics.current_vad_prob,
            "isSpeaking": getattr(self.audio_pipeline.segmenter, "_is_speaking", False),
            "totalFramesProcessed": metrics.total_frames_processed,
            "totalSpeechChunks": metrics.total_speech_chunks_emitted,
            "totalSessionWords": len(self._session_history),
            "lastInferenceLatencyMs": round(metrics.last_inference_latency_ms, 1),
            "avgInferenceLatencyMs": round(metrics.average_inference_latency_ms, 1),
            "connectedStageClients": self.ws_hub.stage_client_count,
            "connectedAudienceClients": self.ws_hub.audience_client_count,
            "connectedTelemetryClients": self.ws_hub.telemetry_client_count,
            "stageQueueDepth": self.stage_queue.queue_size,
            "activePackId": self.active_pack_id,
            "activePackBadge": self.pack_manager.active_pack_badge,
        }

