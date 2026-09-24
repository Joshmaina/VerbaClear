"""
Stage Display Anti-Collision Queue & Rate Limiter for VerbaClear.
Staggers rapid-fire vocabulary events to prevent screen flashing and visual distraction on stage.
"""

import asyncio
import logging
from typing import Callable, Coroutine, Optional
from src.domain.models import StageOverlayCard

logger = logging.getLogger(__name__)


class StageDisplayQueueManager:
    """
    Ensures lower-third stage overlay cards are displayed with graceful pacing.
    If multiple uncommon words occur within seconds of each other, they are queued
    and displayed consecutively with guaranteed readability separation.
    """

    def __init__(
        self,
        dispatch_coroutine: Callable[[StageOverlayCard], Coroutine],
        min_display_separation_s: float = 4.0,
        max_queue_depth: int = 10,
    ):
        self._dispatch = dispatch_coroutine
        self.min_display_separation_s = min_display_separation_s
        self.max_queue_depth = max_queue_depth

        self._queue: asyncio.Queue[StageOverlayCard] = asyncio.Queue(maxsize=max_queue_depth)
        self._worker_task: Optional[asyncio.Task] = None
        self._is_running = False
        self._delay_event = asyncio.Event()

    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        """Starts the queue consumer worker task."""
        if self._is_running:
            return
        self._is_running = True
        try:
            active_loop = loop or asyncio.get_running_loop()
            self._worker_task = active_loop.create_task(self._process_queue(), name="StageQueueWorker")
            logger.debug("StageDisplayQueueManager started with active loop.")
        except RuntimeError:
            logger.debug("No running asyncio loop when starting StageDisplayQueueManager; worker task will lazy-start.")

    async def stop(self) -> None:
        """Stops the queue manager gracefully."""
        self._is_running = False
        self.interrupt_delay()
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
        logger.debug("StageDisplayQueueManager stopped.")

    def interrupt_delay(self) -> None:
        """Interrupts the active delay separation to immediately process the next card or wake worker."""
        self._delay_event.set()

    async def enqueue(self, card: StageOverlayCard) -> bool:
        """
        Enqueues a card for stage display.
        Returns True if enqueued, False if dropped due to queue congestion.
        """
        # Ensure worker task is running if loop is active
        if self._is_running and (self._worker_task is None or self._worker_task.done()):
            try:
                loop = asyncio.get_running_loop()
                self._worker_task = loop.create_task(self._process_queue(), name="StageQueueWorker")
            except RuntimeError:
                pass
        try:
            self._queue.put_nowait(card)
            return True
        except asyncio.QueueFull:
            logger.warning("Stage queue congested (depth=%d); dropping card '%s'.", self._queue.qsize(), card.word)
            return False

    async def _process_queue(self) -> None:
        """Consumes cards from queue and spaces emissions by min_display_separation_s."""
        while self._is_running:
            try:
                card = await self._queue.get()
                await self._dispatch(card)
                self._queue.task_done()

                # Stagger emissions to enforce presentation separation on stage display
                self._delay_event.clear()
                try:
                    await asyncio.wait_for(
                        self._delay_event.wait(), timeout=self.min_display_separation_s
                    )
                except asyncio.TimeoutError:
                    pass
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in StageDisplayQueueManager loop: %s", str(e), exc_info=True)
                await asyncio.sleep(0.5)

    def clear_queue(self) -> int:
        """Drains all queued cards immediately and wakes any waiting worker. Returns count of dropped cards."""
        dropped = 0
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
                dropped += 1
            except (asyncio.QueueEmpty, ValueError):
                break
        self.interrupt_delay()
        logger.info("Stage queue cleared by operator (dropped %d cards).", dropped)
        return dropped

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()
