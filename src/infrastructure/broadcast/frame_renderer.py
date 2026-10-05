"""
Broadcast Lower-Third Frame Renderer for VerbaClear.
Generates pristine 1920x1080 RGBA video frames with true 8-bit alpha transparency
for NDI video senders and video switcher inputs (OBS Studio, vMix, TriCaster).
"""

import io
import logging
from pathlib import Path
import time
from typing import List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont

from src.domain.models import StageOverlayCard

logger = logging.getLogger(__name__)


class StageFrameRenderer:
    """
    Renders stage vocabulary lower-third overlay cards onto a transparent 1920x1080 canvas.
    Supports auto-decay timing, progress bar animation, early dismissal, and instant blackout blanking.
    """

    def __init__(self, width: int = 1920, height: int = 1080):
        self.width = width
        self.height = height

        # Active card state
        self._active_card: Optional[StageOverlayCard] = None
        self._card_shown_at: float = 0.0
        self._card_expires_at: float = 0.0
        self._is_blackout: bool = False

        # Fonts
        self._font_tag: ImageFont.ImageFont = self._load_font(13, bold=True)
        self._font_word: ImageFont.ImageFont = self._load_font(34, bold=True)
        self._font_syn_label: ImageFont.ImageFont = self._load_font(15, bold=True)
        self._font_syn_text: ImageFont.ImageFont = self._load_font(17, bold=False)

        # Cached transparent base image (reused when no card is active)
        self._blank_image: Image.Image = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        self._blank_png_bytes: bytes = self._encode_png(self._blank_image)

        # Dynamic cache
        self._last_rendered_time: float = 0.0
        self._cached_image: Optional[Image.Image] = None
        self._cached_png_bytes: Optional[bytes] = None
        self._cached_raw_rgba: Optional[bytes] = None

    def _load_font(self, size: int, bold: bool = False) -> ImageFont.ImageFont:
        """Finds and loads the cleanest sans-serif font available on the host system."""
        candidate_paths = [
            # Liberation Sans
            f"/usr/share/fonts/truetype/liberation/LiberationSans-{'Bold' if bold else 'Regular'}.ttf",
            # DejaVu Sans
            f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'-Bold' if bold else ''}.ttf",
            # FreeSans
            f"/usr/share/fonts/truetype/freefont/FreeSans{'Bold' if bold else ''}.ttf",
            # Windows / macOS fallbacks
            "/usr/share/fonts/truetype/msttcorefonts/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
            "C:\\Windows\\Fonts\\arial.ttf",
        ]

        for path in candidate_paths:
            if Path(path).exists():
                try:
                    return ImageFont.truetype(path, size=size)
                except Exception:
                    continue

        # Pillow built-in default font fallback
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            # Older Pillow version without size parameter
            return ImageFont.load_default()

    def set_card(self, card: Optional[StageOverlayCard]) -> None:
        """Sets the active lower-third card to display with a decay timer."""
        self._active_card = card
        now = time.time()
        self._card_shown_at = now
        if card:
            self._card_expires_at = now + card.display_duration_s
        else:
            self._card_expires_at = 0.0
        self._invalidate_cache()

    def dismiss_card(self) -> None:
        """Dismisses the currently active card immediately."""
        self._active_card = None
        self._card_expires_at = 0.0
        self._invalidate_cache()

    def set_blackout(self, is_blackout: bool) -> None:
        """Enforces or clears stage blackout."""
        self._is_blackout = is_blackout
        if is_blackout:
            self._active_card = None
            self._card_expires_at = 0.0
        self._invalidate_cache()

    def _invalidate_cache(self) -> None:
        """Clears the cached rendered frame."""
        self._cached_image = None
        self._cached_png_bytes = None
        self._cached_raw_rgba = None

    @property
    def is_card_active(self) -> bool:
        """Returns True if a card is currently active and within its display duration."""
        if self._is_blackout or self._active_card is None:
            return False
        return time.time() < self._card_expires_at

    @property
    def active_card(self) -> Optional[StageOverlayCard]:
        """Returns the currently active card if unexpired and not blacked out."""
        return self._active_card if self.is_card_active else None

    def render_frame(self) -> Image.Image:
        """
        Renders the 1920x1080 RGBA frame.
        If no card is active or in blackout, returns a 100% transparent canvas.
        """
        now = time.time()

        # Check expiration
        if self._active_card and now >= self._card_expires_at:
            self._active_card = None
            self._invalidate_cache()

        if self._is_blackout or self._active_card is None:
            return self._blank_image

        # Re-render active card with current progress
        card = self._active_card
        elapsed = now - self._card_shown_at
        remaining = max(0.0, self._card_expires_at - now)
        duration = max(0.1, card.display_duration_s)
        progress_ratio = max(0.0, min(1.0, remaining / duration))

        img = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Lower-third card dimensions and position (bottom-right safe area)
        card_w, card_h = 580, 180
        x0 = self.width - 64 - card_w   # 1276
        y0 = self.height - 64 - card_h  # 836
        x1 = x0 + card_w                # 1856
        y1 = y0 + card_h                # 1016

        # 1. Card backdrop with glassmorphic obsidian styling
        # Semi-transparent dark navy fill (9, 14, 26, 240)
        draw.rounded_rectangle(
            [x0, y0, x1, y1],
            radius=18,
            fill=(9, 14, 26, 242),
            outline=(56, 189, 248, 160),
            width=2,
        )

        # 2. Category / Brand Tag Pill
        tag_text = "VERBACLEAR LIVE"
        tag_x0, tag_y0 = x0 + 26, y0 + 20
        tag_x1, tag_y1 = tag_x0 + 160, tag_y0 + 24
        draw.rounded_rectangle(
            [tag_x0, tag_y0, tag_x1, tag_y1],
            radius=6,
            fill=(56, 189, 248, 30),
            outline=(56, 189, 248, 90),
            width=1,
        )
        draw.text((tag_x0 + 10, tag_y0 + 5), tag_text, fill=(56, 189, 248, 255), font=self._font_tag)

        # 3. Main Headword / Lemma
        word_text = card.word.upper()
        draw.text((x0 + 26, y0 + 56), word_text, fill=(255, 255, 255, 255), font=self._font_word)

        # 4. Synonyms Line
        synonyms_str = ", ".join(card.synonyms) if card.synonyms else "—"
        syn_y = y0 + 110
        draw.text((x0 + 26, syn_y), "SYNONYMS:", fill=(148, 163, 184, 255), font=self._font_syn_label)
        draw.text((x0 + 130, syn_y), synonyms_str, fill=(241, 245, 249, 255), font=self._font_syn_text)

        # 5. Decay Progress Bar
        bar_x0 = x0 + 26
        bar_y0 = y1 - 16
        bar_x1 = x1 - 26
        bar_y1 = y1 - 12
        full_w = bar_x1 - bar_x0
        current_w = int(full_w * progress_ratio)

        # Background track
        draw.rounded_rectangle([bar_x0, bar_y0, bar_x1, bar_y1], radius=2, fill=(30, 41, 59, 180))
        # Active progress fill
        if current_w > 0:
            draw.rounded_rectangle([bar_x0, bar_y0, bar_x0 + current_w, bar_y1], radius=2, fill=(56, 189, 248, 230))

        return img

    def get_png_bytes(self) -> bytes:
        """Returns PNG-encoded bytes of the current 1920x1080 frame."""
        now = time.time()
        # Fast path: blank frame
        if self._is_blackout or self._active_card is None or now >= self._card_expires_at:
            return self._blank_png_bytes

        img = self.render_frame()
        return self._encode_png(img)

    def get_raw_rgba_bytes(self) -> bytes:
        """Returns raw 1920x1080x4 uncompressed RGBA byte buffer for NDI."""
        img = self.render_frame()
        return img.tobytes("raw", "RGBA")

    @staticmethod
    def _encode_png(img: Image.Image) -> bytes:
        """Encodes an Image into a PNG byte stream."""
        buf = io.BytesIO()
        img.save(buf, format="PNG", compress_level=1)  # compress_level=1 for high-speed real-time encoding
        return buf.getvalue()
